from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from psycopg.rows import dict_row

from index_advisor.config import load_config
from index_advisor.db import check_required_extensions, ensure_storage_database_exists, get_storage_connection, get_target_connection
from index_advisor.storage.repositories import workload as repo
from index_advisor.utils.sql_utils import (
    has_parameters,
    is_internal_query,
    is_select_query,
    is_safe_identifier,
    validate_table_and_columns,
)
from index_advisor.targets.postgres.analyzer.plan_utils import extract_filter_columns, extract_plan_rows, find_scan_nodes
from index_advisor.targets.postgres.analyzer.index_utils import IndexColumn, build_deterministic_index_name, create_index_sql
from index_advisor.targets.postgres.analyzer.candidate_generation import IndexCandidate, generate_parameterized_index_candidates
from index_advisor.targets.postgres.analyzer.hypopg_validator import validate_with_hypopg
from index_advisor.targets.postgres.analyzer.query_parser import PlaceholderUse, parse_select_from_where
from index_advisor.targets.postgres.analyzer.sample_validation import (
    SampleValidationResult,
    sample_validate_parameterized_query,
    score_sample_validated,
 )

logger = logging.getLogger(__name__)


def _write_pressure(table_row: dict[str, Any]) -> float:
    """
    Bounded write pressure in range 0..1.

    Old logic was writes / scans, which can become huge right after bulk inserts.
    This version describes how write-heavy the table is relative to all observed
    read/write activity.
    """
    seq_scan = int(table_row.get("seq_scan", 0) or 0)
    idx_scan = int(table_row.get("idx_scan", 0) or 0)
    writes = int(table_row.get("writes", 0) or 0)
    denom = max(seq_scan + idx_scan + writes, 1)
    return float(writes) / float(denom)


def _candidate_key(
    schemaname: str,
    table_name: str,
    columns: list[str | IndexColumn],
    include_columns: list[str] | None = None,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    rendered = []
    for c in columns:
        if isinstance(c, IndexColumn):
            rendered.append(f"{c.name.lower()}:{(c.direction or "").upper()}")
        else:
            rendered.append(str(c).lower())
    return (schemaname.lower(), table_name.lower(), tuple(rendered), tuple(c.lower() for c in (include_columns or [])))


def _normalize_indexdef(indexdef: str) -> str:
    return " ".join((indexdef or "").replace('"', '').lower().split())


def _render_index_column_for_match(column: str | IndexColumn) -> str:
    if isinstance(column, IndexColumn):
        direction = (column.direction or "").strip().lower()
        return f"{column.name.lower()} {direction}".strip()
    return str(column).lower()


def _split_index_columns(definition_columns: str) -> list[str]:
    """Split an index column list on top-level commas only."""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(definition_columns):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(definition_columns[start:i].strip())
            start = i + 1
    tail = definition_columns[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _extract_index_key_columns(indexdef: str, *, schemaname: str, table_name: str) -> list[str]:
    """Return normalized key columns from a CREATE INDEX statement.

    This deliberately avoids substring prefix checks. For example, an index on
    (order_item_id) must not be treated as covering a recommendation for
    (order_id).
    """
    dl = _normalize_indexdef(indexdef)
    table_patterns = [
        rf"\bon\s+{re.escape(schemaname.lower())}\.{re.escape(table_name.lower())}\s+(?:using\s+\w+\s+)?\((?P<cols>[^)]*)\)",
        rf"\bon\s+{re.escape(table_name.lower())}\s+(?:using\s+\w+\s+)?\((?P<cols>[^)]*)\)",
    ]

    cols_text: str | None = None
    for pattern in table_patterns:
        m = re.search(pattern, dl, flags=re.IGNORECASE)
        if m:
            cols_text = m.group("cols")
            break

    if not cols_text:
        return []

    normalized: list[str] = []
    for col in _split_index_columns(cols_text):
        c = col.strip().replace('"', '').lower()
        # Skip expression indexes for this simple coverage check.
        if "(" in c or ")" in c:
            normalized.append(c)
            continue
        # Remove common decorations that do not change the key column identity.
        c = re.sub(r"\s+collate\s+\S+", "", c)
        c = re.sub(r"\s+opclass\s+\S+", "", c)
        c = re.sub(r"\s+nulls\s+(?:first|last)\b", "", c)
        c = re.sub(r"\s+asc\b", "", c)
        c = re.sub(r"\s+desc\b", " desc", c)
        c = " ".join(c.split())
        normalized.append(c)
    return normalized


def _index_seems_to_exist(
    index_defs: list[str],
    *,
    schemaname: str,
    table_name: str,
    columns: list[str | IndexColumn],
    include_columns: list[str] | None = None,
) -> bool:
    """Return True when an existing index has the requested key prefix.

    A stronger compound index should satisfy a weaker prefix recommendation. For
    example, an existing index on (customer_id, order_date DESC) should suppress
    a recommendation for (customer_id). Matching is column-aware, not substring
    based, so (order_item_id) does not match (order_id).
    """
    if not columns:
        return False

    requested = [_render_index_column_for_match(c) for c in columns]
    requested = [" ".join(c.replace('"', '').lower().split()) for c in requested]

    for raw in index_defs:
        dl = _normalize_indexdef(raw)
        existing_cols = _extract_index_key_columns(raw, schemaname=schemaname, table_name=table_name)
        if not existing_cols or len(existing_cols) < len(requested):
            continue

        prefix_matches = True
        for requested_col, existing_col in zip(requested, existing_cols):
            if requested_col != existing_col:
                prefix_matches = False
                break

        if not prefix_matches:
            continue

        # INCLUDE columns are optional coverage. If requested, make sure they are
        # present somewhere in the index definition as whole identifiers.
        missing_include = []
        for c in (include_columns or []):
            if not c:
                continue
            pattern = rf"(?<![a-z0-9_]){re.escape(c.lower())}(?![a-z0-9_])"
            if not re.search(pattern, dl):
                missing_include.append(c.lower())
        if not missing_include:
            return True
    return False


def _strip_heavy_option_plan_fields(option: dict[str, Any]) -> dict[str, Any]:
    clean = dict(option)
    clean.pop("original_plan_json", None)
    clean.pop("hypothetical_plan_json", None)
    return clean


def _extract_index_name_from_create_sql(create_sql: str) -> str | None:
    m = re.search(r'create\s+index(?:\s+concurrently)?(?:\s+if\s+not\s+exists)?\s+"?([a-zA-Z0-9_]+)"?', create_sql or '', re.IGNORECASE)
    return m.group(1).lower() if m else None


def _existing_index_name_present(index_defs: list[str], index_name: str | None) -> bool:
    if not index_name:
        return False
    needle = f" index {index_name.lower()} "
    return any(needle in _normalize_indexdef(d) for d in index_defs)


def _refresh_recommendation_lifecycle_from_existing_indexes(
    sconn,
    *,
    target_id: int | None,
    index_defs_by_table: dict[tuple[str, str], list[str]],
) -> None:
    """Mark previously-active recommendations as resolved/applied if an index now exists.

    This keeps the main recommendations page clean after the DBA manually creates
    an index. We keep the historical row instead of deleting it.
    """
    params: list[Any] = []
    where = "r.status = 'ACTIVE'"
    if target_id is not None:
        where += " AND cr.target_id = %s"
        params.append(target_id)

    sconn.row_factory = dict_row
    with sconn.cursor() as cur:
        cur.execute(
            f"""
            SELECT r.id, r.schemaname, r.table_name, r.columns, r.recommended_index_sql
            FROM index_advisor.recommendations r
            JOIN index_advisor.collection_runs cr ON cr.id = r.collection_run_id
            WHERE {where};
            """,
            tuple(params),
        )
        rows = list(cur.fetchall())

    for rec in rows:
        schemaname = str(rec["schemaname"])
        table_name = str(rec["table_name"])
        cols = [str(c) for c in (rec.get("columns") or [])]
        index_defs = index_defs_by_table.get((schemaname, table_name), [])
        if not cols or not index_defs:
            continue

        if _index_seems_to_exist(index_defs, schemaname=schemaname, table_name=table_name, columns=cols):
            recommended_index_name = _extract_index_name_from_create_sql(str(rec.get("recommended_index_sql") or ""))
            if _existing_index_name_present(index_defs, recommended_index_name):
                status = "APPLIED"
                reason = "The exact recommended index name now exists on the target database. This recommendation is hidden from active recommendations but kept for history."
            else:
                status = "RESOLVED_BY_EXISTING_INDEX"
                reason = "A matching or stronger existing index was detected on the target database. This recommendation is hidden from active recommendations but kept for history."
            repo.update_recommendation_status(
                sconn,
                int(rec["id"]),
                status,
                reason,
            )


def analyze_latest_run(target_id: int | None = None) -> int:
    cfg = load_config()
    ensure_storage_database_exists()
    check_required_extensions(require_hypopg=True, target_id=target_id)

    with get_storage_connection() as sconn, get_target_connection(target_id) as tconn:
        run = repo.get_latest_completed_collection_run(sconn, target_id=target_id)
        if not run:
            logger.warning("No completed collection_run found in storage.")
            return 0

        logger.info("Analyzing latest completed run_id=%s", run.id)

        query_stats = repo.get_query_stats_for_run(sconn, run.id)
        table_stats = repo.get_table_stats_for_run(sconn, run.id)
        index_stats = repo.get_index_stats_for_run(sconn, run.id)
        query_plans = repo.get_query_plans_for_run(sconn, run.id)

        stats_by_queryid: dict[str, dict[str, Any]] = {str(r["queryid"]): r for r in query_stats}

        table_by_name: dict[tuple[str, str], dict[str, Any]] = {
            (str(r["schemaname"]), str(r["table_name"])): r for r in table_stats
        }

        index_defs_by_table: dict[tuple[str, str], list[str]] = {}
        for r in index_stats:
            key = (str(r["schemaname"]), str(r["table_name"]))
            index_defs_by_table.setdefault(key, []).append(str(r.get("indexdef", "")))

        _refresh_recommendation_lifecycle_from_existing_indexes(
            sconn, target_id=target_id, index_defs_by_table=index_defs_by_table
        )
        sconn.commit()

        # Limit analysis to top queries by total_exec_time, but only if we have plans captured.
        top_queryids = [
            str(r["queryid"])
            for r in sorted(query_stats, key=lambda x: float(x.get("total_exec_time", 0.0)), reverse=True)[
                : cfg.analyze_query_limit
            ]
        ]
        top_queryids_set = set(top_queryids)
        plans_to_analyze = [p for p in query_plans if str(p.get("queryid")) in top_queryids_set]

        logger.info("Plans available=%d; plans selected for analysis=%d", len(query_plans), len(plans_to_analyze))

        param_detected = 0
        sample_attempted = 0
        sample_succeeded = 0
        sample_failed = 0
        sampled_skipped = 0
        stored_validated = 0
        stored_sample_validated = 0

        candidates_generated = 0
        skipped_existing_index = 0
        skipped_write_pressure = 0
        exact_duplicates_skipped = 0
        validated = 0
        stored = 0
        stored_candidate_keys: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()

        for p in plans_to_analyze:
            queryid = str(p.get("queryid", ""))
            query_text = str(p.get("query_text", "")).strip().rstrip(";")
            if not query_text or not is_select_query(query_text):
                continue
            if is_internal_query(query_text):
                logger.info("Skipping internal query during analysis for queryid=%s", queryid)
                continue

            plan_obj: Any = p.get("plan")
            if isinstance(plan_obj, str):
                try:
                    plan_obj = json.loads(plan_obj)
                except Exception:
                    logger.warning("Skipping plan: could not parse json for queryid=%s", queryid)
                    continue

            try:
                scan_nodes = find_scan_nodes(plan_obj)
            except Exception:
                logger.exception("Plan parsing failed for queryid=%s; skipping", queryid)
                continue

            if not scan_nodes:
                continue

            for node in scan_nodes:
                schemaname = str(node.get("Schema") or "public")
                table_name = str(node.get("Relation Name") or "")
                filter_text = node.get("Filter")
                total_cost = node.get("Total Cost")
                plan_rows = extract_plan_rows(node)

                if not table_name:
                    continue

                cols = extract_filter_columns(str(filter_text) if filter_text is not None else None)
                cols = [col for col in cols if is_safe_identifier(col)][:2]
                if not cols:
                    continue

                valid, missing_columns = validate_table_and_columns(tconn, schemaname, table_name, cols)
                if not valid:
                    logger.info(
                        "Skipping analysis candidate for queryid=%s because unresolved table/column %s.%s missing=%s",
                        queryid,
                        schemaname,
                        table_name,
                        missing_columns,
                    )
                    continue

                candidates_generated += 1

                table_row = table_by_name.get((schemaname, table_name))
                if table_row:
                    write_pressure = _write_pressure(table_row)
                    if write_pressure > cfg.max_write_ratio_for_index:
                        skipped_write_pressure += 1
                        continue
                else:
                    write_pressure = 0.0

                index_defs = index_defs_by_table.get((schemaname, table_name), [])
                if _index_seems_to_exist(index_defs, schemaname=schemaname, table_name=table_name, columns=cols):
                    skipped_existing_index += 1
                    continue

                key = _candidate_key(schemaname, table_name, cols)
                if key in stored_candidate_keys:
                    exact_duplicates_skipped += 1
                    continue

                idx_name = build_deterministic_index_name(table_name, cols)
                stmt = create_index_sql(
                    index_name=idx_name,
                    schemaname=schemaname,
                    table_name=table_name,
                    columns=cols,
                    concurrently=True,
                    if_not_exists=True,
                )
                create_sql_text = stmt.as_string(tconn)

                # Validate with HypoPG per candidate; do not crash the whole run on one failure.
                try:
                    hypores = validate_with_hypopg(tconn, query_text=query_text, create_index_sql_text=create_sql_text)
                except Exception:
                    logger.exception("HypoPG validation failed for queryid=%s; rolling back and skipping", queryid)
                    try:
                        tconn.rollback()
                    except Exception:
                        pass
                    continue
                validated += 1

                improvement = hypores.improvement_pct if hypores.improvement_pct is not None else 0.0
                if improvement < cfg.min_recommendation_improvement_pct:
                    continue

                qstat = stats_by_queryid.get(queryid, {})
                q_total_exec = float(qstat.get("total_exec_time", 0.0) or 0.0)

                calls = int(qstat.get("calls", 0) or 0)
                score = score_sample_validated(
                    improvement_pct=float(improvement),
                    total_exec_time=q_total_exec,
                    calls=calls,
                    write_pressure=write_pressure,
                )
                reason = (
                    f"Detected {node.get('Node Type')} on {schemaname}.{table_name} with filter={filter_text!s}. "
                    f"HypoPG cost improvement={improvement:.1f}% (orig={hypores.original_cost}, hypo={hypores.hypothetical_cost}). "
                    f"total_exec_time={q_total_exec:.2f}ms, write_pressure={write_pressure:.2f}, plan_rows={plan_rows}, node_total_cost={total_cost}"
                )

                try:
                    rec_id = repo.insert_recommendation(
                        sconn,
                        run.id,
                        queryid=queryid,
                        schemaname=schemaname,
                        table_name=table_name,
                        columns=cols,
                        recommended_index_sql=create_sql_text,
                        score=float(score),
                        reason=reason,
                        validated=bool(hypores.validated),
                        original_cost=hypores.original_cost,
                        hypothetical_cost=hypores.hypothetical_cost,
                        improvement_pct=hypores.improvement_pct,
                        validation_type="VALIDATED",
                        parameterized_query=False,
                        sampled_validation=False,
                        normalized_query_text=query_text,
                        sampled_query_text=None,
                    )
                    repo.insert_recommendation_validation(
                        sconn,
                        recommendation_id=rec_id,
                        validation_type="AUTO_VALIDATION",
                        option_rank=1,
                        is_selected_option=True,
                        index_sql=create_sql_text,
                        rendered_query_text=query_text,
                        original_cost=hypores.original_cost,
                        hypothetical_cost=hypores.hypothetical_cost,
                        improvement_pct=hypores.improvement_pct,
                        original_plan_json=hypores.original_plan,
                        hypothetical_plan_json=hypores.hypothetical_plan,
                    )
                    sconn.commit()
                    stored_candidate_keys.add(key)
                    stored += 1
                    stored_validated += 1
                except Exception:
                    logger.exception("Failed storing recommendation for queryid=%s", queryid)
                    try:
                        sconn.rollback()
                    except Exception:
                        pass

        # SAMPLE-VALIDATED path for parameterized queries (no plans required).
        for qs in query_stats[: cfg.analyze_query_limit]:
            queryid = str(qs.get("queryid", ""))
            query_text = str(qs.get("query_text", qs.get("query", "")) or "").strip().rstrip(";")
            if not query_text or not is_select_query(query_text):
                continue
            if is_internal_query(query_text):
                sampled_skipped += 1
                logger.debug("queryid=%s skipped reason=internal_query", queryid)
                continue
            if not has_parameters(query_text):
                continue

            param_detected += 1

            parsed = parse_select_from_where(query_text)
            if not parsed:
                sampled_skipped += 1
                logger.info("queryid=%s skipped reason=parse_failed", queryid)
                continue

            logger.info(
                "queryid=%s parser=%s tables=%s aliases=%s unresolved=%s ambiguous=%s uses=%d",
                queryid,
                parsed.parser,
                {k: f"{v[0]}.{v[1]}" for k, v in parsed.table_name_map.items()},
                {k: f"{v[0]}.{v[1]}" for k, v in parsed.table_aliases.items()},
                parsed.unresolved_columns,
                parsed.ambiguous_columns,
                len(parsed.placeholder_uses),
            )

            # Generate candidates FIRST — do not gate on sample validation success.
            # Candidate generation only needs the parsed AST/placeholder uses.
            candidates = generate_parameterized_index_candidates(parsed, query_text)
            if not candidates:
                sampled_skipped += 1
                logger.info(
                    "queryid=%s skipped reason=no_candidates tables=%s",
                    queryid,
                    list(parsed.table_name_map.keys()),
                )
                continue

            logger.info(
                "queryid=%s candidate_generation count=%d types=%s",
                queryid,
                len(candidates),
                list({c.candidate_type for c in candidates}),
            )

            # Attempt sample validation to render a concrete query for HypoPG.
            sample_attempted += 1
            sv: SampleValidationResult = sample_validate_parameterized_query(
                tconn, parsed=parsed, original_query_text=query_text, queryid=queryid,
            )

            if not sv.ok or not sv.sampled_query_text or not sv.sampled_values:
                sample_failed += 1
                logger.info(
                    "queryid=%s sample_validation_failed — HypoPG validation skipped",
                    queryid,
                )
                continue

            sample_succeeded += 1
            logger.info(
                "queryid=%s sample_validation_succeeded sampled=%s",
                queryid, list((sv.sampled_values or {}).keys()),
            )

            # Validate all generated options for this query. Store only the best
            # candidate per (query, table) while preserving tested alternatives in JSON.
            grouped_candidates: dict[tuple[str, str], list[IndexCandidate]] = {}
            for candidate in candidates:
                grouped_candidates.setdefault((candidate.schemaname, candidate.table_name), []).append(candidate)

            for (schemaname, table_name), table_candidates in grouped_candidates.items():
                table_row = table_by_name.get((schemaname, table_name))
                if table_row:
                    write_pressure = _write_pressure(table_row)
                    if write_pressure > cfg.max_write_ratio_for_index:
                        skipped_write_pressure += len(table_candidates)
                        continue
                else:
                    write_pressure = 0.0

                index_defs = index_defs_by_table.get((schemaname, table_name), [])
                validated_options: list[dict[str, Any]] = []
                validated_candidate_results: list[tuple[IndexCandidate, str, Any]] = []

                for candidate in table_candidates:
                    if _index_seems_to_exist(
                        index_defs,
                        schemaname=candidate.schemaname,
                        table_name=candidate.table_name,
                        columns=candidate.key_columns,
                        include_columns=candidate.include_columns,
                    ):
                        skipped_existing_index += 1
                        continue

                    key = candidate.signature
                    if key in stored_candidate_keys:
                        exact_duplicates_skipped += 1
                        continue

                    valid, missing_columns = validate_table_and_columns(
                        tconn,
                        candidate.schemaname,
                        candidate.table_name,
                        candidate.columns + candidate.include_columns,
                    )
                    if not valid:
                        logger.info(
                            "Skipping generated candidate for queryid=%s because unresolved table/column %s.%s missing=%s",
                            queryid,
                            candidate.schemaname,
                            candidate.table_name,
                            missing_columns,
                        )
                        continue

                    candidates_generated += 1
                    idx_name = build_deterministic_index_name(
                        candidate.table_name,
                        candidate.key_columns,
                        include_columns=candidate.include_columns,
                    )
                    stmt = create_index_sql(
                        index_name=idx_name,
                        schemaname=candidate.schemaname,
                        table_name=candidate.table_name,
                        columns=candidate.key_columns,
                        include_columns=candidate.include_columns,
                        concurrently=True,
                        if_not_exists=True,
                    )
                    create_sql_text = stmt.as_string(tconn)

                    try:
                        hypores = validate_with_hypopg(
                            tconn, query_text=sv.sampled_query_text, create_index_sql_text=create_sql_text
                        )
                    except Exception:
                        logger.exception(
                            "HypoPG validation failed for parameterized queryid=%s candidate_type=%s; rolling back and skipping",
                            queryid,
                            candidate.candidate_type,
                        )
                        try:
                            tconn.rollback()
                        except Exception:
                            pass
                        continue

                    validated += 1
                    improvement = float(hypores.improvement_pct if hypores.improvement_pct is not None else 0.0)
                    validated_options.append(
                        candidate.option_json(
                            index_sql=create_sql_text,
                            original_cost=hypores.original_cost,
                            hypothetical_cost=hypores.hypothetical_cost,
                            improvement_pct=hypores.improvement_pct,
                            validated=bool(hypores.validated),
                            original_plan_json=hypores.original_plan,
                            hypothetical_plan_json=hypores.hypothetical_plan,
                        )
                    )

                    validated_candidate_results.append((candidate, create_sql_text, hypores))

                if not validated_candidate_results:
                    continue

                max_improvement = max(
                    float(result.improvement_pct if result.improvement_pct is not None else 0.0)
                    for _candidate, _sql, result in validated_candidate_results
                )

                def candidate_preference(item):
                    candidate, _sql, result = item
                    improvement_value = float(result.improvement_pct if result.improvement_pct is not None else 0.0)

                    # Cost improvement is still the main safety gate, but when two
                    # options are very close, prefer the index that matches the query
                    # shape better. This prevents a plain join index like
                    # (customer_id) from beating a top-N pattern index like
                    # (customer_id, order_date DESC) just because their HypoPG costs
                    # are almost identical.
                    within_best_band = improvement_value >= (max_improvement - 2.0)
                    semantic_priority = {
                        "EQUALITY_ORDER_LIMIT_INDEX": 40,
                        "COVERING_EQUALITY_ORDER_LIMIT_INDEX": 30,
                        "EQUALITY_RANGE_INDEX": 20,
                        "FILTER_INDEX": 10,
                        "JOIN_INDEX": 10,
                    }.get(candidate.candidate_type, 0)

                    return (
                        1 if within_best_band else 0,
                        semantic_priority if within_best_band else 0,
                        improvement_value,
                        -len(candidate.include_columns),
                        -len(candidate.columns),
                    )

                best_candidate, best_sql, best_hypores = max(validated_candidate_results, key=candidate_preference)
                improvement = float(best_hypores.improvement_pct if best_hypores.improvement_pct is not None else 0.0)
                if improvement < cfg.min_recommendation_improvement_pct:
                    continue

                calls = int(qs.get("calls", 0) or 0)
                total_exec_time = float(qs.get("total_exec_time", 0.0) or 0.0)

                score = score_sample_validated(
                    improvement_pct=float(improvement),
                    total_exec_time=total_exec_time,
                    calls=calls,
                    write_pressure=write_pressure,
                )

                option_count = len(validated_options)
                def option_rank_key(option):
                    candidate_type = str(option.get("candidate_type") or "")
                    semantic_priority = {
                        "EQUALITY_ORDER_LIMIT_INDEX": 40,
                        "COVERING_EQUALITY_ORDER_LIMIT_INDEX": 30,
                        "EQUALITY_RANGE_INDEX": 20,
                        "FILTER_INDEX": 10,
                        "JOIN_INDEX": 10,
                    }.get(candidate_type, 0)
                    improvement_value = float(option.get("improvement_pct") or 0.0)
                    within_best_band = improvement_value >= (max_improvement - 2.0)
                    return (
                        1 if option.get("index_sql") == best_sql else 0,
                        1 if within_best_band else 0,
                        semantic_priority if within_best_band else 0,
                        improvement_value,
                    )

                best_rank = sorted(
                    validated_options,
                    key=option_rank_key,
                    reverse=True,
                )
                alternative_options = []
                for rank, option in enumerate(best_rank, start=1):
                    option = dict(option)
                    option["rank"] = rank
                    option["selected"] = option.get("index_sql") == best_sql
                    alternative_options.append(_strip_heavy_option_plan_fields(option))

                reason = (
                    "Best index chosen after generating and validating multiple candidate options with HypoPG. "
                    f"Selected candidate_type={best_candidate.candidate_type}. "
                    f"Reason: {best_candidate.explanation} "
                    "Recommendation validated using sampled parameter values because original query used bind parameters. "
                    "Actual workload performance may vary depending on runtime parameter distribution. "
                    f"Improvement={improvement:.1f}% (orig={best_hypores.original_cost}, hypo={best_hypores.hypothetical_cost}). "
                    f"calls={calls}, total_exec_time={total_exec_time:.2f}ms, write_pressure={write_pressure:.2f}, "
                    f"tested_options={option_count}"
                )

                try:
                    rec_id = repo.insert_recommendation(
                        sconn,
                        run.id,
                        queryid=queryid,
                        schemaname=best_candidate.schemaname,
                        table_name=best_candidate.table_name,
                        columns=best_candidate.columns,
                        recommended_index_sql=best_sql,
                        score=float(score),
                        reason=reason,
                        validated=bool(best_hypores.validated),
                        original_cost=best_hypores.original_cost,
                        hypothetical_cost=best_hypores.hypothetical_cost,
                        improvement_pct=best_hypores.improvement_pct,
                        validation_type="SAMPLE_VALIDATED",
                        parameterized_query=True,
                        sampled_validation=True,
                        normalized_query_text=parsed.normalized_query,
                        sampled_query_text=sv.sampled_query_text,
                        alternative_options_json=alternative_options,
                    )

                    options_by_sql = {str(option.get("index_sql")): option for option in alternative_options}
                    for candidate, option_sql, option_result in validated_candidate_results:
                        stored_option = options_by_sql.get(option_sql, {})
                        repo.insert_recommendation_validation(
                            sconn,
                            recommendation_id=rec_id,
                            validation_type="SAMPLED_VALIDATION",
                            option_rank=stored_option.get("rank"),
                            is_selected_option=option_sql == best_sql,
                            index_sql=option_sql,
                            bind_values_json=sv.sampled_values,
                            rendered_query_text=sv.sampled_query_text,
                            original_cost=option_result.original_cost,
                            hypothetical_cost=option_result.hypothetical_cost,
                            improvement_pct=option_result.improvement_pct,
                            original_plan_json=option_result.original_plan,
                            hypothetical_plan_json=option_result.hypothetical_plan,
                        )
                    sconn.commit()
                    for option in alternative_options:
                        cols_for_key = [
                            IndexColumn(c, (option.get("column_directions") or {}).get(c))
                            for c in option.get("columns", [])
                        ]
                        stored_candidate_keys.add(
                            _candidate_key(
                                str(option.get("schemaname") or best_candidate.schemaname),
                                str(option.get("table_name") or best_candidate.table_name),
                                cols_for_key,
                                list(option.get("include_columns") or []),
                            )
                        )
                    stored += 1
                    stored_sample_validated += 1
                except Exception:
                    logger.exception("Failed storing SAMPLE_VALIDATED recommendation for queryid=%s", queryid)
                    try:
                        sconn.rollback()
                    except Exception:
                        pass

        logger.info(
            "Analyzer summary for run_id=%s: plans_analyzed=%d candidates_generated=%d "
            "skipped_existing_index=%d skipped_write_pressure=%d exact_duplicates_skipped=%d validated=%d stored=%d",
            run.id,
            len(plans_to_analyze),
            candidates_generated,
            skipped_existing_index,
            skipped_write_pressure,
            exact_duplicates_skipped,
            validated,
            stored,
        )
        logger.info(
            "Parameterized summary: detected=%d sample_attempted=%d sample_succeeded=%d sample_failed=%d sampled_skipped=%d "
            "stored_validated=%d stored_sample_validated=%d",
            param_detected,
            sample_attempted,
            sample_succeeded,
            sample_failed,
            sampled_skipped,
            stored_validated,
            stored_sample_validated,
        )
        return stored

