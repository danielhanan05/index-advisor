from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


logger = logging.getLogger(__name__)


def sample_non_null_value(
    conn: psycopg.Connection, *, schemaname: str, table_name: str, column: str
) -> Any | None:
    """
    Sample a realistic value using ORDER BY random() LIMIT 1.
    Returns Python value (psycopg decodes to int/str/datetime/etc).
    """
    conn.row_factory = dict_row
    stmt = sql.SQL(
        "SELECT {col} AS v FROM {schema}.{table} WHERE {col} IS NOT NULL ORDER BY random() LIMIT 1"
    ).format(
        col=sql.Identifier(column),
        schema=sql.Identifier(schemaname),
        table=sql.Identifier(table_name),
    )
    with conn.cursor() as cur:
        cur.execute(stmt)
        row = cur.fetchone()
        return (row["v"] if row else None)


def sample_n_non_null_values(
    conn: psycopg.Connection, *, schemaname: str, table_name: str, column: str, n: int
) -> list[Any]:
    if n <= 0:
        return []
    conn.row_factory = dict_row
    stmt = sql.SQL(
        "SELECT {col} AS v FROM {schema}.{table} WHERE {col} IS NOT NULL ORDER BY random() LIMIT {n}"
    ).format(
        col=sql.Identifier(column),
        schema=sql.Identifier(schemaname),
        table=sql.Identifier(table_name),
        n=sql.Literal(int(n)),
    )
    with conn.cursor() as cur:
        cur.execute(stmt)
        return [r["v"] for r in cur.fetchall()]



def sample_row_non_null_values(
    conn: psycopg.Connection, *, schemaname: str, table_name: str, columns: list[str]
) -> dict[str, Any] | None:
    """
    Sample one real row containing non-null values for all requested columns.

    This is important for multi-column predicates: it preserves real combinations
    such as (country, city) instead of sampling each column independently and
    accidentally creating impossible bind combinations.
    """
    if not columns:
        return {}

    conn.row_factory = dict_row
    select_list = sql.SQL(", ").join(
        sql.SQL("{col} AS {alias}").format(
            col=sql.Identifier(column),
            alias=sql.Identifier(column),
        )
        for column in columns
    )
    where_clause = sql.SQL(" AND ").join(
        sql.SQL("{col} IS NOT NULL").format(col=sql.Identifier(column))
        for column in columns
    )
    stmt = sql.SQL(
        "SELECT {select_list} FROM {schema}.{table} WHERE {where_clause} ORDER BY random() LIMIT 1"
    ).format(
        select_list=select_list,
        schema=sql.Identifier(schemaname),
        table=sql.Identifier(table_name),
        where_clause=where_clause,
    )
    with conn.cursor() as cur:
        cur.execute(stmt)
        row = cur.fetchone()
        if not row:
            return None
        return {column: row[column] for column in columns}
