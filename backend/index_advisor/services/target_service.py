from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from index_advisor.utils.connection_utils import target_conninfo_from_request_body
from index_advisor.api.errors import storage_bootstrap_error_detail
from index_advisor.api.errors import api_error
from index_advisor.api.serializers import row_to_dict, rows_to_list
from index_advisor.config import save_local_storage_database_url
from index_advisor.db import bootstrap_storage_from_target_details, get_storage_connection, has_storage_config
from index_advisor.storage.migrations import apply_storage_migrations
from index_advisor.storage.retention import apply_storage_retention
from index_advisor.storage.repositories import targets as target_repo
from index_advisor.targets.registry import get_adapter, is_engine_supported


def _unsupported_engine(engine: str) -> HTTPException:
    return api_error(
        400,
        title="Database engine not available yet",
        message="PostgreSQL is the only supported engine in this version. MSSQL and Oracle are shown as roadmap options.",
        details=f"Selected engine: {engine}",
        action_items=["Choose PostgreSQL for now."],
        error_type="ENGINE_NOT_SUPPORTED",
    )


def list_targets() -> dict[str, object]:
    with get_storage_connection() as conn:
        rows = target_repo.list_targets(conn)
    return {"items": rows_to_list(rows)}


def get_target_or_404(target_id: int, *, include_password: bool = False) -> dict[str, Any]:
    with get_storage_connection() as conn:
        row = target_repo.get_target(conn, target_id, include_password=include_password)
    if not row:
        raise api_error(404, title="Target not found", message="Database target not found.", error_type="TARGET_NOT_FOUND")
    return row


def create_target(body: Any) -> dict[str, object]:
    if not is_engine_supported(body.engine):
        raise _unsupported_engine(body.engine)

    conninfo = target_conninfo_from_request_body(body)
    adapter = get_adapter(body.engine)

    connection_result = adapter.test_connection(conninfo)
    connection_error = connection_result.error
    connection_error_detail = connection_result.error_detail

    requirement_result = adapter.check_requirements(conninfo, attempt_create=True) if connection_result.ok else None
    ext_status: dict[str, object] = requirement_result.details if requirement_result else {"ok": False, "errors": [connection_error or "Connection failed"]}
    status = requirement_result.setup_status if requirement_result else "NEEDS_ATTENTION"

    storage_bootstrapped = False
    bootstrapped_storage_conninfo: str | None = None
    try:
        if not has_storage_config():
            bootstrapped_storage_conninfo = bootstrap_storage_from_target_details(
                host=body.host,
                port=int(body.port or 5432),
                username=body.username,
                password=body.password,
                sslmode=body.sslmode or "prefer",
            )
            storage_bootstrapped = True

        apply_storage_migrations()
        apply_storage_retention(force=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=storage_bootstrap_error_detail(exc)) from exc

    with get_storage_connection() as conn:
        new_id, target_existed = target_repo.upsert_target(
            conn,
            engine=body.engine,
            name=body.name,
            host=body.host,
            port=int(body.port or 5432),
            database_name=body.database_name,
            username=body.username,
            password=body.password,
            sslmode=body.sslmode or "prefer",
            is_default=body.is_default,
            setup_status=status,
            connection_error=connection_error,
            extension_error="\n".join(ext_status.get("errors", [])) if ext_status.get("errors") else None,
            pg_stat_statements_ok=bool(ext_status.get("pg_stat_statements_usable")),
            hypopg_ok=bool(ext_status.get("hypopg")),
        )
        conn.commit()

    if bootstrapped_storage_conninfo:
        save_local_storage_database_url(bootstrapped_storage_conninfo)

    return {
        "id": new_id,
        "setup_status": status,
        "extension_status": ext_status,
        "connection_error": connection_error,
        "connection_error_detail": connection_error_detail,
        "storage_bootstrapped": storage_bootstrapped,
        "target_existed": target_existed,
    }


def get_target(target_id: int) -> dict[str, object]:
    row = get_target_or_404(target_id)
    return row_to_dict(row) or {}


def update_target(target_id: int, body: Any) -> dict[str, object]:
    get_target_or_404(target_id, include_password=True)
    data = body.model_dump(exclude_unset=True)
    if not data:
        return {"status": "unchanged", "id": target_id}

    with get_storage_connection() as conn:
        status = target_repo.update_target(conn, target_id, data)
        conn.commit()

    return {"status": status, "id": target_id}


def delete_target(target_id: int) -> dict[str, object]:
    get_target_or_404(target_id, include_password=True)
    with get_storage_connection() as conn:
        target_repo.disable_target(conn, target_id)
        conn.commit()
    return {"status": "disabled", "id": target_id}


def test_existing_target_connection(target_id: int) -> dict[str, object]:
    row = get_target_or_404(target_id, include_password=True)
    conninfo = target_conninfo_from_request_body(dict(row))
    result = get_adapter(row.get("engine", "postgres")).test_connection(conninfo)

    with get_storage_connection() as conn:
        target_repo.update_connection_check(conn, target_id, result.error)
        conn.commit()

    return {"ok": result.ok, "version": result.version, "error": result.error, "error_detail": result.error_detail}


def check_existing_target_extensions(target_id: int, *, attempt_create: bool = True) -> dict[str, object]:
    row = get_target_or_404(target_id, include_password=True)
    conninfo = target_conninfo_from_request_body(dict(row))

    requirement = get_adapter(row.get("engine", "postgres")).check_requirements(conninfo, attempt_create=attempt_create)
    status = requirement.details
    setup_status = requirement.setup_status

    with get_storage_connection() as conn:
        target_repo.update_extension_check(conn, target_id, setup_status=setup_status, status=status)
        conn.commit()

    return {"target_id": target_id, "setup_status": setup_status, "extension_status": status}

