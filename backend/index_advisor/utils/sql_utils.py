from __future__ import annotations

import logging
import re

import psycopg
from psycopg.rows import dict_row


_SQL_LEADING_KEYWORD_RE = re.compile(r"^\s*(?P<kw>[a-zA-Z]+)")
_PARAM_MARKER_RE = re.compile(r"(\$\d+)|(\?)")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
logger = logging.getLogger(__name__)

_INTERNAL_SCHEMA_RE = re.compile(
    r"\b(?:pg_catalog|information_schema|pg_toast|index_advisor|pg_stat_statements|pg_stat_activity|pg_stat_user_tables|pg_stat_user_indexes|pg_indexes|pg_extension|pg_database|pg_show_all_settings|hypopg(?:_create_index|_reset)?|current_setting)\b",
    re.IGNORECASE,
)


def get_leading_keyword(sql: str) -> str:
    m = _SQL_LEADING_KEYWORD_RE.search(sql or "")
    return (m.group("kw").upper() if m else "").strip()


def is_select_query(sql: str) -> bool:
    return get_leading_keyword(sql) == "SELECT"


def is_unsafe_to_explain(sql: str) -> bool:
    kw = get_leading_keyword(sql)
    return kw in {
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "ALTER",
        "DROP",
        "TRUNCATE",
    }


def has_parameters(sql: str) -> bool:
    return bool(_PARAM_MARKER_RE.search(sql or ""))


def is_internal_query(sql: str) -> bool:
    return bool(_INTERNAL_SCHEMA_RE.search(sql or ""))


def is_safe_identifier(name: str) -> bool:
    return bool(_IDENTIFIER_RE.fullmatch(name or ""))


def _validation_context(cur) -> dict:
    cur.execute(
        """
        SELECT
            current_database() AS database_name,
            current_schema() AS schema_name,
            current_user AS current_user,
            current_setting('search_path', true) AS search_path
        """
    )
    return cur.fetchone() or {}


def _table_visibility_hint(cur, schemaname: str, table_name: str) -> dict[str, object]:
    """Return lightweight diagnostics for table/column validation logs."""
    cur.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE lower(table_name) = lower(%s)
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
        LIMIT 10;
        """,
        (table_name,),
    )
    same_name_tables = [f"{row['table_schema']}.{row['table_name']}" for row in cur.fetchall()]

    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE lower(table_schema) = lower(%s)
        ORDER BY table_name
        LIMIT 15;
        """,
        (schemaname,),
    )
    tables_in_requested_schema = [row["table_name"] for row in cur.fetchall()]

    return {
        "same_name_tables": same_name_tables,
        "tables_in_requested_schema_sample": tables_in_requested_schema,
    }


def validate_table_and_columns(
    conn: psycopg.Connection,
    schemaname: str,
    table_name: str,
    columns: list[str] | None = None,
) -> tuple[bool, list[str]]:
    if not is_safe_identifier(schemaname) or not is_safe_identifier(table_name):
        logger.info(
            "table validation failed: unsafe identifier requested_table=%s.%s requested_columns=%s",
            schemaname,
            table_name,
            columns or [],
        )
        return False, columns or []

    columns = columns or []
    if not all(is_safe_identifier(column) for column in columns):
        logger.info(
            "table validation failed: unsafe column identifier requested_table=%s.%s requested_columns=%s",
            schemaname,
            table_name,
            columns,
        )
        return False, columns

    requested = [column.lower() for column in columns]

    conn.row_factory = dict_row
    with conn.cursor() as cur:
        context = _validation_context(cur)

        cur.execute(
            """
            SELECT lower(column_name) AS column_name
            FROM information_schema.columns
            WHERE lower(table_schema) = lower(%s)
              AND lower(table_name) = lower(%s)
            ORDER BY ordinal_position;
            """,
            (schemaname, table_name),
        )
        rows = [r["column_name"] for r in cur.fetchall()]

        hint = None if rows else _table_visibility_hint(cur, schemaname, table_name)

    if not rows:
        logger.info(
            "table validation failed: table not found or no visible columns database=%s current_schema=%s current_user=%s search_path=%s requested_table=%s.%s requested_columns=%s same_name_tables=%s tables_in_requested_schema_sample=%s",
            context.get("database_name"),
            context.get("schema_name"),
            context.get("current_user"),
            context.get("search_path"),
            schemaname,
            table_name,
            columns,
            (hint or {}).get("same_name_tables"),
            (hint or {}).get("tables_in_requested_schema_sample"),
        )
        return False, columns

    existing = set(rows)
    missing = [original for original, lower_col in zip(columns, requested) if lower_col not in existing]
    if missing:
        logger.info(
            "table validation failed: missing columns database=%s current_schema=%s current_user=%s search_path=%s requested_table=%s.%s requested_columns=%s found_columns=%s missing=%s",
            context.get("database_name"),
            context.get("schema_name"),
            context.get("current_user"),
            context.get("search_path"),
            schemaname,
            table_name,
            columns,
            rows,
            missing,
        )
    return (len(missing) == 0, missing)


def strip_concurrently(create_index_sql: str) -> str:
    # HypoPG doesn't support CONCURRENTLY in hypopg_create_index().
    return re.sub(r"\bCONCURRENTLY\b", "", create_index_sql, flags=re.IGNORECASE).strip()


# ── Recommendation apply/revalidation helpers ──────────────────────────────
_DOLLAR_PARAM_RE = re.compile(r"\$(\d+)")
_QMARK_RE = re.compile(r"\?")


def is_safe_recommended_index_sql(index_sql: str) -> bool:
    """Validate that an index SQL statement is safe to execute through the API."""
    q = (index_sql or "").strip()
    q_lower = q.lower()
    if not q_lower.startswith("create index concurrently if not exists"):
        return False

    body = q[:-1] if q.endswith(";") else q
    if ";" in body:
        return False

    blocked = ["drop ", "alter ", "truncate ", "delete ", "update ", "insert ", "grant ", "revoke "]
    return not any(word in q_lower for word in blocked)


def _is_select_or_with_query(query_text: str) -> bool:
    q = (query_text or "").strip().lstrip("(").lower()
    return q.startswith("select") or q.startswith("with")


def _sql_literal(value: object, target_id: int | None = None) -> str:
    """Render a single SQL literal using psycopg's quoting against the target connection.

    Raises RuntimeError if the target connection cannot be established so that
    callers outside the HTTP request cycle receive a plain Python exception
    instead of a FastAPI HTTPException.
    """
    from psycopg import sql as psql
    from index_advisor.db import get_target_connection

    with get_target_connection(target_id) as conn:
        return psql.Literal(value).as_string(conn)


def render_query_with_bind_values(
    query_text: str,
    bind_values: dict,
    target_id: int | None = None,
) -> str:
    """Render a SELECT/WITH query by safely replacing supported bind markers.

    Supports PostgreSQL-style ``$1`` markers and positional ``?1``/``?`` markers
    used by the recommendation revalidation flow.

    Raises ``ValueError`` on invalid input (missing query, non-SELECT statement,
    missing bind values).  Callers in the service/API layer should translate
    ``ValueError`` into the appropriate HTTP 400 response.
    """
    q = (query_text or "").strip().rstrip(";")
    if not q:
        raise ValueError("Recommendation has no query text to validate")

    if not _is_select_or_with_query(q):
        raise ValueError("Only SELECT/WITH queries can be revalidated")

    dollar_keys: list[int] = []
    for key in bind_values:
        if str(key).startswith("$") and str(key)[1:].isdigit():
            dollar_keys.append(int(str(key)[1:]))

    for n in sorted(dollar_keys, reverse=True):
        key = f"${n}"
        q = re.sub(rf"\${n}\b", _sql_literal(bind_values[key], target_id), q)

    qmark_count = len(_QMARK_RE.findall(q))
    if qmark_count:
        qmark_values: list = []
        for i in range(1, qmark_count + 1):
            key = f"?{i}"
            if key not in bind_values:
                raise ValueError(f"Missing bind value for {key}")
            qmark_values.append(bind_values[key])

        parts = _QMARK_RE.split(q)
        out = parts[0]
        for seg, val in zip(parts[1:], qmark_values, strict=True):
            out += _sql_literal(val, target_id) + seg
        q = out

    unresolved = _DOLLAR_PARAM_RE.findall(q)
    if unresolved or _QMARK_RE.search(q):
        raise ValueError("Missing one or more bind values")

    return q
