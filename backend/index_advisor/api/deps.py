"""Shared API helpers used by multiple router modules.

Keep this module focused on API plumbing only. Business logic and SQL helpers
belong in services, repositories, or utils modules.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from index_advisor.api.errors import storage_bootstrap_error_detail
from index_advisor.db import get_storage_connection
from index_advisor.storage.repositories import recommendations as rec_repo
from index_advisor.storage.repositories import targets as target_repo
from index_advisor.storage.repositories.common import fetch_one


def storage_ready_or_503() -> None:
    """Fast storage connectivity check.

    Migrations are applied once during application startup. This function only
    verifies that the storage DB can be reached by request handlers.
    """
    try:
        with get_storage_connection() as conn:
            fetch_one(conn, "SELECT 1 AS ok;")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=storage_bootstrap_error_detail(exc)) from exc


def get_target_or_404(target_id: int) -> dict[str, Any]:
    storage_ready_or_503()
    with get_storage_connection() as conn:
        row = target_repo.get_target(conn, target_id, include_password=True)
    if not row:
        raise HTTPException(status_code=404, detail="Database target not found")
    return row


def select_default_target_id(target_id: int | None = None) -> int | None:
    if target_id is not None:
        return target_id

    storage_ready_or_503()
    with get_storage_connection() as conn:
        return target_repo.get_default_target_id(conn)


def get_recommendation_or_404(recommendation_id: int) -> dict[str, Any]:
    with get_storage_connection() as conn:
        row = rec_repo.get_recommendation_with_plan(conn, recommendation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return row
