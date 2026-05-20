from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from index_advisor.storage.repositories.common import SCHEMA, fetch_all, fetch_one

_RUN_COLUMNS = "id, target_id, started_at, completed_at, status, error_message"
_ALLOWED_COUNT_TABLES = {"recommendations", "query_stats", "table_stats", "index_stats", "query_plans"}


def list_runs(conn: psycopg.Connection, *, limit: int, offset: int, status: str | None = None, target_id: int | None = None) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[object] = []

    if status:
        conditions.append("status = %s")
        params.append(status.upper())

    if target_id is not None:
        conditions.append("target_id = %s")
        params.append(target_id)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.extend([limit, offset])
    return fetch_all(
        conn,
        f"""
        SELECT {_RUN_COLUMNS}
        FROM {SCHEMA}.collection_runs
        {where}
        ORDER BY started_at DESC
        LIMIT %s OFFSET %s;
        """,
        tuple(params),
    )


def get_latest_run(conn: psycopg.Connection, *, completed_only: bool, target_id: int | None = None) -> dict[str, Any] | None:
    conditions: list[str] = []
    params: list[object] = []
    if completed_only:
        conditions.append("status = 'COMPLETED'")
    if target_id is not None:
        conditions.append("target_id = %s")
        params.append(target_id)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    order = "completed_at DESC NULLS LAST, started_at DESC" if completed_only else "started_at DESC"
    return fetch_one(
        conn,
        f"""
        SELECT {_RUN_COLUMNS}
        FROM {SCHEMA}.collection_runs
        {where}
        ORDER BY {order}
        LIMIT 1;
        """,
        tuple(params),
    )


def get_run(conn: psycopg.Connection, run_id: UUID) -> dict[str, Any] | None:
    return fetch_one(conn, f"SELECT {_RUN_COLUMNS} FROM {SCHEMA}.collection_runs WHERE id = %s;", (run_id,))


def count_for_run(conn: psycopg.Connection, table: str, run_id: UUID) -> int:
    if table not in _ALLOWED_COUNT_TABLES:
        raise ValueError(f"Unsupported table for count: {table}")
    row = fetch_one(conn, f"SELECT COUNT(*) AS count FROM {SCHEMA}.{table} WHERE collection_run_id = %s;", (run_id,))
    return int(row["count"] if row else 0)


def counts_for_run(conn: psycopg.Connection, run_id: UUID) -> dict[str, int]:
    return {table: count_for_run(conn, table, run_id) for table in sorted(_ALLOWED_COUNT_TABLES)}
