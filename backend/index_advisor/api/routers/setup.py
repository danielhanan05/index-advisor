"""Setup and health endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from index_advisor.api.errors import api_error, storage_bootstrap_error_detail
from index_advisor.api.scheduler import scheduler_status
from index_advisor.api.schemas import DatabaseTargetRequest
from index_advisor.api.security import require_admin_token
from index_advisor.db import get_storage_connection, has_storage_config
from index_advisor.services.setup_service import get_setup_status
from index_advisor.storage.repositories.common import fetch_one
from index_advisor.storage.retention import apply_storage_retention
from index_advisor.storage.settings import get_product_settings
from index_advisor.targets.registry import get_adapter, is_engine_supported, list_supported_engines
from index_advisor.utils.connection_utils import target_conninfo_from_request_body
from index_advisor.config import load_config

router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    if not has_storage_config():
        cfg = load_config()
        return {
            "status": "setup_required",
            "storage_db": False,
            "storage_configured": False,
            "storage_database_name": cfg.storage_database_name,
            "storage_source": "frontend_setup_required",
        }

    try:
        with get_storage_connection() as conn:
            row = fetch_one(conn, "SELECT 1 AS ok;")
        return {"status": "ok", "storage_db": bool(row and row["ok"] == 1), "storage_configured": True}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=storage_bootstrap_error_detail(exc)) from exc


@router.get("/scheduler/status")
def get_scheduler_status() -> dict[str, object]:
    return scheduler_status()


@router.get("/engines")
def list_database_engines() -> dict[str, object]:
    return {"items": list_supported_engines()}


@router.get("/setup/status")
def setup_status() -> dict[str, object]:
    return get_setup_status()


@router.post("/setup/test-target-connection", dependencies=[Depends(require_admin_token)])
def test_target_connection(body: DatabaseTargetRequest) -> dict[str, object]:
    if not is_engine_supported(body.engine):
        raise api_error(
            400,
            title="Database engine not available yet",
            message="PostgreSQL is the only supported engine in this version. MSSQL and Oracle are shown as roadmap options.",
            error_type="ENGINE_NOT_SUPPORTED",
            details=f"Selected engine: {body.engine}",
            action_items=["Choose PostgreSQL for now."],
        )

    conninfo = target_conninfo_from_request_body(body)
    result = get_adapter(body.engine).test_connection(conninfo)
    return {"ok": result.ok, "version": result.version, "error": result.error, "error_detail": result.error_detail}


@router.get("/setup/retention/status")
def retention_status() -> dict[str, object]:
    if not has_storage_config():
        return {
            "enabled": True,
            "retention_days": get_product_settings().storage_retention_days,
            "configured": False,
            "message": "Retention will start after storage is configured.",
        }
    return {"configured": True, **apply_storage_retention(force=False).as_dict()}


@router.post("/setup/retention/run", dependencies=[Depends(require_admin_token)])
def run_retention_now() -> dict[str, object]:
    if not has_storage_config():
        raise HTTPException(status_code=400, detail="Storage is not configured yet; retention cannot run.")
    return apply_storage_retention(force=True).as_dict()
