from __future__ import annotations

import logging
from pathlib import Path

from index_advisor.db import ensure_storage_database_exists, get_storage_connection

logger = logging.getLogger(__name__)

SCHEMA = "index_advisor"


def _connect_autocommit():
    """Open a storage connection in autocommit mode before any statement runs.

    The previous implementation changed autocommit after SELECT statements had
    already opened a transaction, which caused psycopg to raise:
    "can't change 'autocommit' now: connection in transaction status INTRANS".
    """
    conn = get_storage_connection()
    conn.autocommit = True
    return conn


def _ensure_migrations_table() -> None:
    """Bootstrap the schema_migrations tracking table before migrations run."""
    with _connect_autocommit() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE SCHEMA IF NOT EXISTS {SCHEMA};
                CREATE TABLE IF NOT EXISTS {SCHEMA}.schema_migrations (
                    version    text        PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                );
                """
            )


def _applied_versions() -> set[str]:
    with _connect_autocommit() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT version FROM {SCHEMA}.schema_migrations;")
            return {row["version"] for row in cur.fetchall()}


def _mark_applied(version: str) -> None:
    with _connect_autocommit() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.schema_migrations (version)
                VALUES (%s)
                ON CONFLICT (version) DO NOTHING;
                """,
                (version,),
            )


def _run_migration_file(sql_path: Path) -> None:
    sql_text = sql_path.read_text(encoding="utf-8")
    with _connect_autocommit() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)


def apply_storage_migrations() -> None:
    """Create the storage database if needed and apply pending SQL migrations.

    Migration files are tracked in index_advisor.schema_migrations and skipped
    once applied. Each operation uses a fresh autocommit connection so there is
    no autocommit toggle while a transaction is already open.
    """
    ensure_storage_database_exists()
    _ensure_migrations_table()

    storage_dir = Path(__file__).parent
    migration_files = sorted(storage_dir.glob("*.sql"))

    if not migration_files:
        raise RuntimeError(f"No migration files found under: {storage_dir}")

    applied = _applied_versions()
    for migration_path in migration_files:
        version = migration_path.stem
        if version in applied:
            logger.debug("Skipping already-applied migration: %s", migration_path.name)
            continue

        logger.info("Applying migration: %s", migration_path.name)
        _run_migration_file(migration_path)
        _mark_applied(version)
        logger.info("Migration applied: %s", migration_path.name)

    logger.info("Storage migrations up to date.")
