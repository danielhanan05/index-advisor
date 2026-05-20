"""Collection run endpoints."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from index_advisor.api.errors import api_error
from index_advisor.api.schemas import ItemListResponse, RunDetailResponse, StatusResponse
from index_advisor.api.security import require_admin_token
from index_advisor.api.serializers import row_to_dict, rows_to_list
from index_advisor.api.jobs import run_collect_and_analyze
from index_advisor.db import get_storage_connection
from index_advisor.storage.repositories import recommendations as rec_repo
from index_advisor.storage.repositories import runs as run_repo
from index_advisor.storage.repositories import targets as target_repo

router = APIRouter()


@router.post("/runs/manual", status_code=202, response_model=StatusResponse, dependencies=[Depends(require_admin_token)])
def trigger_manual_run(background_tasks: BackgroundTasks, target_id: int | None = None) -> dict[str, str]:
    with get_storage_connection() as conn:
        resolved_target_id = target_repo.get_default_target_id(conn) if target_id is None else target_id

    if resolved_target_id is None:
        raise api_error(400, title="No target configured", message="No database target configured. Add a database target first.", error_type="NO_TARGET_CONFIGURED")

    background_tasks.add_task(run_collect_and_analyze, resolved_target_id)
    return {"status": "accepted", "message": "collect + analyze started in background", "target_id": str(resolved_target_id)}


@router.get("/runs", response_model=ItemListResponse)
def list_runs(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: str | None = Query(default=None, description="Optional status filter: RUNNING, COMPLETED, FAILED"),
    target_id: int | None = None,
) -> dict[str, object]:
    with get_storage_connection() as conn:
        rows = run_repo.list_runs(conn, limit=limit, offset=offset, status=status, target_id=target_id)
    return {"items": rows_to_list(rows), "limit": limit, "offset": offset}


@router.get("/runs/latest")
def latest_run(completed_only: bool = True, target_id: int | None = None) -> dict[str, object]:
    with get_storage_connection() as conn:
        row = run_repo.get_latest_run(conn, completed_only=completed_only, target_id=target_id)

    if not row:
        raise api_error(404, title="No runs found", message="No collection runs found.", error_type="RUN_NOT_FOUND")

    return row_to_dict(row) or {}


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: UUID) -> dict[str, object]:
    with get_storage_connection() as conn:
        run = run_repo.get_run(conn, run_id)
        if not run:
            raise api_error(404, title="Run not found", message="Run not found.", error_type="RUN_NOT_FOUND")
        counts = run_repo.counts_for_run(conn, run_id)

    return {"run": row_to_dict(run), "counts": counts}


@router.get("/runs/{run_id}/recommendations", response_model=ItemListResponse)
def get_run_recommendations(
    run_id: UUID,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    with get_storage_connection() as conn:
        rows = rec_repo.list_run_recommendations(conn, run_id=run_id, limit=limit, offset=offset)
    return {"items": rows_to_list(rows), "limit": limit, "offset": offset}
