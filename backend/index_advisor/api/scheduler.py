"""In-process scheduler for automatic collect + analyze jobs.

The scheduler has no external dependencies and reads its schedule from the
storage DB app_settings table. This lets users edit run times from the UI
without editing environment variables or restarting the backend.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from index_advisor.api.jobs import run_collect_and_analyze_for_all_active_targets
from index_advisor.storage.settings import get_product_settings, validate_scheduler_run_times

logger = logging.getLogger(__name__)


@dataclass
class SchedulerRuntimeState:
    running: bool = False
    next_run_at: datetime | None = None
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_success: bool | None = None
    last_error: str | None = None
    last_summary: dict[str, Any] | None = None
    last_run_slot: str | None = None


@dataclass(frozen=True)
class SchedulerStatus:
    enabled: bool
    run_times: list[str]
    next_run_at: str | None
    running: bool
    last_started_at: str | None
    last_finished_at: str | None
    last_success: bool | None
    last_error: str | None
    last_summary: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "run_times": self.run_times,
            "next_run_at": self.next_run_at,
            "running": self.running,
            "last_started_at": self.last_started_at,
            "last_finished_at": self.last_finished_at,
            "last_success": self.last_success,
            "last_error": self.last_error,
            "last_summary": self.last_summary,
        }


_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_state = SchedulerRuntimeState()
_state_lock = threading.RLock()


def _parse_run_times(labels: list[str]) -> list[time]:
    normalized = validate_scheduler_run_times(labels)
    out: list[time] = []
    for token in normalized:
        hour_text, minute_text = token.split(":", 1)
        out.append(time(hour=int(hour_text), minute=int(minute_text)))
    return out


def configured_run_times() -> list[time]:
    settings = get_product_settings()
    return _parse_run_times(settings.scheduler_run_times)


def _time_label(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _next_run_after(now: datetime, run_times: list[time]) -> datetime | None:
    if not run_times:
        return None
    candidates = [now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0) for t in run_times]
    future_today = [candidate for candidate in candidates if candidate > now]
    if future_today:
        return min(future_today)
    return candidates[0] + timedelta(days=1)


def _set_state(**updates: Any) -> None:
    with _state_lock:
        for key, value in updates.items():
            setattr(_state, key, value)


def _snapshot_state() -> SchedulerRuntimeState:
    with _state_lock:
        return SchedulerRuntimeState(**vars(_state))


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float = 30.0) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def _run_scheduler_loop(stop_event: asyncio.Event) -> None:
    logger.info("Automatic collect/analyze scheduler started. Settings are loaded from storage DB when available.")

    while not stop_event.is_set():
        try:
            settings = get_product_settings()
            run_times = _parse_run_times(settings.scheduler_run_times)
            run_time_labels = [_time_label(t) for t in run_times]
            now = datetime.now().astimezone()
            _set_state(next_run_at=_next_run_after(now, run_times) if settings.scheduler_enabled else None)

            if not settings.scheduler_enabled:
                await _sleep_or_stop(stop_event, 30.0)
                continue

            current_label = f"{now.hour:02d}:{now.minute:02d}"
            current_slot = f"{now.date().isoformat()} {current_label}"

            with _state_lock:
                should_run = current_label in run_time_labels and _state.last_run_slot != current_slot
                if should_run:
                    _state.last_run_slot = current_slot
                    _state.running = True
                    _state.last_started_at = now.isoformat(timespec="seconds")
                    _state.last_error = None

            if should_run:
                logger.info("Automatic collect/analyze triggered by scheduler. slot=%s", current_slot)
                summary = await asyncio.to_thread(run_collect_and_analyze_for_all_active_targets, source="scheduled")
                summary_dict = summary.as_dict()
                _set_state(
                    last_summary=summary_dict,
                    last_success=not summary.failed_targets and not summary.skipped,
                    last_finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                )
                logger.info("Automatic collect/analyze scheduler cycle finished. %s", summary_dict)

            # Poll often enough that UI setting changes take effect without a restart.
            stopped = await _sleep_or_stop(stop_event, 30.0)
            if stopped:
                break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _set_state(
                last_success=False,
                last_error=str(exc),
                last_finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            logger.exception("Automatic collect/analyze scheduler cycle failed.")
            await _sleep_or_stop(stop_event, 30.0)
        finally:
            _set_state(running=False)


async def start_scheduler() -> None:
    """Start the scheduler once for this FastAPI process."""
    global _task, _stop_event
    if _task and not _task.done():
        return

    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_run_scheduler_loop(_stop_event), name="index-advisor-scheduler")


async def stop_scheduler() -> None:
    """Stop the scheduler cleanly during FastAPI shutdown."""
    global _task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    _stop_event = None


def scheduler_status() -> dict[str, Any]:
    settings = get_product_settings()
    try:
        times = [_time_label(t) for t in configured_run_times()]
    except Exception:
        times = []

    state = _snapshot_state()
    return SchedulerStatus(
        enabled=bool(settings.scheduler_enabled),
        run_times=times,
        next_run_at=state.next_run_at.isoformat(timespec="seconds") if state.next_run_at else None,
        running=state.running,
        last_started_at=state.last_started_at,
        last_finished_at=state.last_finished_at,
        last_success=state.last_success,
        last_error=state.last_error,
        last_summary=state.last_summary,
    ).as_dict()
