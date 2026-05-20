from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import uuid
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row


SCHEMA = "index_advisor"


@dataclass(frozen=True)
class CollectionRun:
    id: uuid.UUID
    started_at: datetime
    completed_at: datetime | None
    status: str
    error_message: str | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_collection_run(conn: psycopg.Connection, target_id: int | None = None) -> uuid.UUID:
    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.collection_runs (id, target_id, started_at, status)
            VALUES (%s, %s, %s, %s);
            """,
            (run_id, target_id, _utcnow(), "RUNNING"),
        )
    return run_id


def complete_collection_run(conn: psycopg.Connection, run_id: uuid.UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.collection_runs
            SET completed_at = %s,
                status = %s,
                error_message = NULL
            WHERE id = %s;
            """,
            (_utcnow(), "COMPLETED", run_id),
        )


def fail_collection_run(conn: psycopg.Connection, run_id: uuid.UUID, error_message: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.collection_runs
            SET completed_at = %s,
                status = %s,
                error_message = %s
            WHERE id = %s;
            """,
            (_utcnow(), "FAILED", error_message[:10_000], run_id),
        )


def insert_query_stats(conn: psycopg.Connection, run_id: uuid.UUID, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    values = [
        (
            run_id,
            str(r.get("queryid", "")),
            str(r.get("query", "")),
            int(r.get("calls", 0)),
            float(r.get("mean_exec_time", 0.0)),
            float(r.get("total_exec_time", 0.0)),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {SCHEMA}.query_stats
              (collection_run_id, queryid, query_text, calls, mean_exec_time, total_exec_time)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            values,
        )


def insert_table_stats(conn: psycopg.Connection, run_id: uuid.UUID, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    values = [
        (
            run_id,
            str(r["schemaname"]),
            str(r["relname"]),
            int(r.get("seq_scan", 0)),
            int(r.get("idx_scan", 0)),
            int(r.get("n_tup_ins", 0)),
            int(r.get("n_tup_upd", 0)),
            int(r.get("n_tup_del", 0)),
            int(r.get("writes", 0)),
            int(r.get("n_live_tup", 0)),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {SCHEMA}.table_stats
              (collection_run_id, schemaname, table_name, seq_scan, idx_scan,
               n_tup_ins, n_tup_upd, n_tup_del, writes, n_live_tup)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            values,
        )


def insert_index_stats(conn: psycopg.Connection, run_id: uuid.UUID, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        return
    values = [
        (
            run_id,
            str(r["schemaname"]),
            str(r["relname"]),
            str(r["indexrelname"]),
            int(r.get("idx_scan", 0)),
            int(r.get("idx_tup_read", 0)),
            int(r.get("idx_tup_fetch", 0)),
            str(r.get("indexdef", "")),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {SCHEMA}.index_stats
              (collection_run_id, schemaname, table_name, index_name, idx_scan,
               idx_tup_read, idx_tup_fetch, indexdef)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """,
            values,
        )


def insert_query_plan(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    queryid: str,
    query_text: str,
    plan: Any,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.query_plans (collection_run_id, queryid, query_text, plan)
            VALUES (%s, %s, %s, %s::jsonb);
            """,
            (run_id, str(queryid), query_text, json.dumps(plan)),
        )


def get_latest_completed_collection_run(conn: psycopg.Connection, target_id: int | None = None) -> CollectionRun | None:
    conn.row_factory = dict_row
    where = "WHERE status = 'COMPLETED'"
    params: tuple[Any, ...] = ()
    if target_id is not None:
        where += " AND target_id = %s"
        params = (target_id,)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, started_at, completed_at, status, error_message
            FROM {SCHEMA}.collection_runs
            {where}
            ORDER BY completed_at DESC NULLS LAST
            LIMIT 1;
            """,
            params,
        )
        row = cur.fetchone()
    if not row:
        return None
    return CollectionRun(
        id=row["id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        status=row["status"],
        error_message=row["error_message"],
    )


def get_query_stats_for_run(conn: psycopg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {SCHEMA}.query_stats
            WHERE collection_run_id = %s
            ORDER BY total_exec_time DESC;
            """,
            (run_id,),
        )
        return list(cur.fetchall())


def get_table_stats_for_run(conn: psycopg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {SCHEMA}.table_stats
            WHERE collection_run_id = %s;
            """,
            (run_id,),
        )
        return list(cur.fetchall())


def get_index_stats_for_run(conn: psycopg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {SCHEMA}.index_stats
            WHERE collection_run_id = %s;
            """,
            (run_id,),
        )
        return list(cur.fetchall())


def get_query_plans_for_run(conn: psycopg.Connection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {SCHEMA}.query_plans
            WHERE collection_run_id = %s;
            """,
            (run_id,),
        )
        return list(cur.fetchall())


def insert_recommendation(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    queryid: str,
    schemaname: str,
    table_name: str,
    columns: list[str],
    recommended_index_sql: str,
    score: float,
    reason: str,
    validated: bool,
    original_cost: float | None,
    hypothetical_cost: float | None,
    improvement_pct: float | None,
    *,
    validation_type: str | None = None,
    parameterized_query: bool | None = None,
    sampled_validation: bool | None = None,
    normalized_query_text: str | None = None,
    sampled_query_text: str | None = None,
    sampled_values_json: dict[str, Any] | None = None,
    alternative_options_json: list[dict[str, Any]] | None = None,
    validation_original_plan_json: Any | None = None,
    validation_hypothetical_plan_json: Any | None = None,
) -> int:
    """
    Insert the main recommendation row and return its id.

    The recommendations table intentionally stores only the current/main summary.
    Heavy validation evidence (bind values, rendered query text and execution plans)
    is stored in index_advisor.recommendation_validations.

    The optional plan/sample arguments are kept in the function signature for
    compatibility with older analyzer calls, but they are not stored directly on
    recommendations anymore.
    """
    vtype = validation_type or ("VALIDATED" if validated else "HEURISTIC_ONLY")
    param_q = bool(parameterized_query) if parameterized_query is not None else False
    samp_v = bool(sampled_validation) if sampled_validation is not None else False

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {SCHEMA}.recommendations
              (collection_run_id, queryid, schemaname, table_name, columns, recommended_index_sql,
               score, reason, validated, original_cost, hypothetical_cost, improvement_pct,
               validation_type, parameterized_query, sampled_validation, normalized_query_text,
               sampled_query_text, alternative_options_json, status, status_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'ACTIVE', %s)
            RETURNING id;
            """,
            (
                run_id,
                str(queryid),
                schemaname,
                table_name,
                columns,
                recommended_index_sql,
                score,
                reason,
                validated,
                original_cost,
                hypothetical_cost,
                improvement_pct,
                vtype,
                param_q,
                samp_v,
                normalized_query_text,
                sampled_query_text,
                json.dumps(alternative_options_json or [], default=str),
                "Recommendation is active and no matching existing index was detected.",
            ),
        )
        row = cur.fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])


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


def get_recommendation_validations(conn: psycopg.Connection, recommendation_id: int) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM {SCHEMA}.recommendation_validations
            WHERE recommendation_id = %s
            ORDER BY
              CASE WHEN is_selected_option THEN 0 ELSE 1 END,
              option_rank NULLS LAST,
              created_at DESC,
              id DESC;
            """,
            (recommendation_id,),
        )
        return list(cur.fetchall())


def update_recommendation_status(
    conn: psycopg.Connection,
    recommendation_id: int,
    status: str,
    reason: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {SCHEMA}.recommendations
            SET status = %s,
                status_reason = %s,
                status_updated_at = now()
            WHERE id = %s;
            """,
            (status, reason, recommendation_id),
        )
