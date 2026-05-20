"""Small API-facing service helpers shared by routers and scheduler."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from index_advisor.storage.repositories.common import SCHEMA, fetch_all
from index_advisor.db import get_storage_connection, get_target_row, has_storage_config
from index_advisor.storage.retention import apply_storage_retention
from index_advisor.targets.registry import get_adapter

logger = logging.getLogger(__name__)

# Prevent two collect/analyze jobs from running at the same time. This protects
# the storage DB and target DBs from a manual run overlapping a scheduled run.
_run_lock = threading.Lock()


@dataclass(frozen=True)
class TargetRunResult:
    target_id: int
    ok: bool
    run_id: str | None = None
    recommendations_stored: int | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "ok": self.ok,
            "run_id": self.run_id,
            "recommendations_stored": self.recommendations_stored,
            "error": self.error,
        }


@dataclass(frozen=True)
class ScheduledRunSummary:
    source: str
    started_at: str
    finished_at: str
    attempted_targets: int
    successful_targets: int
    failed_targets: int
    skipped: bool
    skip_reason: str | None
    results: list[TargetRunResult]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempted_targets": self.attempted_targets,
            "successful_targets": self.successful_targets,
            "failed_targets": self.failed_targets,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "results": [r.as_dict() for r in self.results],
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def list_active_target_ids() -> list[int]:
    """Return active target IDs ordered by default first, then ID.

    The scheduler uses this instead of choosing only the default target because
    a product installation may manage multiple target databases.
    """
    if not has_storage_config():
        return []

    with get_storage_connection() as conn:
        rows = fetch_all(
            conn,
            f"""
            SELECT id
            FROM {SCHEMA}.database_targets
            WHERE is_active = true
            ORDER BY is_default DESC, id ASC;
            """,
        )
    return [int(row["id"]) for row in rows]


def _collect_and_analyze_one_unlocked(target_id: int | None) -> TargetRunResult:
    run_id = None
    try:
        target = get_target_row(target_id)
        adapter = get_adapter(target.get("engine") if target else "postgres")

        run_id = adapter.collect(target_id=target_id)
        logger.info("Collect finished. engine=%s target_id=%s run_id=%s", adapter.engine, target_id, run_id)

        stored = adapter.analyze_latest_run(target_id=target_id)
        logger.info("Analyze finished. engine=%s target_id=%s recommendations_stored=%s", adapter.engine, target_id, stored)

        return TargetRunResult(
            target_id=int(target_id) if target_id is not None else -1,
            ok=True,
            run_id=str(run_id),
            recommendations_stored=int(stored),
        )
    except Exception as exc:
        logger.exception("Collect/analyze failed for target_id=%s", target_id)
        return TargetRunResult(
            target_id=int(target_id) if target_id is not None else -1,
            ok=False,
            run_id=str(run_id) if run_id else None,
            error=str(exc),
        )


def run_collect_and_analyze(target_id: int | None = None) -> None:
    """Background task for manual collect + analyze API actions."""
    if not _run_lock.acquire(blocking=False):
        logger.warning(
            "Manual collect/analyze skipped because another collect/analyze job is already running. target_id=%s",
            target_id,
        )
        return

    try:
        result = _collect_and_analyze_one_unlocked(target_id)
        if result.ok:
            retention = apply_storage_retention(force=True)
            logger.info("Storage retention finished after manual run. %s", retention.as_dict())
        else:
            logger.error("Manual collect/analyze failed. %s", result.as_dict())
    finally:
        _run_lock.release()


def run_collect_and_analyze_for_all_active_targets(*, source: str = "scheduled") -> ScheduledRunSummary:
    """Run collect+analyze for every active target, sequentially.

    This is used by the twice-daily scheduler. It intentionally runs targets one
    at a time to avoid overloading the target PostgreSQL host or storage DB.
    """
    started_at = _utc_now_iso()

    if not has_storage_config():
        logger.info("%s collect/analyze skipped because storage is not configured yet.", source)
        return ScheduledRunSummary(
            source=source,
            started_at=started_at,
            finished_at=_utc_now_iso(),
            attempted_targets=0,
            successful_targets=0,
            failed_targets=0,
            skipped=True,
            skip_reason="storage_not_configured",
            results=[],
        )

    if not _run_lock.acquire(blocking=False):
        logger.warning("%s collect/analyze skipped because another collect/analyze job is already running.", source)
        return ScheduledRunSummary(
            source=source,
            started_at=started_at,
            finished_at=_utc_now_iso(),
            attempted_targets=0,
            successful_targets=0,
            failed_targets=0,
            skipped=True,
            skip_reason="job_already_running",
            results=[],
        )

    try:
        target_ids = list_active_target_ids()
        if not target_ids:
            logger.info("%s collect/analyze skipped because there are no active targets.", source)
            return ScheduledRunSummary(
                source=source,
                started_at=started_at,
                finished_at=_utc_now_iso(),
                attempted_targets=0,
                successful_targets=0,
                failed_targets=0,
                skipped=True,
                skip_reason="no_active_targets",
                results=[],
            )

        logger.info("%s collect/analyze started for active targets: %s", source, target_ids)
        results: list[TargetRunResult] = []
        for target_id in target_ids:
            results.append(_collect_and_analyze_one_unlocked(target_id))

        retention = apply_storage_retention(force=True)
        logger.info("Storage retention finished after %s run. %s", source, retention.as_dict())

        successful = sum(1 for r in results if r.ok)
        failed = len(results) - successful
        summary = ScheduledRunSummary(
            source=source,
            started_at=started_at,
            finished_at=_utc_now_iso(),
            attempted_targets=len(results),
            successful_targets=successful,
            failed_targets=failed,
            skipped=False,
            skip_reason=None,
            results=results,
        )
        logger.info("%s collect/analyze finished. %s", source, summary.as_dict())
        return summary
    finally:
        _run_lock.release()
