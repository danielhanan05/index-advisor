from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from index_advisor.storage.repositories.common import SCHEMA, fetch_all
from index_advisor.storage.repositories.runs import get_latest_run


def query_stats(
    conn: psycopg.Connection,
    *,
    run_id: UUID | None,
    target_id: int | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[object] = []

    if run_id:
        conditions.append("qs.collection_run_id = %s")
        params.append(run_id)

    if target_id is not None:
        conditions.append(f"qs.collection_run_id IN (SELECT id FROM {SCHEMA}.collection_runs WHERE target_id = %s)")
        params.append(target_id)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.extend([limit, offset])
    return fetch_all(
        conn,
        f"""
        SELECT
            qs.id,
            qs.collection_run_id,
            qs.queryid,
            qs.query_text,
            qs.calls,
            qs.mean_exec_time,
            qs.total_exec_time,
            qs.captured_at,
            qp.id AS collected_plan_id,
            qp.plan AS collected_plan_json,
            qp.captured_at AS collected_plan_captured_at
        FROM {SCHEMA}.query_stats qs
        LEFT JOIN LATERAL (
            SELECT id, plan, captured_at
            FROM {SCHEMA}.query_plans qp
            WHERE qp.collection_run_id = qs.collection_run_id
              AND qp.queryid = qs.queryid
            ORDER BY captured_at DESC
            LIMIT 1
        ) qp ON true
        {where}
        ORDER BY qs.total_exec_time DESC
        LIMIT %s OFFSET %s;
        """,
        tuple(params),
    )


def table_stats(conn: psycopg.Connection, *, run_id: UUID | None, target_id: int | None) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[object] = []

    if run_id:
        conditions.append("r.collection_run_id = %s")
        params.append(run_id)

    if target_id is not None:
        conditions.append(f"r.collection_run_id IN (SELECT id FROM {SCHEMA}.collection_runs WHERE target_id = %s)")
        params.append(target_id)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return fetch_all(conn, f"SELECT * FROM {SCHEMA}.table_stats r {where} ORDER BY schemaname, table_name;", tuple(params))


def index_stats(conn: psycopg.Connection, *, run_id: UUID | None, target_id: int | None) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[object] = []

    if run_id:
        conditions.append("r.collection_run_id = %s")
        params.append(run_id)

    if target_id is not None:
        conditions.append(f"r.collection_run_id IN (SELECT id FROM {SCHEMA}.collection_runs WHERE target_id = %s)")
        params.append(target_id)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return fetch_all(conn, f"SELECT * FROM {SCHEMA}.index_stats r {where} ORDER BY schemaname, table_name, index_name;", tuple(params))


def summary(conn: psycopg.Connection, *, target_id: int | None = None) -> dict[str, Any] | None:
    latest = get_latest_run(conn, completed_only=True, target_id=target_id)
    if not latest:
        return None

    run_id = latest["id"]
    counts = fetch_all(
        conn,
        f"""
        SELECT validation_type, COUNT(*) AS count
        FROM {SCHEMA}.recommendations
        WHERE collection_run_id = %s
        GROUP BY validation_type
        ORDER BY validation_type;
        """,
        (run_id,),
    )

    top_recs = fetch_all(
        conn,
        f"""
        SELECT
            r.id,
            r.table_name,
            r.columns,
            r.score,
            r.improvement_pct,
            r.validation_type,
            r.recommended_index_sql,
            r.status,
            uv.improvement_pct AS user_validation_improvement_pct,
            r.alternative_options_json
        FROM {SCHEMA}.recommendations r
        LEFT JOIN LATERAL (
            SELECT improvement_pct
            FROM {SCHEMA}.recommendation_validations rv
            WHERE rv.recommendation_id = r.id
              AND rv.validation_type = 'USER_VALIDATION'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) uv ON true
        WHERE r.collection_run_id = %s
          AND r.status = 'ACTIVE'
        ORDER BY r.score DESC, r.improvement_pct DESC NULLS LAST
        LIMIT 10;
        """,
        (run_id,),
    )

    return {"latest_run": latest, "recommendation_counts": counts, "top_recommendations": top_recs}
