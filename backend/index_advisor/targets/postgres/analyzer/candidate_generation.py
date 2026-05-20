from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp

from index_advisor.targets.postgres.analyzer.index_utils import IndexColumn
from index_advisor.targets.postgres.analyzer.query_parser import ParsedQuery, PlaceholderUse, normalize_sql
from index_advisor.utils.sql_utils import is_safe_identifier


@dataclass(frozen=True)
class IndexCandidate:
    schemaname: str
    table_name: str
    columns: list[str]
    column_directions: dict[str, str] = field(default_factory=dict)
    include_columns: list[str] = field(default_factory=list)
    candidate_type: str = "SIMPLE"
    explanation: str = ""

    @property
    def key_columns(self) -> list[IndexColumn]:
        return [IndexColumn(c, self.column_directions.get(c)) for c in self.columns]

    @property
    def signature(self) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
        rendered = tuple(
            f"{c.lower()}:{(self.column_directions.get(c) or '').upper()}" for c in self.columns
        )
        includes = tuple(c.lower() for c in self.include_columns)
        return (self.schemaname.lower(), self.table_name.lower(), rendered, includes)

    def option_json(
        self,
        *,
        index_sql: str,
        original_cost: float | None,
        hypothetical_cost: float | None,
        improvement_pct: float | None,
        validated: bool,
        original_plan_json: Any | None = None,
        hypothetical_plan_json: Any | None = None,
    ) -> dict[str, Any]:
        return {
            "candidate_type": self.candidate_type,
            "index_sql": index_sql,
            "schemaname": self.schemaname,
            "table_name": self.table_name,
            "columns": self.columns,
            "column_directions": self.column_directions,
            "include_columns": self.include_columns,
            "reason": self.explanation,
            "validated": validated,
            "original_cost": original_cost,
            "hypothetical_cost": hypothetical_cost,
            "improvement_pct": improvement_pct,
            "original_plan_json": original_plan_json,
            "hypothetical_plan_json": hypothetical_plan_json,
        }


def _column_parts(column: exp.Column) -> tuple[str | None, str | None]:
    parts = [str(part.name) if isinstance(part, exp.Identifier) else str(part) for part in getattr(column, "parts", [])]
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    if len(parts) == 1:
        return None, parts[0]
    return None, None


def _table_maps_for_select(select: exp.Select) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    aliases: dict[str, tuple[str, str]] = {}
    names: dict[str, tuple[str, str]] = {}

    def register(table: exp.Table | None) -> None:
        if table is None:
            return
        schema = str(table.args.get("db") or "public")
        table_name = str(table.this)
        alias = str(table.alias) if table.alias else None
        if not is_safe_identifier(schema) or not is_safe_identifier(table_name):
            return
        key = (schema, table_name)
        names.setdefault(table_name.lower(), key)
        if alias and is_safe_identifier(alias):
            aliases[alias.lower()] = key

    from_clause = select.args.get("from") or select.args.get("from_")
    if isinstance(from_clause, exp.From):
        if isinstance(from_clause.this, exp.Table):
            register(from_clause.this)
        for source in from_clause.expressions or []:
            if isinstance(source, exp.Table):
                register(source)

    for join in select.args.get("joins") or []:
        if isinstance(join.this, exp.Table):
            register(join.this)

    return aliases, names


def _resolve_column_in_select(
    column: exp.Column,
    aliases: dict[str, tuple[str, str]],
    names: dict[str, tuple[str, str]],
) -> tuple[str | None, str | None, str | None]:
    qualifier, col = _column_parts(column)
    if not col or not is_safe_identifier(col):
        return None, None, None

    if qualifier:
        resolved = aliases.get(qualifier.lower()) or names.get(qualifier.lower())
        if resolved:
            return resolved[0], resolved[1], col
        return None, None, col

    if len(names) == 1:
        schema, table = next(iter(names.values()))
        return schema, table, col

    return None, None, col


def _ordered_columns_by_table(sql: str) -> dict[tuple[str, str], list[IndexColumn]]:
    """
    Find ORDER BY columns inside SELECT blocks that also use LIMIT.
    This intentionally catches LATERAL/top-N patterns like:
      WHERE child.parent_id = parent.id ORDER BY child.created_at DESC LIMIT 1
    """
    output: dict[tuple[str, str], list[IndexColumn]] = {}
    try:
        expression = sqlglot.parse_one(normalize_sql(sql), read="postgres")
    except Exception:
        return output

    for select in expression.find_all(exp.Select):
        if not select.args.get("limit"):
            continue
        order = select.args.get("order")
        if not isinstance(order, exp.Order):
            continue

        aliases, names = _table_maps_for_select(select)
        for ordered in order.expressions or []:
            col_expr = ordered.this if isinstance(ordered, exp.Ordered) else ordered
            if not isinstance(col_expr, exp.Column):
                continue
            schema, table, col = _resolve_column_in_select(col_expr, aliases, names)
            if not schema or not table or not col:
                continue
            direction = "DESC" if bool(ordered.args.get("desc")) else "ASC"
            key = (schema, table)
            existing = [c.name.lower() for c in output.setdefault(key, [])]
            if col.lower() not in existing:
                output[key].append(IndexColumn(col, direction))
    return output


def _selected_columns_by_table(sql: str) -> dict[tuple[str, str], list[str]]:
    output: dict[tuple[str, str], list[str]] = {}
    try:
        expression = sqlglot.parse_one(normalize_sql(sql), read="postgres")
    except Exception:
        return output

    for select in expression.find_all(exp.Select):
        aliases, names = _table_maps_for_select(select)
        for expr in select.expressions or []:
            if not isinstance(expr, exp.Column):
                continue
            schema, table, col = _resolve_column_in_select(expr, aliases, names)
            if not schema or not table or not col:
                continue
            key = (schema, table)
            current = output.setdefault(key, [])
            if col not in current:
                current.append(col)
    return output


def _append_unique(items: list[str], value: str, limit: int | None = None) -> None:
    if not value or not is_safe_identifier(value):
        return
    if value not in items:
        if limit is None or len(items) < limit:
            items.append(value)


def _resolve_use(use: PlaceholderUse, parsed: ParsedQuery) -> PlaceholderUse | None:
    if use.schemaname and use.table_name:
        return use
    if len(parsed.table_name_map) == 1:
        schemaname, table_name = next(iter(parsed.table_name_map.values()))
        return PlaceholderUse(schemaname, table_name, use.alias, use.column, use.operator, use.placeholders, use.is_join)
    return None


def generate_parameterized_index_candidates(parsed: ParsedQuery, query_text: str) -> list[IndexCandidate]:
    """
    Generate multiple safe candidates for one parameterized SELECT.
    The analyzer will validate them with HypoPG and keep the best option.
    """
    filter_groups: dict[tuple[str, str], list[str]] = {}
    range_groups: dict[tuple[str, str], list[str]] = {}
    join_groups: dict[tuple[str, str], list[str]] = {}

    for raw_use in parsed.placeholder_uses:
        use = _resolve_use(raw_use, parsed)
        if not use or not use.schemaname or not use.table_name:
            continue
        if not is_safe_identifier(use.column):
            continue
        key = (use.schemaname, use.table_name)
        op = (use.operator or "").upper()
        if use.is_join:
            _append_unique(join_groups.setdefault(key, []), use.column, limit=3)
        elif use.placeholders and op in {"=", "IN"}:
            _append_unique(filter_groups.setdefault(key, []), use.column, limit=3)
        elif use.placeholders and op in {">", ">=", "<", "<="}:
            _append_unique(range_groups.setdefault(key, []), use.column, limit=2)

    order_by = _ordered_columns_by_table(query_text)
    selected = _selected_columns_by_table(query_text)

    candidates: list[IndexCandidate] = []
    seen: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()

    def add(candidate: IndexCandidate) -> None:
        if not candidate.columns:
            return
        if not all(is_safe_identifier(c) for c in candidate.columns):
            return
        if not all(is_safe_identifier(c) for c in candidate.include_columns):
            return
        if candidate.signature in seen:
            return
        seen.add(candidate.signature)
        candidates.append(candidate)

    all_tables = set(filter_groups) | set(range_groups) | set(join_groups) | set(order_by)
    for key in sorted(all_tables):
        schemaname, table_name = key
        eq_cols: list[str] = []
        for col in filter_groups.get(key, []):
            _append_unique(eq_cols, col, limit=3)
        for col in join_groups.get(key, []):
            _append_unique(eq_cols, col, limit=3)

        range_cols = range_groups.get(key, [])
        order_cols = order_by.get(key, [])

        if filter_groups.get(key):
            cols = filter_groups[key][:3]
            add(IndexCandidate(
                schemaname=schemaname,
                table_name=table_name,
                columns=cols,
                candidate_type="FILTER_INDEX",
                explanation="Supports equality/IN predicates that use bind parameters.",
            ))

        for join_col in join_groups.get(key, []):
            add(IndexCandidate(
                schemaname=schemaname,
                table_name=table_name,
                columns=[join_col],
                candidate_type="JOIN_INDEX",
                explanation="Supports an equality join lookup on this table.",
            ))

        if eq_cols and range_cols:
            cols = eq_cols[:2]
            _append_unique(cols, range_cols[0], limit=3)
            add(IndexCandidate(
                schemaname=schemaname,
                table_name=table_name,
                columns=cols,
                candidate_type="EQUALITY_RANGE_INDEX",
                explanation="Places equality/join columns first, then the range predicate column.",
            ))

        if eq_cols and order_cols:
            cols = eq_cols[:2]
            directions: dict[str, str] = {}
            for order_col in order_cols[:2]:
                if order_col.name not in cols:
                    _append_unique(cols, order_col.name, limit=4)
                    if order_col.direction:
                        directions[order_col.name] = order_col.direction.upper()

            add(IndexCandidate(
                schemaname=schemaname,
                table_name=table_name,
                columns=cols,
                column_directions=directions,
                candidate_type="EQUALITY_ORDER_LIMIT_INDEX",
                explanation="Matches equality/join lookup plus ORDER BY/LIMIT, allowing PostgreSQL to seek directly to the first ordered rows.",
            ))

            # Covering variant as an alternative. Keep INCLUDE small and conservative.
            include_cols: list[str] = []
            key_set = {c.lower() for c in cols}
            for col in selected.get(key, []):
                if col.lower() not in key_set:
                    _append_unique(include_cols, col, limit=2)
            if include_cols:
                add(IndexCandidate(
                    schemaname=schemaname,
                    table_name=table_name,
                    columns=cols,
                    column_directions=directions,
                    include_columns=include_cols,
                    candidate_type="COVERING_EQUALITY_ORDER_LIMIT_INDEX",
                    explanation="Covering alternative for the equality + ORDER BY/LIMIT pattern. INCLUDE may reduce heap access but increases index size.",
                ))

    return candidates
