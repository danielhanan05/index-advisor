from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from index_advisor.targets.postgres.analyzer.index_utils import normalize_for_hypopg
from index_advisor.targets.postgres.analyzer.plan_utils import extract_total_cost

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HypoPgResult:
    validated: bool
    original_cost: float | None
    hypothetical_cost: float | None
    improvement_pct: float | None
    original_plan: Any | None = None
    hypothetical_plan: Any | None = None


def _explain_json(conn: psycopg.Connection, query_text: str) -> Any:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("EXPLAIN (FORMAT JSON) " + query_text)
        row = cur.fetchone()
        return row["QUERY PLAN"]


def validate_with_hypopg(conn: psycopg.Connection, *, query_text: str, create_index_sql_text: str) -> HypoPgResult:
    q = (query_text or "").strip().rstrip(";")
    idx = normalize_for_hypopg(create_index_sql_text)

    try:
        original_plan = _explain_json(conn, q)
        original_cost = extract_total_cost(original_plan)

        with conn.cursor() as cur:
            cur.execute("SELECT hypopg_reset();")
            cur.execute("SELECT * FROM hypopg_create_index(%s);", (idx,))

        hypothetical_plan = _explain_json(conn, q)
        hypothetical_cost = extract_total_cost(hypothetical_plan)

        with conn.cursor() as cur:
            cur.execute("SELECT hypopg_reset();")

        if original_cost is None or hypothetical_cost is None or original_cost <= 0:
            return HypoPgResult(
                False,
                original_cost,
                hypothetical_cost,
                None,
                original_plan=original_plan,
                hypothetical_plan=hypothetical_plan,
            )

        improvement_pct = (original_cost - hypothetical_cost) / original_cost * 100.0
        validated = improvement_pct > 0
        return HypoPgResult(
            validated,
            original_cost,
            hypothetical_cost,
            improvement_pct,
            original_plan=original_plan,
            hypothetical_plan=hypothetical_plan,
        )

    except Exception:
        logger.exception("HypoPG validation failed for candidate index")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT hypopg_reset();")
        except Exception:
            pass
        try:
            conn.rollback()
        except Exception:
            pass
        return HypoPgResult(False, None, None, None, original_plan=None, hypothetical_plan=None)

