from __future__ import annotations

from typing import Any

import psycopg

from index_advisor.security.credentials import encrypt_secret
from index_advisor.storage.repositories.common import SCHEMA, fetch_all, fetch_one

SAFE_TARGET_COLUMNS = """
    id, engine, name, host, port, database_name, username, sslmode, is_active, is_default,
    setup_status, pg_stat_statements_ok, hypopg_ok, last_connection_check_at,
    last_connection_error, last_extension_check_at, last_extension_error, created_at, updated_at
"""

CONNECTION_FIELDS = {"engine", "host", "port", "database_name", "username", "password", "sslmode"}
_ALLOWED_UPDATE_COLUMNS = CONNECTION_FIELDS | {"name", "is_active", "is_default"}
_UPDATE_COLUMN_SQL = {
    "engine": "engine = %s",
    "name": "name = %s",
    "host": "host = %s",
    "port": "port = %s",
    "database_name": "database_name = %s",
    "username": "username = %s",
    "password": "password = %s",
    "sslmode": "sslmode = %s",
    "is_active": "is_active = %s",
    "is_default": "is_default = %s",
}


def list_targets(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return fetch_all(conn, f"SELECT {SAFE_TARGET_COLUMNS} FROM {SCHEMA}.database_targets ORDER BY is_default DESC, id ASC;")


def get_target(conn: psycopg.Connection, target_id: int, *, include_password: bool = False) -> dict[str, Any] | None:
    columns = "*" if include_password else SAFE_TARGET_COLUMNS
    return fetch_one(conn, f"SELECT {columns} FROM {SCHEMA}.database_targets WHERE id = %s;", (target_id,))


def get_default_target_id(conn: psycopg.Connection) -> int | None:
    row = fetch_one(
        conn,
        f"""
        SELECT id
        FROM {SCHEMA}.database_targets
        WHERE is_active = true
        ORDER BY is_default DESC, id ASC
        LIMIT 1;
        """,
    )
    return int(row["id"]) if row else None


def setup_complete(conn: psycopg.Connection) -> bool:
    row = fetch_one(conn, f"SELECT COUNT(*) AS count FROM {SCHEMA}.database_targets WHERE is_active = true;")
    return bool(row and int(row["count"]) > 0)


def set_setup_complete(conn: psycopg.Connection, complete: bool) -> None:
    import json

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.app_settings(key, value, updated_at)
            VALUES ('setup_complete', %s::jsonb, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
            """,
            (json.dumps({"complete": bool(complete)}),),
        )


def upsert_target(
    conn: psycopg.Connection,
    *,
    engine: str,
    name: str,
    host: str,
    port: int,
    database_name: str,
    username: str,
    password: str | None,
    sslmode: str,
    is_default: bool,
    setup_status: str,
    connection_error: str | None,
    extension_error: str | None,
    pg_stat_statements_ok: bool,
    hypopg_ok: bool,
) -> tuple[int, bool]:
    if is_default:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {SCHEMA}.database_targets SET is_default = false;")

    encrypted_password = encrypt_secret(password)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.database_targets
                (engine, name, host, port, database_name, username, password, sslmode, is_default, is_active,
                 setup_status, last_connection_check_at, last_connection_error,
                 last_extension_check_at, last_extension_error, pg_stat_statements_ok, hypopg_ok)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true,
                    %s, now(), %s, now(), %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                engine = EXCLUDED.engine,
                host = EXCLUDED.host,
                port = EXCLUDED.port,
                database_name = EXCLUDED.database_name,
                username = EXCLUDED.username,
                password = EXCLUDED.password,
                sslmode = EXCLUDED.sslmode,
                is_active = true,
                is_default = EXCLUDED.is_default,
                setup_status = EXCLUDED.setup_status,
                last_connection_check_at = EXCLUDED.last_connection_check_at,
                last_connection_error = EXCLUDED.last_connection_error,
                last_extension_check_at = EXCLUDED.last_extension_check_at,
                last_extension_error = EXCLUDED.last_extension_error,
                pg_stat_statements_ok = EXCLUDED.pg_stat_statements_ok,
                hypopg_ok = EXCLUDED.hypopg_ok,
                updated_at = now()
            RETURNING id, (xmax <> 0) AS target_existed;
            """,
            (
                engine,
                name,
                host,
                port,
                database_name,
                username,
                encrypted_password,
                sslmode,
                is_default,
                setup_status,
                connection_error,
                extension_error,
                pg_stat_statements_ok,
                hypopg_ok,
            ),
        )
        row = cur.fetchone()
        target_id = int(row["id"])
        target_existed = bool(row.get("target_existed"))

        cur.execute(f"SELECT COUNT(*) AS count FROM {SCHEMA}.database_targets WHERE is_active = true;")
        count = int(cur.fetchone()["count"])
        if count == 1:
            cur.execute(f"UPDATE {SCHEMA}.database_targets SET is_default = true WHERE id = %s;", (target_id,))

    set_setup_complete(conn, True)
    return target_id, target_existed


def update_target(conn: psycopg.Connection, target_id: int, data: dict[str, Any]) -> str:
    updates = {k: v for k, v in data.items() if k in _ALLOWED_UPDATE_COLUMNS}
    if not updates:
        return "unchanged"

    if updates.get("is_default") is True:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {SCHEMA}.database_targets SET is_default = false;")

    connection_changed = any(k in CONNECTION_FIELDS for k in updates)
    if "password" in updates:
        updates["password"] = encrypt_secret(updates["password"])

    # Use fixed SQL fragments from an allowlist rather than interpolating
    # request-provided keys into SQL. The values are still parameterized.
    set_parts = [_UPDATE_COLUMN_SQL[column] for column in updates]
    params = list(updates.values())

    if connection_changed:
        set_parts.extend(
            [
                "setup_status = 'NEEDS_ATTENTION'",
                "last_connection_error = NULL",
                "last_extension_error = NULL",
                "pg_stat_statements_ok = false",
                "hypopg_ok = false",
            ]
        )

    params.append(target_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {SCHEMA}.database_targets SET {', '.join(set_parts)}, updated_at = now() WHERE id = %s;",
            tuple(params),
        )

    set_setup_complete(conn, setup_complete(conn))
    return "updated_needs_recheck" if connection_changed else "updated"


def disable_target(conn: psycopg.Connection, target_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.database_targets
            SET is_active = false,
                is_default = false,
                updated_at = now()
            WHERE id = %s;
            """,
            (target_id,),
        )
    set_setup_complete(conn, setup_complete(conn))


def update_connection_check(conn: psycopg.Connection, target_id: int, error: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.database_targets
            SET last_connection_check_at = now(),
                last_connection_error = %s,
                updated_at = now()
            WHERE id = %s;
            """,
            (error, target_id),
        )


def update_extension_check(conn: psycopg.Connection, target_id: int, *, setup_status: str, status: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.database_targets
            SET setup_status = %s,
                last_extension_check_at = now(),
                last_extension_error = %s,
                pg_stat_statements_ok = %s,
                hypopg_ok = %s,
                updated_at = now()
            WHERE id = %s;
            """,
            (
                setup_status,
                "\n".join(status.get("errors", [])) if status.get("errors") else None,
                bool(status.get("pg_stat_statements_usable")),
                bool(status.get("hypopg")),
                target_id,
            ),
        )
