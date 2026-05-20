"""Recommendation endpoints."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from index_advisor.api.schemas import (
    ApplyIndexRequest,
    ItemListResponse,
    RecommendationApplyResponse,
    RecommendationRevalidateResponse,
    RevalidateRequest,
)
from index_advisor.api.security import require_admin_token
from index_advisor.services import recommendation_service

router = APIRouter()


@router.get("/recommendations", response_model=ItemListResponse)
def list_recommendations(
    run_id: UUID | None = None,
    target_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    validation_type: str | None = None,
    table_name: str | None = None,
    status: str | None = None,
    min_score: float | None = Query(default=None, ge=0),
) -> dict[str, object]:
    return recommendation_service.list_recommendations(
        run_id=run_id,
        target_id=target_id,
        limit=limit,
        offset=offset,
        validation_type=validation_type,
        table_name=table_name,
        status=status,
        min_score=min_score,
    )


@router.get("/recommendations/history", response_model=ItemListResponse)
def list_recommendation_history(
    target_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 300,
    offset: Annotated[int, Query(ge=0)] = 0,
    validation_type: str | None = None,
    table_name: str | None = None,
    status: str | None = None,
    min_score: float | None = Query(default=None, ge=0),
) -> dict[str, object]:
    return recommendation_service.list_recommendation_history(
        target_id=target_id,
        limit=limit,
        offset=offset,
        validation_type=validation_type,
        table_name=table_name,
        status=status,
        min_score=min_score,
    )


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: int) -> dict[str, object]:
    return recommendation_service.get_recommendation(recommendation_id)


@router.post("/recommendations/{recommendation_id}/revalidate", response_model=RecommendationRevalidateResponse, dependencies=[Depends(require_admin_token)])
def revalidate_recommendation(recommendation_id: int, body: RevalidateRequest) -> dict[str, object]:
    return recommendation_service.revalidate_recommendation(recommendation_id, body.bind_values)


@router.post("/recommendations/{recommendation_id}/apply", response_model=RecommendationApplyResponse, dependencies=[Depends(require_admin_token)])
def apply_recommendation(recommendation_id: int, body: ApplyIndexRequest) -> dict[str, object]:
    return recommendation_service.apply_recommendation(recommendation_id, body.confirm)
