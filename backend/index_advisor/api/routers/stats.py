"""Workload statistics and dashboard summary endpoints."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from index_advisor.api.schemas import ItemListResponse
from index_advisor.api.serializers import row_to_dict, rows_to_list
from index_advisor.db import get_storage_connection
from index_advisor.storage.repositories import stats as stats_repo

router = APIRouter()


@router.get("/query-stats", response_model=ItemListResponse)
def list_query_stats(
    run_id: UUID | None = None,
    target_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    with get_storage_connection() as conn:
        rows = stats_repo.query_stats(conn, run_id=run_id, target_id=target_id, limit=limit, offset=offset)
    return {"items": rows_to_list(rows), "limit": limit, "offset": offset}


@router.get("/table-stats", response_model=ItemListResponse)
def list_table_stats(run_id: UUID | None = None, target_id: int | None = None) -> dict[str, object]:
    with get_storage_connection() as conn:
        rows = stats_repo.table_stats(conn, run_id=run_id, target_id=target_id)
    return {"items": rows_to_list(rows)}


@router.get("/index-stats", response_model=ItemListResponse)
def list_index_stats(run_id: UUID | None = None, target_id: int | None = None) -> dict[str, object]:
    with get_storage_connection() as conn:
        rows = stats_repo.index_stats(conn, run_id=run_id, target_id=target_id)
    return {"items": rows_to_list(rows)}


@router.get("/summary")
def summary(target_id: int | None = None) -> dict[str, object]:
    with get_storage_connection() as conn:
        data = stats_repo.summary(conn, target_id=target_id)

    if not data:
        return {"latest_run": None, "recommendation_counts": [], "top_recommendations": []}

    return {
        "latest_run": row_to_dict(data["latest_run"]),
        "recommendation_counts": rows_to_list(data["recommendation_counts"]),
        "top_recommendations": rows_to_list(data["top_recommendations"]),
    }
