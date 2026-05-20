"""Product settings endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from index_advisor.api.errors import storage_bootstrap_error_detail
from index_advisor.api.schemas import ProductSettingsUpdateRequest
from index_advisor.api.security import require_admin_token
from index_advisor.api.scheduler import scheduler_status
from index_advisor.storage.retention import apply_storage_retention
from index_advisor.storage.settings import get_product_settings, update_product_settings

router = APIRouter()


@router.get("/settings")
def get_settings() -> dict[str, object]:
    settings = get_product_settings().as_dict()
    settings["scheduler"] = scheduler_status()
    return settings


@router.put("/settings", dependencies=[Depends(require_admin_token)])
def update_settings(body: ProductSettingsUpdateRequest) -> dict[str, object]:
    try:
        settings = update_product_settings(
            scheduler_enabled=body.scheduler_enabled,
            scheduler_run_times=body.scheduler_run_times,
            storage_retention_days=body.storage_retention_days,
        )

        # If retention days were lowered, clean immediately so the setting is
        # effective right away instead of waiting for the next scheduled/manual run.
        retention = apply_storage_retention(force=True)
        return {**settings.as_dict(), "retention": retention.as_dict(), "scheduler": scheduler_status()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=storage_bootstrap_error_detail(exc)) from exc
