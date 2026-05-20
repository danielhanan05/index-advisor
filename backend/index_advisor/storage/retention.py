from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

SCHEMA = "index_advisor"
from index_advisor.db import get_storage_connection, has_storage_config
from index_advisor.storage.settings import get_product_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionResult:
    enabled: bool
    retention_days: int
    cutoff: str | None
    deleted_collection_runs: int
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "retention_days": self.retention_days,
            "cutoff": self.cutoff,
            "deleted_collection_runs": self.deleted_collection_runs,
            "message": self.message,
        }


def apply_storage_retention(*, force: bool = False) -> RetentionResult:
    """Delete old storage data using normal PostgreSQL FK cascades.

    This is intentionally implemented in the application instead of depending
    on pg_partman. pg_partman is useful, but it is not safe for the product to
    rely on an OS-level extension that many client PostgreSQL installations do
    not have. The core safety requirement is that storage data cannot grow
    forever, so we enforce retention with DELETE ... CASCADE through the
    collection_runs parent table.

    Deleting collection_runs cascades to:
      - query_stats
      - table_stats
      - index_stats
      - query_plans
      - recommendations
      - recommendation_validations, through recommendations
    """
    settings = get_product_settings()
    retention_days = int(settings.storage_retention_days)

    if retention_days <= 0:
        result = RetentionResult(
            enabled=False,
            retention_days=retention_days,
            cutoff=None,
            deleted_collection_runs=0,
            message="Storage retention disabled because storage_retention_days <= 0.",
        )
        logger.warning(result.message)
        return result

    if not has_storage_config():
        return RetentionResult(
            enabled=True,
            retention_days=retention_days,
            cutoff=None,
            deleted_collection_runs=0,
            message="Storage retention skipped because storage is not configured yet.",
        )

    with get_storage_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (now() - make_interval(days => %s))::text AS cutoff;",
                (retention_days,),
            )
            cutoff = cur.fetchone()["cutoff"]

            cur.execute(
                f"""
                DELETE FROM {SCHEMA}.collection_runs
                WHERE started_at < now() - make_interval(days => %s);
                """,
                (retention_days,),
            )
            deleted = int(cur.rowcount or 0)
        conn.commit()

    if deleted or force:
        logger.info(
            "Storage retention applied. retention_days=%s cutoff=%s deleted_collection_runs=%s",
            retention_days,
            cutoff,
            deleted,
        )
    else:
        logger.debug(
            "Storage retention checked. retention_days=%s cutoff=%s deleted_collection_runs=0",
            retention_days,
            cutoff,
        )

    return RetentionResult(
        enabled=True,
        retention_days=retention_days,
        cutoff=cutoff,
        deleted_collection_runs=deleted,
        message="Storage retention applied successfully.",
    )
