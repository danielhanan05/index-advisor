from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from index_advisor.utils.sql_utils import is_safe_identifier

_SINGLE_LINE_WS_RE = re.compile(r"\s+")
_DOLLAR_PARAM_RE = re.compile(r"\$(\d+)")
_QMARK_RE = re.compile(r"\?")
_INTERNAL_SKIP_RE = re.compile(
    r"\b(?:pg_catalog|information_schema|pg_toast|index_advisor|pg_stat_statements|pg_stat_activity|pg_stat_user_tables|pg_stat_user_indexes|pg_indexes|pg_extension|pg_show_all_settings|pg_database|hypopg|current_setting)\b",
    re.IGNORECASE,
)
_STATEMENT_SKIP_RE = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|SET|SHOW|DISCARD|DEALLOCATE|PREPARE|EXECUTE|EXPLAIN)\b", re.IGNORECASE)

_SUPPORTED_COMPARISONS = {
    exp.EQ: "=",
    exp.GT: ">",
    exp.GTE: ">=",
    exp.LT: "<",
    exp.LTE: "<=",
}


@dataclass(frozen=True)
class PlaceholderUse:
    schemaname: str | None
    table_name: str | None
    alias: str | None
    column: str
    operator: str
    placeholders: list[str]
    is_join: bool = False


@dataclass(frozen=True)
class ParsedQuery:
    normalized_query: str
    parser: str
    schemaname: str | None
    table_name: str | None
    alias: str | None
    where_clause: str | None
    table_aliases: dict[str, tuple[str, str]]
    table_name_map: dict[str, tuple[str, str]]
    placeholder_uses: list[PlaceholderUse]
    unresolved_columns: list[str]
    ambiguous_columns: list[str]


def normalize_sql(sql: str) -> str:
    s = (sql or "").strip().rstrip(";")
    return _SINGLE_LINE_WS_RE.sub(" ", s)


def is_parameterized(sql: str) -> bool:
    s = sql or ""
    return bool(_DOLLAR_PARAM_RE.search(s) or _QMARK_RE.search(s))


def _normalize_identifier(identifier: Any) -> str | None:
    if identifier is None:
        return None
    name = str(identifier)
    return name if is_safe_identifier(name) else None


def _parameter_text(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Parameter):
        return node.sql(dialect="postgres")
    return None


def _placeholders_from_expression(node: exp.Expression) -> list[str]:
    if isinstance(node, exp.Parameter):
        return [_parameter_text(node)] if _parameter_text(node) else []

    if isinstance(node, exp.Tuple):
        return [
            _parameter_text(expr)
            for expr in node.expressions
            if _parameter_text(expr)
        ]

    if isinstance(node, exp.Array):
        return [
            _parameter_text(expr)
            for expr in node.expressions
            if _parameter_text(expr)
        ]

    return []


def _column_parts(column: exp.Column) -> tuple[str | None, str | None, str | None]:
    parts = [
        str(part.name) if isinstance(part, exp.Identifier) else str(part)
        for part in getattr(column, "parts", [])
    ]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    if len(parts) == 1:
        return None, None, parts[0]
    return None, None, str(column)


def _resolve_table_for_column(
    schemaname: str | None,
    table_name: str | None,
    alias: str | None,
    table_aliases: dict[str, tuple[str, str]],
    table_name_map: dict[str, tuple[str, str]],
) -> tuple[str | None, str | None, str | None]:
    if schemaname and table_name:
        return schemaname, table_name, alias

    if table_name:
        lookup = table_aliases.get(table_name.lower()) or table_name_map.get(table_name.lower())
        if lookup:
            return lookup[0], lookup[1], table_name

    if alias:
        lookup = table_aliases.get(alias.lower())
        if lookup:
            return lookup[0], lookup[1], alias

    if len(table_name_map) == 1:
        schemaname, table_name = next(iter(table_name_map.values()))
        return schemaname, table_name, alias

    return None, None, alias


def _table_source_from_expression(node: exp.Expression) -> tuple[str, str, str | None] | None:
    if isinstance(node, exp.Table):
        schema = _normalize_identifier(node.args.get("db") or "public")
        table_name = _normalize_identifier(node.this)
        alias = _normalize_identifier(node.alias)
        if schema and table_name:
            return schema, table_name, alias
        return None

    if isinstance(node, exp.TableAlias) and isinstance(node.this, exp.Table):
        return _table_source_from_expression(node.this)

    return None


def _is_within_cte(node: exp.Expression) -> bool:
    current = node
    while current is not None:
        if isinstance(current, exp.CTE):
            return True
        current = getattr(current, "parent", None)
    return False


def _build_table_maps(expression: exp.Expression) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    table_aliases: dict[str, tuple[str, str]] = {}
    table_name_map: dict[str, tuple[str, str]] = {}
    table_seen: dict[str, tuple[str, str]] = {}

    def register_source(source: exp.Expression | None) -> None:
        if source is None:
            return
        source_info = _table_source_from_expression(source)
        if not source_info:
            return
        schema, table_name, alias = source_info
        key = (schema, table_name)
        if alias:
            table_aliases[alias.lower()] = key
        # Also allow the real table name as a lookup key.
        if table_name.lower() not in table_seen:
            table_seen[table_name.lower()] = key
            table_name_map[table_name.lower()] = key
        elif table_seen[table_name.lower()] != key:
            # Same table name from different schemas is ambiguous.
            table_name_map.pop(table_name.lower(), None)

    for from_clause in expression.find_all(exp.From):
        if _is_within_cte(from_clause):
            continue
        # sqlglot versions differ: simple FROM table may be in .this, while
        # multiple sources may be in .expressions. Handle both.
        register_source(from_clause.this)
        for source in from_clause.expressions or []:
            register_source(source)

    for join in expression.find_all(exp.Join):
        if _is_within_cte(join):
            continue
        register_source(join.this)

    return table_aliases, table_name_map

def _extract_column_expression(column: exp.Expression) -> tuple[str | None, str | None, str | None, str | None]:
    if not isinstance(column, exp.Column):
        return None, None, None, None

    schemaname, table_name, column_name = _column_parts(column)
    alias = table_name if table_name and column_name else None
    return schemaname, table_name, column_name, alias


def _collect_placeholder_uses(expression: exp.Expression, table_aliases: dict[str, tuple[str, str]], table_name_map: dict[str, tuple[str, str]]) -> tuple[list[PlaceholderUse], list[str], list[str]]:
    uses: list[PlaceholderUse] = []
    unresolved: list[str] = []
    ambiguous: list[str] = []

    def add_use(
        schemaname: str | None,
        table_name: str | None,
        alias: str | None,
        column: str,
        operator: str,
        placeholders: list[str],
        is_join: bool = False,
    ) -> None:
        resolved_schema, resolved_table, resolved_alias = _resolve_table_for_column(
            schemaname, table_name, alias, table_aliases, table_name_map
        )
        if resolved_schema is None or resolved_table is None:
            ambiguous.append(column)
            uses.append(PlaceholderUse(None, None, alias, column, operator, placeholders, is_join))
            return
        uses.append(PlaceholderUse(resolved_schema, resolved_table, resolved_alias, column, operator, placeholders, is_join))

    for node in expression.walk():
        if isinstance(node, exp.In):
            lhs = node.this
            rhs = node.args.get("expressions") or []
            placeholders = [p.sql(dialect="postgres") for p in rhs if isinstance(p, exp.Parameter)]
            if not placeholders:
                continue
            schemaname, table_name, column_name, alias = _extract_column_expression(lhs)
            if not column_name:
                continue
            add_use(schemaname, table_name, alias, column_name, "IN", placeholders)
            continue

        # sqlglot does not expose the same IS NOT NULL class in every version.
        # Avoid version-specific exp.IsNot references. We keep IS predicates as
        # optional heuristic metadata and never let them crash parsing.
        if isinstance(node, exp.Is):
            lhs = node.this
            rhs = node.expression
            if not isinstance(rhs, exp.Null):
                continue
            schemaname, table_name, column_name, alias = _extract_column_expression(lhs)
            if not column_name:
                continue
            operator = "IS NULL"
            add_use(schemaname, table_name, alias, column_name, operator, [])
            continue

        if type(node) in _SUPPORTED_COMPARISONS:
            lhs = node.left
            rhs = node.right
            lhs_is_column = isinstance(lhs, exp.Column)
            rhs_is_column = isinstance(rhs, exp.Column)
            lhs_placeholders = _placeholders_from_expression(lhs)
            rhs_placeholders = _placeholders_from_expression(rhs)
            operator = _SUPPORTED_COMPARISONS[type(node)]

            if lhs_is_column and rhs_placeholders:
                schemaname, table_name, column_name, alias = _extract_column_expression(lhs)
                if column_name:
                    add_use(schemaname, table_name, alias, column_name, operator, rhs_placeholders)
                continue

            if rhs_is_column and lhs_placeholders:
                schemaname, table_name, column_name, alias = _extract_column_expression(rhs)
                if column_name:
                    add_use(schemaname, table_name, alias, column_name, operator, lhs_placeholders)
                continue

            if lhs_is_column and rhs_is_column and operator == "=":
                lschem, ltable, lcol, la = _extract_column_expression(lhs)
                rschem, rtable, rcol, ra = _extract_column_expression(rhs)
                if lcol and rcol:
                    add_use(lschem, ltable, la, lcol, operator, [], is_join=True)
                    add_use(rschem, rtable, ra, rcol, operator, [], is_join=True)
                continue

    for use in uses:
        if use.table_name is None or use.schemaname is None:
            unresolved.append(use.column)

    return uses, unresolved, ambiguous


def _parse_with_sqlglot(sql: str) -> ParsedQuery | None:
    normalized = normalize_sql(sql)
    if not normalized.upper().startswith("SELECT"):
        return None
    try:
        expression = sqlglot.parse_one(normalized, read="postgres")
    except Exception:
        # Workload text from pg_stat_statements can contain internal PostgreSQL
        # function calls, partial prepared-statement text, or syntax sqlglot
        # cannot tokenize. Parser failures must never crash analysis.
        return None

    table_aliases, table_name_map = _build_table_maps(expression)
    placeholder_uses, unresolved, ambiguous = _collect_placeholder_uses(expression, table_aliases, table_name_map)

    first_table = None
    first_schema = None
    first_alias = None
    if len(table_name_map) == 1:
        first_schema, first_table = next(iter(table_name_map.values()))
    elif len(table_aliases) == 1:
        first_schema, first_table = next(iter(table_aliases.values()))
        first_alias = next(iter(table_aliases))

    where_clause = None
    where_expr = expression.args.get("where")
    if isinstance(where_expr, exp.Where):
        where_clause = where_expr.this.sql(dialect="postgres")

    return ParsedQuery(
        normalized_query=normalized,
        parser="sqlglot",
        schemaname=first_schema,
        table_name=first_table,
        alias=first_alias,
        where_clause=where_clause,
        table_aliases=table_aliases,
        table_name_map=table_name_map,
        placeholder_uses=placeholder_uses,
        unresolved_columns=unresolved,
        ambiguous_columns=ambiguous,
    )


def _extract_regex_placeholder_uses(where_clause: str, alias: str | None) -> list[PlaceholderUse]:
    out: list[PlaceholderUse] = []
    for m in re.finditer(
        r"(?P<lhs>(?:[a-zA-Z_][a-zA-Z0-9_]*\.)?[a-zA-Z_][a-zA-Z0-9_]*)\s*(?P<op>=|>=|<=|<>|<|>|IN|IS\s+NOT\s+NULL|IS\s+NULL)\s*(?P<rhs>\(\s*(?:\$\d+|\?)(?:\s*,\s*(?:\$\d+|\?))*\s*\)|(?:\$\d+|\?)|NULL)",
        where_clause,
        re.IGNORECASE,
    ):
        lhs = m.group("lhs")
        op = m.group("op").upper()
        rhs = m.group("rhs") or ""
        if "." in lhs:
            lhs_alias, col = lhs.split(".", 1)
            if alias and lhs_alias.lower() != alias.lower():
                continue
        else:
            col = lhs
        col = col.strip()
        if not is_safe_identifier(col):
            continue
        placeholders: list[str] = []
        if op == "IN":
            placeholders = re.findall(r"(\$\d+|\?)", rhs)
        elif "$" in rhs or "?" in rhs:
            placeholders = re.findall(r"(\$\d+|\?)", rhs)
        elif op in {"IS NOT NULL", "IS NULL"}:
            placeholders = []
        else:
            continue
        out.append(PlaceholderUse(None, None, alias, col, op, placeholders, False))
    return out


def _parse_with_regex(sql: str) -> ParsedQuery | None:
    normalized = normalize_sql(sql)
    if not normalized.upper().startswith("SELECT"):
        return None

    m_from = re.search(
        r"\bFROM\s+(?:(?P<schema>[a-zA-Z_][a-zA-Z0-9_]*)\.)?(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)(?:\s+(?:AS\s+)?(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*))?",
        normalized,
        re.IGNORECASE,
    )
    if not m_from:
        return None

    schemaname = m_from.group("schema") or "public"
    table_name = m_from.group("table")
    alias = m_from.group("alias")

    if not is_safe_identifier(schemaname) or not is_safe_identifier(table_name):
        return None
    if alias and not is_safe_identifier(alias):
        return None

    m_where = re.search(r"\bWHERE\b(?P<where>.*)$", normalized, re.IGNORECASE | re.DOTALL)
    where_clause = m_where.group("where").strip() if m_where else None
    placeholder_uses = _extract_regex_placeholder_uses(where_clause or "", alias)

    return ParsedQuery(
        normalized_query=normalized,
        parser="regex_fallback",
        schemaname=schemaname,
        table_name=table_name,
        alias=alias,
        where_clause=where_clause,
        table_aliases={alias.lower(): (schemaname, table_name)} if alias else {table_name.lower(): (schemaname, table_name)},
        table_name_map={table_name.lower(): (schemaname, table_name)},
        placeholder_uses=placeholder_uses,
        unresolved_columns=[],
        ambiguous_columns=[],
    )


def parse_select_from_where(sql: str) -> ParsedQuery | None:
    normalized = normalize_sql(sql)
    if not normalized.upper().startswith("SELECT"):
        return None

    # Skip obvious system/metadata noise before any parser touches it.
    if _STATEMENT_SKIP_RE.search(normalized) or _INTERNAL_SKIP_RE.search(normalized):
        return None

    try:
        parsed = _parse_with_sqlglot(normalized)
        # If sqlglot parsed but failed to resolve even simple table metadata, try
        # the regex parser. This is useful for pg_stat_statements-normalized SQL
        # with placeholders that sqlglot only partially understands.
        if parsed and (parsed.table_name_map or parsed.table_aliases):
            return parsed
    except Exception:
        parsed = None

    try:
        return _parse_with_regex(normalized)
    except Exception:
        return None


def extract_placeholder_uses(parsed: ParsedQuery) -> list[PlaceholderUse]:
    return parsed.placeholder_uses

