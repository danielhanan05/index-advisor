"""Database target management endpoints.

Routers are intentionally thin: validation/authentication happen here, while
workflow and SQL are delegated to service/repository modules.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from index_advisor.api.deps import storage_ready_or_503
from index_advisor.api.schemas import (
    DatabaseTargetRequest,
    DatabaseTargetUpdateRequest,
    ItemListResponse,
    StatusResponse,
    TargetCheckResponse,
    TargetCreateResponse,
    TargetExtensionCheckResponse,
)
from index_advisor.api.security import require_admin_token
from index_advisor.api.jobs import run_collect_and_analyze
from index_advisor.services import target_service

router = APIRouter()


@router.get("/targets", response_model=ItemListResponse)
def list_targets() -> dict[str, object]:
    storage_ready_or_503()
    return target_service.list_targets()


@router.post("/targets", response_model=TargetCreateResponse, dependencies=[Depends(require_admin_token)])
def create_target(body: DatabaseTargetRequest) -> dict[str, object]:
    return target_service.create_target(body)


@router.get("/targets/{target_id}")
def get_target(target_id: int) -> dict[str, object]:
    return target_service.get_target(target_id)


@router.put("/targets/{target_id}", response_model=StatusResponse, dependencies=[Depends(require_admin_token)])
def update_target(target_id: int, body: DatabaseTargetUpdateRequest) -> dict[str, object]:
    return target_service.update_target(target_id, body)


@router.delete("/targets/{target_id}", response_model=StatusResponse, dependencies=[Depends(require_admin_token)])
def delete_target(target_id: int) -> dict[str, object]:
    return target_service.delete_target(target_id)


@router.post("/targets/{target_id}/test-connection", response_model=TargetCheckResponse, dependencies=[Depends(require_admin_token)])
def test_existing_target_connection(target_id: int) -> dict[str, object]:
    return target_service.test_existing_target_connection(target_id)


@router.post("/targets/{target_id}/check-extensions", response_model=TargetExtensionCheckResponse, dependencies=[Depends(require_admin_token)])
def check_existing_target_extensions(target_id: int, attempt_create: bool = True) -> dict[str, object]:
    return target_service.check_existing_target_extensions(target_id, attempt_create=attempt_create)


@router.post("/targets/{target_id}/runs/manual", status_code=202, response_model=StatusResponse, dependencies=[Depends(require_admin_token)])
def trigger_manual_run_for_target(target_id: int, background_tasks: BackgroundTasks) -> dict[str, str]:
    target_service.get_target(target_id)
    background_tasks.add_task(run_collect_and_analyze, target_id)
    return {"status": "accepted", "message": "collect + analyze started in background", "target_id": str(target_id)}
