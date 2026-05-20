from __future__ import annotations

import logging
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

from index_advisor.config import load_config
from index_advisor.db import (
    check_required_extensions,
    ensure_storage_database_exists,
    get_storage_connection,
    get_target_connection,
)
from index_advisor.storage.repositories import workload as repo
from index_advisor.targets.postgres.collector.queries import INDEX_STATS_SQL, TABLE_STATS_SQL, TOP_QUERIES_SQL
from index_advisor.utils.sql_utils import (
    has_parameters,
    is_internal_query,
    is_select_query,
    is_unsafe_to_explain,
)

logger = logging.getLogger(__name__)


def _fetchall(conn: psycopg.Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return list(cur.fetchall())


def _explain_json(conn: psycopg.Connection, query_text: str) -> Any:
    conn.row_factory = dict_row
    with conn.cursor() as cur:
        cur.execute("EXPLAIN (FORMAT JSON) " + query_text)
        row = cur.fetchone()
        return row["QUERY PLAN"]


def collect(target_id: int | None = None) -> uuid.UUID:
    cfg = load_config()
    # Collector only strictly needs pg_stat_statements; HypoPG is for analyzer.
    check_required_extensions(require_hypopg=False, target_id=target_id)
    ensure_storage_database_exists()

    with get_storage_connection() as sconn, get_target_connection(target_id) as tconn:
        run_id = repo.create_collection_run(sconn, target_id=target_id)
        sconn.commit()
        logger.info("Started collection run %s", run_id)

        try:
            top_queries = _fetchall(tconn, TOP_QUERIES_SQL, {"limit": cfg.top_query_limit})
            repo.insert_query_stats(sconn, run_id, top_queries)
            sconn.commit()
            logger.info("Collected %d top queries", len(top_queries))

            table_stats = _fetchall(tconn, TABLE_STATS_SQL)
            repo.insert_table_stats(sconn, run_id, table_stats)
            sconn.commit()
            logger.info("Collected %d table stats rows", len(table_stats))

            index_stats = _fetchall(tconn, INDEX_STATS_SQL)
            repo.insert_index_stats(sconn, run_id, index_stats)
            sconn.commit()
            logger.info("Collected %d index stats rows", len(index_stats))

            explained = 0
            skipped_params = 0
            skipped_nonselect = 0
            skipped_unsafe = 0
            skipped_system = 0
            failed_explain = 0

            for q in top_queries:
                queryid = str(q.get("queryid", ""))
                query_text = str(q.get("query", "")).strip().rstrip(";")
                if not query_text:
                    continue

                if is_internal_query(query_text):
                    skipped_system += 1
                    logger.info("Skipping system/internal query for queryid=%s", queryid)
                    continue

                if is_unsafe_to_explain(query_text):
                    skipped_unsafe += 1
                    continue

                if not is_select_query(query_text):
                    skipped_nonselect += 1
                    continue

                if has_parameters(query_text):
                    skipped_params += 1
                    logger.info("Skipping EXPLAIN for parameterized queryid=%s", queryid)
                    continue

                try:
                    plan = _explain_json(tconn, query_text)
                except Exception:
                    failed_explain += 1
                    logger.exception("EXPLAIN failed for queryid=%s; skipping plan", queryid)
                    try:
                        tconn.rollback()
                    except Exception:
                        pass
                    continue

                try:
                    repo.insert_query_plan(sconn, run_id, queryid, query_text, plan)
                    sconn.commit()
                    explained += 1
                except Exception:
                    logger.exception("Failed storing plan for queryid=%s; continuing", queryid)
                    try:
                        sconn.rollback()
                    except Exception:
                        pass

            logger.info(
                "Plan capture summary: explained=%d skipped_params=%d skipped_nonselect=%d skipped_unsafe=%d skipped_system=%d failed_explain=%d",
                explained,
                skipped_params,
                skipped_nonselect,
                skipped_unsafe,
                skipped_system,
                failed_explain,
            )

            repo.complete_collection_run(sconn, run_id)
            sconn.commit()
            logger.info("Completed collection run %s", run_id)
            return run_id

        except Exception as e:
            logger.exception("Collection failed for run %s", run_id)
            try:
                repo.fail_collection_run(sconn, run_id, str(e))
                sconn.commit()
            except Exception:
                try:
                    sconn.rollback()
                except Exception:
                    pass
            raise

