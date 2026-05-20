from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import psycopg

from index_advisor.storage.repositories.common import SCHEMA, fetch_all, fetch_one

_VALIDATION_TYPES = {"HEURISTIC_ONLY", "HYPOPG_VALIDATED", "SAMPLED_VALIDATED", "USER_VALIDATED", "USER_VALIDATION"}
_STATUSES = {"ACTIVE", "APPLIED", "DISMISSED", "FAILED", "SUPERSEDED"}


def normalize_validation_type(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    normalized = value.strip().upper()
    if normalized not in _VALIDATION_TYPES:
        raise ValueError(f"Unsupported validation_type '{value}'. Allowed values: {sorted(_VALIDATION_TYPES)}")
    return normalized


def normalize_status(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    normalized = value.strip().upper()
    if normalized not in _STATUSES:
        raise ValueError(f"Unsupported recommendation status '{value}'. Allowed values: {sorted(_STATUSES)}")
    return normalized


def recommendation_select_sql() -> str:
    return f"""
        SELECT
            r.id,
            r.collection_run_id,
            r.queryid,
            r.schemaname,
            r.table_name,
            r.columns,
            r.recommended_index_sql,
            r.score,
            r.reason,
            r.validated,
            r.original_cost,
            r.hypothetical_cost,
            r.improvement_pct,
            r.created_at,
            r.validation_type,
            r.parameterized_query,
            r.sampled_validation,
            r.normalized_query_text,
            r.sampled_query_text,
            r.alternative_options_json,
            r.status,
            r.status_reason,
            r.status_updated_at,
            uv.created_at AS user_validated_at,
            uv.improvement_pct AS user_validation_improvement_pct
        FROM {SCHEMA}.recommendations r
        LEFT JOIN LATERAL (
            SELECT created_at, improvement_pct
            FROM {SCHEMA}.recommendation_validations rv
            WHERE rv.recommendation_id = r.id
              AND rv.validation_type = 'USER_VALIDATION'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) uv ON true
    """


def _filters(
    *,
    run_id: UUID | None = None,
    target_id: int | None = None,
    latest_for_target: bool = False,
    validation_type: str | None = None,
    table_name: str | None = None,
    status: str | None = None,
    min_score: float | None = None,
) -> tuple[str, list[object]]:
    conditions: list[str] = []
    params: list[object] = []

    if run_id:
        conditions.append("r.collection_run_id = %s")
        params.append(run_id)
    elif target_id is not None and latest_for_target:
        conditions.append(
            f"""
            r.collection_run_id = (
                SELECT cr.id
                FROM {SCHEMA}.collection_runs cr
                WHERE cr.target_id = %s
                  AND cr.status = 'COMPLETED'
                ORDER BY cr.completed_at DESC NULLS LAST, cr.started_at DESC
                LIMIT 1
            )
            """
        )
        params.append(target_id)
    elif target_id is not None:
        conditions.append(
            f"""
            r.collection_run_id IN (
                SELECT cr.id
                FROM {SCHEMA}.collection_runs cr
                WHERE cr.target_id = %s
            )
            """
        )
        params.append(target_id)

    normalized_validation_type = normalize_validation_type(validation_type)
    if normalized_validation_type:
        conditions.append("r.validation_type = %s")
        params.append(normalized_validation_type)

    if table_name:
        conditions.append("r.table_name = %s")
        params.append(table_name)

    normalized_status = normalize_status(status)
    if normalized_status:
        conditions.append("r.status = %s")
        params.append(normalized_status)

    if min_score is not None:
        conditions.append("r.score >= %s")
        params.append(min_score)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where, params


def list_recommendations(
    conn: psycopg.Connection,
    *,
    run_id: UUID | None = None,
    target_id: int | None = None,
    limit: int,
    offset: int,
    validation_type: str | None = None,
    table_name: str | None = None,
    status: str | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    where, params = _filters(
        run_id=run_id,
        target_id=target_id,
        latest_for_target=True,
        validation_type=validation_type,
        table_name=table_name,
        status=status,
        min_score=min_score,
    )
    params.extend([limit, offset])
    return fetch_all(
        conn,
        f"""
        {recommendation_select_sql()}
        {where}
        ORDER BY r.score DESC, r.improvement_pct DESC NULLS LAST, r.created_at DESC
        LIMIT %s OFFSET %s;
        """,
        tuple(params),
    )


def list_recommendation_history(
    conn: psycopg.Connection,
    *,
    target_id: int | None,
    limit: int,
    offset: int,
    validation_type: str | None = None,
    table_name: str | None = None,
    status: str | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    where, params = _filters(
        target_id=target_id,
        latest_for_target=False,
        validation_type=validation_type,
        table_name=table_name,
        status=status,
        min_score=min_score,
    )
    params.extend([limit, offset])
    return fetch_all(
        conn,
        f"""
        {recommendation_select_sql()}
        {where}
        ORDER BY r.created_at DESC, r.score DESC, r.improvement_pct DESC NULLS LAST
        LIMIT %s OFFSET %s;
        """,
        tuple(params),
    )


def list_run_recommendations(conn: psycopg.Connection, *, run_id: UUID, limit: int, offset: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        f"""
        {recommendation_select_sql()}
        WHERE r.collection_run_id = %s
        ORDER BY r.score DESC, r.improvement_pct DESC NULLS LAST, r.created_at DESC
        LIMIT %s OFFSET %s;
        """,
        (run_id, limit, offset),
    )


def get_recommendation_with_plan(conn: psycopg.Connection, recommendation_id: int) -> dict[str, Any] | None:
    return fetch_one(
        conn,
        f"""
        SELECT
            r.*,
            cr.target_id,
            qp.id AS collected_plan_id,
            qp.query_text AS collected_plan_query_text,
            qp.plan AS collected_plan_json,
            qp.captured_at AS collected_plan_captured_at
        FROM {SCHEMA}.recommendations r
        JOIN {SCHEMA}.collection_runs cr ON cr.id = r.collection_run_id
        LEFT JOIN LATERAL (
            SELECT id, query_text, plan, captured_at
            FROM {SCHEMA}.query_plans qp
            WHERE qp.collection_run_id = r.collection_run_id
              AND qp.queryid = r.queryid
            ORDER BY captured_at DESC
            LIMIT 1
        ) qp ON true
        WHERE r.id = %s;
        """,
        (recommendation_id,),
    )


def insert_recommendation_validation(
    conn: psycopg.Connection,
    *,
    recommendation_id: int,
    validation_type: str,
    option_rank: int | None = None,
    is_selected_option: bool = False,
    index_sql: str | None = None,
    bind_values_json: dict[str, Any] | None = None,
    rendered_query_text: str | None = None,
    original_cost: float | None = None,
    hypothetical_cost: float | None = None,
    improvement_pct: float | None = None,
    original_plan_json: Any | None = None,
    hypothetical_plan_json: Any | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.recommendation_validations
              (recommendation_id, validation_type, option_rank, is_selected_option, index_sql,
               bind_values_json, rendered_query_text, original_cost, hypothetical_cost, improvement_pct,
               original_plan_json, hypothetical_plan_json)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            RETURNING id;
            """,
            (
                recommendation_id,
                validation_type,
                option_rank,
                is_selected_option,
                index_sql,
                json.dumps(bind_values_json, default=str) if bind_values_json is not None else None,
                rendered_query_text,
                original_cost,
                hypothetical_cost,
                improvement_pct,
                json.dumps(original_plan_json, default=str) if original_plan_json is not None else None,
                json.dumps(hypothetical_plan_json, default=str) if hypothetical_plan_json is not None else None,
            ),
        )
        row = cur.fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])


def get_validations(conn: psycopg.Connection, recommendation_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        f"""
        SELECT *
        FROM {SCHEMA}.recommendation_validations
        WHERE recommendation_id = %s
        ORDER BY is_selected_option DESC, option_rank NULLS LAST, created_at DESC, id DESC;
        """,
        (recommendation_id,),
    )


def update_validation_state(conn: psycopg.Connection, recommendation_id: int, validated: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.recommendations
            SET validation_type = 'USER_VALIDATED',
                validated = %s
            WHERE id = %s;
            """,
            (bool(validated), recommendation_id),
        )


def update_status(conn: psycopg.Connection, recommendation_id: int, status: str, reason: str | None) -> None:
    normalized_status = normalize_status(status)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.recommendations
            SET status = %s,
                status_reason = %s,
                status_updated_at = now()
            WHERE id = %s;
            """,
            (normalized_status, reason, recommendation_id),
        )
