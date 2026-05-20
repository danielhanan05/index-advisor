from __future__ import annotations

import logging
from urllib.parse import urlparse, unquote

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from index_advisor.config import load_config, set_runtime_storage_database_url
from index_advisor.security.credentials import decrypt_secret

logger = logging.getLogger(__name__)
SCHEMA = "index_advisor"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 15


def connection_timeout_seconds() -> int:
    """Return the PostgreSQL connection timeout used by all backend DB connects."""
    try:
        value = int(load_config().database_connect_timeout_seconds)
    except Exception:
        return DEFAULT_CONNECT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_CONNECT_TIMEOUT_SECONDS


def with_connection_timeout(conninfo: str) -> str:
    """Ensure every psycopg conninfo includes a finite connect_timeout.

    This prevents setup/test/analyze requests from hanging for a long time when
    PostgreSQL is down, firewalled, or the host/port is unreachable. Existing
    user-supplied conninfo values keep their SSL/user/password settings; only
    connect_timeout is added/overridden consistently.
    """
    return make_conninfo(conninfo, connect_timeout=connection_timeout_seconds())


def connect_with_timeout(conninfo: str, **kwargs) -> psycopg.Connection:
    """Open a psycopg connection with the project-wide connection timeout."""
    return psycopg.connect(with_connection_timeout(conninfo), **kwargs)


def _conninfo_dict(conninfo: str) -> dict[str, str]:
    """Parse psycopg conninfo into a dict. Supports URL and keyword DSNs."""
    try:
        d = conninfo_to_dict(conninfo)
        return {k: str(v) for k, v in d.items() if v is not None}
    except Exception:
        parsed = urlparse(conninfo)
        if not parsed.scheme.startswith("postgres"):
            raise
        out: dict[str, str] = {}
        if parsed.username:
            out["user"] = unquote(parsed.username)
        if parsed.password:
            out["password"] = unquote(parsed.password)
        if parsed.hostname:
            out["host"] = parsed.hostname
        if parsed.port:
            out["port"] = str(parsed.port)
        if parsed.path and parsed.path != "/":
            out["dbname"] = parsed.path.lstrip("/")
        return out


def _target_row_to_conninfo(row: dict) -> str:
    parts = {
        "host": row["host"],
        "port": int(row.get("port") or 5432),
        "dbname": row["database_name"],
        "user": row["username"],
        "sslmode": row.get("sslmode") or "prefer",
        "connect_timeout": connection_timeout_seconds(),
    }
    if row.get("password"):
        parts["password"] = decrypt_secret(row["password"])
    return make_conninfo(**parts)


def target_conninfo_from_details(
    *,
    host: str,
    port: int,
    database_name: str,
    username: str,
    password: str | None = None,
    sslmode: str = "prefer",
) -> str:
    parts: dict[str, object] = {
        "host": host,
        "port": int(port),
        "dbname": database_name,
        "user": username,
        "sslmode": sslmode or "prefer",
        "connect_timeout": connection_timeout_seconds(),
    }
    if password:
        parts["password"] = password
    return make_conninfo(**parts)


def load_storage_conninfo() -> str:
    cfg = load_config()
    if not cfg.storage_database_url:
        raise RuntimeError(
            "Storage database is not configured yet. Complete the first-time setup wizard; "
            "the app will create storage_db on the same PostgreSQL host as your target database."
        )
    return cfg.storage_database_url


def has_storage_config() -> bool:
    return bool(load_config().storage_database_url)


def get_storage_connection() -> psycopg.Connection:
    conn = connect_with_timeout(load_storage_conninfo(), row_factory=dict_row)
    conn.autocommit = False
    return conn


def get_target_row(target_id: int | None = None) -> dict | None:
    """Return a configured target row with encrypted password included.

    Kept in db.py for backward compatibility with existing collector/analyzer
    callers, but the actual SQL now lives in the target repository layer.
    """
    try:
        from index_advisor.storage.repositories import targets as target_repo

        with get_storage_connection() as conn:
            if target_id is not None:
                return target_repo.get_target(conn, target_id, include_password=True)

            default_id = target_repo.get_default_target_id(conn)
            if default_id is None:
                return None
            return target_repo.get_target(conn, default_id, include_password=True)
    except Exception:
        return None


def get_target_connection(target_id: int | None = None) -> psycopg.Connection:
    row = get_target_row(target_id)
    if row:
        conninfo = _target_row_to_conninfo(row)
    else:
        cfg = load_config()
        if not cfg.target_database_url:
            raise RuntimeError(
                "No database target is configured yet. Add a database target in the setup wizard "
                "or set TARGET_DATABASE_URL for development mode."
            )
        conninfo = cfg.target_database_url

    conn = connect_with_timeout(conninfo, row_factory=dict_row)
    conn.autocommit = False
    return conn


def storage_conninfo_from_target_details(
    *,
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    sslmode: str = "prefer",
    storage_database_name: str | None = None,
) -> str:
    cfg = load_config()
    parts: dict[str, object] = {
        "host": host,
        "port": int(port),
        "dbname": storage_database_name or cfg.storage_database_name,
        "user": username,
        "sslmode": sslmode or "prefer",
        "connect_timeout": connection_timeout_seconds(),
    }
    if password:
        parts["password"] = password
    return make_conninfo(**parts)


def _ensure_database_exists_for_conninfo(conninfo: str, maintenance_db: str) -> None:
    info = _conninfo_dict(conninfo)
    dbname = info.get("dbname")
    if not dbname:
        raise RuntimeError("Storage connection info must include a database name (dbname).")

    info_maint = dict(info)
    info_maint["dbname"] = maintenance_db
    maint_conninfo = make_conninfo(**info_maint)

    try:
        with connect_with_timeout(maint_conninfo, row_factory=dict_row, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (dbname,))
                exists = cur.fetchone() is not None
                if exists:
                    logger.info("Storage database exists: %s", dbname)
                    return

                logger.info("Creating storage database: %s", dbname)
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
                logger.info("Created storage database: %s", dbname)

    except psycopg.errors.InvalidCatalogName as exc:
        raise RuntimeError(
            f"Could not connect to maintenance database '{maintenance_db}'. Usually this should be 'postgres'."
        ) from exc


def ensure_storage_database_exists(maintenance_db: str | None = None) -> None:
    """Ensure the configured storage database exists.

    On end-user machines the storage DB is usually configured by the first-time
    setup wizard rather than by STORAGE_DATABASE_URL.
    """
    cfg = load_config()
    conninfo = load_storage_conninfo()
    _ensure_database_exists_for_conninfo(conninfo, maintenance_db or cfg.storage_maintenance_db)


def bootstrap_storage_from_target_details(
    *,
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    sslmode: str = "prefer",
) -> str:
    """Create/configure storage_db on the same server as the target DB.

    This is used by first-time setup when STORAGE_DATABASE_URL is not set. It
    creates storage_db and sets the resulting conninfo in memory. The API layer
    persists it to the local user config directory after migrations and target
    creation succeed.
    """
    cfg = load_config()
    conninfo = storage_conninfo_from_target_details(
        host=host,
        port=port,
        username=username,
        password=password,
        sslmode=sslmode,
        storage_database_name=cfg.storage_database_name,
    )
    _ensure_database_exists_for_conninfo(conninfo, cfg.storage_maintenance_db)
    set_runtime_storage_database_url(conninfo)
    logger.info(
        "Storage database configured for current process on host=%s port=%s dbname=%s",
        host,
        port,
        cfg.storage_database_name,
    )
    return conninfo


def test_connections(target_id: int | None = None) -> None:
    with get_target_connection(target_id) as tconn:
        with tconn.cursor() as cur:
            cur.execute("SELECT 1 AS ok;")
            _ = cur.fetchone()
        tconn.rollback()

    with get_storage_connection() as sconn:
        with sconn.cursor() as cur:
            cur.execute("SELECT 1 AS ok;")
            _ = cur.fetchone()
        sconn.rollback()

    logger.info("Connections to TARGET and STORAGE databases succeeded.")


def extension_status_for_conninfo(conninfo: str, *, attempt_create: bool = False, require_hypopg: bool = True) -> dict[str, object]:
    required = ["pg_stat_statements"] + (["hypopg"] if require_hypopg else [])
    result: dict[str, object] = {
        "pg_stat_statements": False,
        "hypopg": False,
        "pg_stat_statements_usable": False,
        "errors": [],
        "guide": extension_fix_guide(),
    }

    def refresh_present(conn: psycopg.Connection) -> set[str]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extname FROM pg_extension WHERE extname = ANY(%s);",
                (["pg_stat_statements", "hypopg"],),
            )
            return {row["extname"] for row in cur.fetchall()}

    try:
        with connect_with_timeout(conninfo, row_factory=dict_row, autocommit=True) as conn:
            present = refresh_present(conn)
            if attempt_create:
                with conn.cursor() as cur:
                    for ext in ["pg_stat_statements", "hypopg"]:
                        if ext not in present:
                            try:
                                cur.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(ext)))
                            except Exception as exc:
                                result["errors"].append(f"Could not create {ext}: {exc}")
                present = refresh_present(conn)

            result["pg_stat_statements"] = "pg_stat_statements" in present
            result["hypopg"] = "hypopg" in present

            if "pg_stat_statements" in present:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM pg_stat_statements LIMIT 1;")
                        _ = cur.fetchone()
                    result["pg_stat_statements_usable"] = True
                except Exception as exc:
                    result["errors"].append(
                        "pg_stat_statements exists but is not usable. It probably needs shared_preload_libraries and a PostgreSQL restart: "
                        + str(exc)
                    )

    except Exception as exc:
        result["errors"].append(f"Could not connect/check extensions: {exc}")

    missing = [ext for ext in required if not result.get(ext)]
    if "pg_stat_statements" in required and not result.get("pg_stat_statements_usable"):
        if "pg_stat_statements" not in missing:
            missing.append("pg_stat_statements usable preload")
    result["ok"] = not missing and not result["errors"]
    result["missing"] = missing
    return result


def extension_fix_guide() -> dict[str, str]:
    return {
        "pg_stat_statements": (
            "pg_stat_statements usually requires shared_preload_libraries. Run as a PostgreSQL admin: "
            "ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements'; then restart PostgreSQL. "
            "After restart, connect to the monitored database and run: CREATE EXTENSION IF NOT EXISTS pg_stat_statements; "
            "The restart can cause downtime unless your PostgreSQL HA setup hides it."
        ),
        "hypopg": (
            "HypoPG must be installed on the PostgreSQL server OS/package first. Then connect to the monitored database "
            "and run: CREATE EXTENSION IF NOT EXISTS hypopg; Without HypoPG the advisor cannot validate hypothetical indexes."
        ),
    }


def check_required_extensions(*, require_hypopg: bool = True, target_id: int | None = None) -> None:
    row = get_target_row(target_id)
    if row:
        conninfo = _target_row_to_conninfo(row)
    else:
        cfg = load_config()
        if not cfg.target_database_url:
            raise RuntimeError("No target database configured.")
        conninfo = cfg.target_database_url

    status = extension_status_for_conninfo(conninfo, attempt_create=True, require_hypopg=require_hypopg)
    if not status.get("ok"):
        errors = status.get("errors") or []
        missing = status.get("missing") or []
        guide = extension_fix_guide()
        raise RuntimeError(
            "Target database extension check failed.\n"
            f"Missing/failed: {missing}\n"
            f"Errors: {errors}\n\n"
            "Fix guide:\n"
            f"pg_stat_statements: {guide['pg_stat_statements']}\n"
            f"hypopg: {guide['hypopg']}"
        )

    logger.info("Required extensions are present on target database.")
