from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

SCHEMA = "index_advisor"


def fetch_all(conn: psycopg.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def fetch_one(conn: psycopg.Connection, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()
