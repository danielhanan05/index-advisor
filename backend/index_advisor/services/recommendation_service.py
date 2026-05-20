from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from index_advisor.api.errors import api_error
from index_advisor.api.serializers import row_to_dict, rows_to_list, to_jsonable
from index_advisor.utils.sql_utils import is_safe_recommended_index_sql, render_query_with_bind_values
from index_advisor.db import get_storage_connection, get_target_connection
from index_advisor.storage.repositories import recommendations as rec_repo
from index_advisor.targets.postgres.analyzer.hypopg_validator import validate_with_hypopg

logger = logging.getLogger(__name__)


def _repo_value_error(exc: ValueError) -> HTTPException:
    return api_error(
        400,
        title="Invalid filter",
        message=str(exc),
        error_type="INVALID_FILTER",
        action_items=["Use one of the supported filter values."],
    )


def get_recommendation_or_404(recommendation_id: int) -> dict[str, Any]:
    with get_storage_connection() as conn:
        row = rec_repo.get_recommendation_with_plan(conn, recommendation_id)
    if not row:
        raise api_error(404, title="Recommendation not found", message="Recommendation not found.", error_type="RECOMMENDATION_NOT_FOUND")
    return row


def list_recommendations(**kwargs) -> dict[str, object]:
    try:
        with get_storage_connection() as conn:
            rows = rec_repo.list_recommendations(conn, **kwargs)
    except ValueError as exc:
        raise _repo_value_error(exc) from exc
    return {"items": rows_to_list(rows), "limit": kwargs["limit"], "offset": kwargs["offset"]}


def list_recommendation_history(**kwargs) -> dict[str, object]:
    try:
        with get_storage_connection() as conn:
            rows = rec_repo.list_recommendation_history(conn, **kwargs)
    except ValueError as exc:
        raise _repo_value_error(exc) from exc
    return {"items": rows_to_list(rows), "limit": kwargs["limit"], "offset": kwargs["offset"]}


def list_run_recommendations(run_id, *, limit: int, offset: int) -> dict[str, object]:
    with get_storage_connection() as conn:
        rows = rec_repo.list_run_recommendations(conn, run_id=run_id, limit=limit, offset=offset)
    return {"items": rows_to_list(rows), "limit": limit, "offset": offset}


def get_recommendation(recommendation_id: int) -> dict[str, object]:
    rec = get_recommendation_or_404(recommendation_id)
    data = row_to_dict(rec) or {}

    with get_storage_connection() as conn:
        validations = rec_repo.get_validations(conn, recommendation_id)

    data["validations"] = rows_to_list(validations)
    selected_validation = next((v for v in data["validations"] if v.get("is_selected_option")), None)
    if selected_validation:
        data["validation_original_plan_json"] = selected_validation.get("original_plan_json")
        data["validation_hypothetical_plan_json"] = selected_validation.get("hypothetical_plan_json")

    user_validation = next((v for v in data["validations"] if v.get("validation_type") == "USER_VALIDATION"), None)
    if user_validation:
        data["user_validated_at"] = user_validation.get("created_at")
        data["user_validation_improvement_pct"] = user_validation.get("improvement_pct")

    return data


def revalidate_recommendation(recommendation_id: int, bind_values: dict[str, Any]) -> dict[str, object]:
    rec = get_recommendation_or_404(recommendation_id)

    query_text = rec.get("normalized_query_text") or rec.get("sampled_query_text")
    if not query_text:
        raise api_error(400, title="Cannot revalidate", message="Recommendation has no query text to revalidate.", error_type="REVALIDATION_NOT_AVAILABLE")

    target_id = rec.get("target_id")
    try:
        rendered_query = render_query_with_bind_values(str(query_text), bind_values, target_id=target_id)
    except ValueError as exc:
        raise api_error(
            400,
            title="Invalid bind values",
            message=str(exc),
            error_type="INVALID_BIND_VALUES",
            action_items=["Check that all required bind values are provided and that the query is a SELECT or WITH statement."],
        ) from exc

    recommended_index_sql = str(rec["recommended_index_sql"])

    with get_target_connection(target_id) as target_conn:
        result = validate_with_hypopg(target_conn, query_text=rendered_query, create_index_sql_text=recommended_index_sql)

    if result.original_cost is None or result.hypothetical_cost is None:
        raise api_error(400, title="Revalidation failed", message="Could not revalidate recommendation with provided bind values.", error_type="REVALIDATION_FAILED")

    with get_storage_connection() as storage_conn:
        rec_repo.update_validation_state(storage_conn, recommendation_id, bool(result.validated))
        validation_id = rec_repo.insert_recommendation_validation(
            storage_conn,
            recommendation_id=recommendation_id,
            validation_type="USER_VALIDATION",
            option_rank=None,
            is_selected_option=True,
            index_sql=recommended_index_sql,
            bind_values_json=to_jsonable(bind_values),
            rendered_query_text=rendered_query,
            original_cost=result.original_cost,
            hypothetical_cost=result.hypothetical_cost,
            improvement_pct=result.improvement_pct,
            original_plan_json=to_jsonable(result.original_plan),
            hypothetical_plan_json=to_jsonable(result.hypothetical_plan),
        )
        storage_conn.commit()

    return {
        "recommendation_id": recommendation_id,
        "validation_id": validation_id,
        "validation_type": "USER_VALIDATION",
        "validated": bool(result.validated),
        "query_text": rendered_query,
        "bind_values": to_jsonable(bind_values),
        "original_cost": result.original_cost,
        "hypothetical_cost": result.hypothetical_cost,
        "improvement_pct": result.improvement_pct,
        "original_plan_json": to_jsonable(result.original_plan),
        "hypothetical_plan_json": to_jsonable(result.hypothetical_plan),
        "recommended_index_sql": recommended_index_sql,
        "warning": "Validated using user-provided bind values. Actual production performance may still vary.",
    }


def apply_recommendation(recommendation_id: int, confirm: str) -> dict[str, object]:
    if confirm != "APPLY":
        raise api_error(400, title="Confirmation required", message="Confirmation required. Send confirm='APPLY'.", error_type="CONFIRMATION_REQUIRED")

    rec = get_recommendation_or_404(recommendation_id)
    index_sql = str(rec["recommended_index_sql"])

    if not is_safe_recommended_index_sql(index_sql):
        raise api_error(400, title="Unsafe index SQL", message="Recommended index SQL failed safety validation.", error_type="UNSAFE_INDEX_SQL")

    try:
        with get_target_connection(rec.get("target_id")) as target_conn:
            target_conn.autocommit = True
            with target_conn.cursor() as cur:
                cur.execute(index_sql)

        with get_storage_connection() as storage_conn:
            rec_repo.update_status(storage_conn, recommendation_id, "APPLIED", "Index was applied through the product API.")
            storage_conn.commit()

        return {"status": "APPLIED", "recommendation_id": recommendation_id, "executed_sql": index_sql}

    except Exception as exc:
        logger.exception("Failed applying recommended index id=%s", recommendation_id)
        with get_storage_connection() as storage_conn:
            rec_repo.update_status(storage_conn, recommendation_id, "ACTIVE", f"Last apply attempt failed: {exc}")
            storage_conn.commit()
        raise api_error(500, title="Apply index failed", message=f"Failed applying index: {exc}", error_type="APPLY_INDEX_FAILED") from exc
