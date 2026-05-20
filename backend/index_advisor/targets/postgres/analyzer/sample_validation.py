from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql

from index_advisor.targets.postgres.analyzer.hypopg_validator import validate_with_hypopg, HypoPgResult
from index_advisor.targets.postgres.analyzer.query_parser import ParsedQuery, PlaceholderUse, extract_placeholder_uses, is_parameterized
from index_advisor.targets.postgres.analyzer.value_sampling import sample_n_non_null_values, sample_row_non_null_values
from index_advisor.utils.sql_utils import (
    is_internal_query,
    is_safe_identifier,
    validate_table_and_columns,
)

logger = logging.getLogger(__name__)


_DOLLAR_PARAM_RE = re.compile(r"\$(\d+)")
_QMARK_RE = re.compile(r"\?")


@dataclass(frozen=True)
class SampleValidationResult:
    ok: bool
    sampled_query_text: str | None
    sampled_values: dict[str, Any] | None
    hypopg: HypoPgResult | None


def _sql_literal(conn: psycopg.Connection, value: Any) -> str:
    # psycopg.sql.Literal quotes and escapes safely using the connection.
    return sql.Literal(value).as_string(conn)


_INTERVAL_CONTEXT_RE = re.compile(r"\binterval\s+\$\d+", re.IGNORECASE)
_LIMIT_CONTEXT_RE = re.compile(r"\bLIMIT\s+\$\d+", re.IGNORECASE)
_OFFSET_CONTEXT_RE = re.compile(r"\bOFFSET\s+\$\d+", re.IGNORECASE)


def _fill_remaining_placeholders(conn: psycopg.Connection, q: str) -> str:
    """
    Replace any remaining $N placeholders that were not resolved via column sampling.

    pg_stat_statements can normalize constants that are not real user bind values,
    including LIMIT numbers and boolean constants like `ON true`.  A blind fallback
    of `$N -> 1` is dangerous because PostgreSQL rejects `JOIN ... ON 1`.

    Context-aware defaults:
      - JOIN/WHERE boolean context -> true
      - LIMIT $N                  -> 100
      - OFFSET $N                 -> 0
      - interval $N               -> '7 days'
      - everything else           -> 1
    """
    remaining = sorted({int(m.group(1)) for m in _DOLLAR_PARAM_RE.finditer(q)}, reverse=True)
    if not remaining:
        return q

    for n in remaining:
        # interval $N must be a quoted interval string.
        pat = re.compile(rf"(\binterval\s+)\${n}\b", re.IGNORECASE)
        if pat.search(q):
            replacement = _sql_literal(conn, "7 days")
            q = pat.sub(lambda m: m.group(1) + replacement, q)
            continue

        # LIMIT/OFFSET placeholders are usually normalized constants.
        pat = re.compile(rf"(\bLIMIT\s+)\${n}\b", re.IGNORECASE)
        if pat.search(q):
            q = pat.sub(lambda m: m.group(1) + "100", q)
            continue

        pat = re.compile(rf"(\bOFFSET\s+)\${n}\b", re.IGNORECASE)
        if pat.search(q):
            q = pat.sub(lambda m: m.group(1) + "0", q)
            continue

        # Boolean contexts. pg_stat_statements may normalize `ON true` to `ON $N`.
        # PostgreSQL does not accept `ON 1`, so preserve boolean semantics.
        boolean_patterns = [
            re.compile(rf"(\bON\s+)\${n}\b", re.IGNORECASE),
            re.compile(rf"(\bWHERE\s+)\${n}\b", re.IGNORECASE),
            re.compile(rf"(\bAND\s+)\${n}\b", re.IGNORECASE),
            re.compile(rf"(\bOR\s+)\${n}\b", re.IGNORECASE),
            re.compile(rf"(\bHAVING\s+)\${n}\b", re.IGNORECASE),
        ]
        replaced_boolean = False
        for pat in boolean_patterns:
            if pat.search(q):
                q = pat.sub(lambda m: m.group(1) + "true", q)
                replaced_boolean = True
        if replaced_boolean:
            continue

        # Generic numeric fallback for unresolved predicates.
        q = re.sub(rf"\${n}\b", "1", q)

    return q


def _render_sampled_query(
    conn: psycopg.Connection,
    original_query: str,
    *,
    dollar_bind_values: dict[int, Any],
    qmark_values: list[Any],
    fill_remaining: bool = True,
) -> str | None:
    """
    Replace $1/$2/... and ? placeholders with SQL literals safely.

    When fill_remaining=True (default), any placeholders that were not resolved
    via column sampling (e.g. LIMIT $N, interval $N) are replaced with safe
    context-aware defaults so the query can be sent to HypoPG for EXPLAIN.
    """
    q = (original_query or "").strip().rstrip(";")

    # Strip pg_stat_statements truncation comments from the query so they don't
    # interfere with EXPLAIN, e.g.  IN ($1, $2 /* , ... */)
    q = re.sub(r"/\*\s*,\s*\.\.\.\s*\*/", "", q)

    # Replace $n by descending n to avoid $1 matching $10 prefix issues.
    for n in sorted(dollar_bind_values.keys(), reverse=True):
        lit = _sql_literal(conn, dollar_bind_values[n])
        q = re.sub(rf"\${n}\b", lit, q)

    # Replace ? placeholders left-to-right.
    if qmark_values:
        parts = _QMARK_RE.split(q)
        # split returns segments between ?; count of ? is len(parts)-1
        needed = len(parts) - 1
        if needed != len(qmark_values):
            return None
        out = parts[0]
        for seg, val in zip(parts[1:], qmark_values, strict=True):
            out += _sql_literal(conn, val) + seg
        q = out

    # Fill any remaining $N placeholders (LIMIT, interval, unresolved predicates).
    if fill_remaining and _DOLLAR_PARAM_RE.search(q):
        q = _fill_remaining_placeholders(conn, q)

    # Ensure no unresolved placeholders remain
    if _DOLLAR_PARAM_RE.search(q) or _QMARK_RE.search(q):
        return None
    return q


def sample_validate_parameterized_query(
    conn: psycopg.Connection,
    *,
    parsed: ParsedQuery,
    original_query_text: str,
    queryid: str = "",
) -> SampleValidationResult:
    """
    Sample values for placeholders tied to columns in WHERE clause, render a
    concrete query, and return it so HypoPG can validate hypothetical indexes.

    Strategy:
    - For each placeholder that can be mapped to a resolved (schema, table, column),
      sample a real value from that column.
    - For placeholders in ambiguous / multi-table positions, try a best-effort
      resolution rather than immediately bailing out.
    - For remaining unresolved placeholders (LIMIT $N, interval $N, etc.) fill
      with safe context-aware defaults in _render_sampled_query.
    - Only return ok=False when no placeholders could be resolved at all OR when
      the final rendered query still has unresolved $N after fill_remaining.

    Safety: caller must ensure query_text is a SELECT.
    """
    if is_internal_query(original_query_text):
        logger.debug("queryid=%s sample_validation_skipped reason=internal_query", queryid)
        return SampleValidationResult(False, None, None, None)

    if not is_parameterized(original_query_text):
        logger.debug("queryid=%s sample_validation_skipped reason=not_parameterized", queryid)
        return SampleValidationResult(False, None, None, None)

    uses = extract_placeholder_uses(parsed)
    # Proceed even when uses is empty — fill_remaining will handle LIMIT/interval params.

    try:
        dollar_map: dict[int, Any] = {}
        qmark_vals: list[Any] = []
        sampled_values: dict[str, Any] = {}

        # Group placeholder uses by resolved table and column.
        table_groups: dict[tuple[str, str], list[PlaceholderUse]] = {}
        skipped_uses: list[str] = []

        for use in uses:
            if not use.column:
                continue
            resolved_use = use

            if use.schemaname is None or use.table_name is None:
                # Try to resolve from the parsed table map.
                if len(parsed.table_name_map) == 1:
                    schemaname, table_name = next(iter(parsed.table_name_map.values()))
                    resolved_use = PlaceholderUse(
                        schemaname, table_name, parsed.alias,
                        use.column, use.operator, use.placeholders, use.is_join,
                    )
                else:
                    # For multi-table queries, try each table to find one that has this column.
                    matched: tuple[str, str] | None = None
                    for (sn, tn) in parsed.table_name_map.values():
                        valid, _ = validate_table_and_columns(conn, sn, tn, [use.column])
                        if valid:
                            matched = (sn, tn)
                            break
                    if matched:
                        resolved_use = PlaceholderUse(
                            matched[0], matched[1], use.alias,
                            use.column, use.operator, use.placeholders, use.is_join,
                        )
                    else:
                        logger.debug(
                            "queryid=%s sample_validation use skipped reason=column_unresolved column=%s",
                            queryid, use.column,
                        )
                        skipped_uses.append(use.column)
                        continue

            if resolved_use.schemaname is None or resolved_use.table_name is None:
                skipped_uses.append(use.column)
                continue

            table_groups.setdefault((resolved_use.schemaname, resolved_use.table_name), []).append(resolved_use)

        # Validate each referenced table/column before sampling.
        valid_groups: dict[tuple[str, str], list[PlaceholderUse]] = {}
        for (schemaname, table_name), group_uses in table_groups.items():
            columns = [u.column for u in group_uses if u.column]
            valid, missing = validate_table_and_columns(conn, schemaname, table_name, columns)
            if not valid:
                logger.debug(
                    "queryid=%s sample_validation group skipped reason=missing_columns table=%s.%s missing=%s",
                    queryid, schemaname, table_name, missing,
                )
                skipped_uses.extend(missing or columns)
                continue
            valid_groups[(schemaname, table_name)] = group_uses

        # Sample values for all resolvable uses.
        for (schemaname, table_name), group_uses in valid_groups.items():
            placeholder_columns: list[str] = []
            for use in group_uses:
                if use.placeholders:
                    placeholder_columns.append(use.column)
            placeholder_columns = list(dict.fromkeys(c for c in placeholder_columns if c))

            row_values: dict[str, Any] | None = None
            if len(set(placeholder_columns)) > 1:
                row_values = sample_row_non_null_values(
                    conn,
                    schemaname=schemaname,
                    table_name=table_name,
                    columns=placeholder_columns,
                )
                # row_values=None means table has no rows satisfying all columns — not fatal.

            for use in group_uses:
                if not use.placeholders:
                    continue
                if row_values is not None and use.column in row_values:
                    values = [row_values[use.column]] * len(use.placeholders)
                else:
                    count = len(use.placeholders)
                    values = sample_n_non_null_values(
                        conn,
                        schemaname=schemaname,
                        table_name=table_name,
                        column=use.column,
                        n=count,
                    )
                    if not values:
                        # No rows in table for this column — skip but don't abort.
                        logger.debug(
                            "queryid=%s sample_validation no_values table=%s.%s column=%s",
                            queryid, schemaname, table_name, use.column,
                        )
                        continue
                    # Pad with last value if fewer samples than placeholders.
                    while len(values) < count:
                        values.append(values[-1])

                for ph, value in zip(use.placeholders, values):
                    if ph.startswith("$"):
                        m = re.match(r"\$(\d+)", ph)
                        if not m:
                            logger.debug(
                                "queryid=%s sample_validation skipping unrecognised placeholder %r",
                                queryid, ph,
                            )
                            continue
                        n = int(m.group(1))
                        if n not in dollar_map:
                            dollar_map[n] = value
                            sampled_values[f"${n}"] = value
                    else:
                        qmark_vals.append(value)
                        sampled_values[f"?{len(qmark_vals)}"] = value

        # Render the query. fill_remaining=True fills LIMIT/interval/etc. with safe defaults.
        sampled_query = _render_sampled_query(
            conn, original_query_text,
            dollar_bind_values=dollar_map,
            qmark_values=qmark_vals,
            fill_remaining=True,
        )

        if not sampled_query:
            logger.debug(
                "queryid=%s sample_validation_failed reason=render_failed "
                "dollar_map_size=%d skipped_uses=%s",
                queryid, len(dollar_map), skipped_uses,
            )
            return SampleValidationResult(False, None, None, None)

        logger.debug(
            "queryid=%s sample_validation_succeeded sampled_params=%s",
            queryid, list(sampled_values.keys()),
        )
        return SampleValidationResult(True, sampled_query, sampled_values, None)

    except Exception:
        logger.exception("queryid=%s sample_validation_exception", queryid)
        try:
            conn.rollback()
        except Exception:
            pass
        return SampleValidationResult(False, None, None, None)


def score_sample_validated(
    *,
    improvement_pct: float,
    total_exec_time: float,
    calls: int,
    write_pressure: float,
) -> float:
    """Human-readable 0-100 priority score."""
    score = (
        improvement_pct * 0.55
        + min(math.log10(total_exec_time + 1.0) * 10.0, 25.0)
        + min(math.log10(float(calls) + 1.0) * 10.0, 20.0)
        - (write_pressure * 25.0)
    )
    return float(max(0.0, min(score, 100.0)))

