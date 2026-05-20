"""Storage-backed product settings.

These settings are editable from the frontend and stored in the storage DB so
end users don't need to edit environment variables. Environment variables are
used only as defaults/fallbacks before storage is configured.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

SCHEMA = "index_advisor"
from index_advisor.config import load_config
from index_advisor.db import get_storage_connection, has_storage_config

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

DEFAULT_SCHEDULER_ENABLED = True
DEFAULT_SCHEDULER_RUN_TIMES = ["06:00", "20:00"]
DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365


@dataclass(frozen=True)
class ProductSettings:
    scheduler_enabled: bool
    scheduler_run_times: list[str]
    storage_retention_days: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "scheduler_enabled": self.scheduler_enabled,
            "scheduler_run_times": self.scheduler_run_times,
            "storage_retention_days": self.storage_retention_days,
            "source": self.source,
            "limits": {
                "storage_retention_days_min": MIN_RETENTION_DAYS,
                "storage_retention_days_max": MAX_RETENTION_DAYS,
            },
        }


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def validate_scheduler_run_times(run_times: list[str]) -> list[str]:
    if not isinstance(run_times, list):
        raise ValueError("scheduler_run_times must be a list of HH:MM values")

    normalized: list[str] = []
    for value in run_times:
        token = str(value).strip()
        if not _TIME_RE.match(token):
            raise ValueError(f"Invalid scheduler time '{value}'. Expected HH:MM in 24-hour format, for example 06:00.")
        if token not in normalized:
            normalized.append(token)

    if not normalized:
        raise ValueError("At least one scheduler run time is required")

    return sorted(normalized)


def validate_retention_days(days: int) -> int:
    try:
        value = int(days)
    except Exception as exc:
        raise ValueError("storage_retention_days must be a number") from exc

    if value < MIN_RETENTION_DAYS or value > MAX_RETENTION_DAYS:
        raise ValueError(f"storage_retention_days must be between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS}")
    return value


def _defaults_from_env() -> ProductSettings:
    cfg = load_config()
    try:
        run_times = validate_scheduler_run_times([p.strip() for p in cfg.scheduler_run_times.split(",") if p.strip()])
    except Exception:
        run_times = DEFAULT_SCHEDULER_RUN_TIMES

    try:
        retention_days = validate_retention_days(cfg.storage_retention_days)
    except Exception:
        retention_days = DEFAULT_RETENTION_DAYS

    return ProductSettings(
        scheduler_enabled=bool(cfg.scheduler_enabled),
        scheduler_run_times=run_times,
        storage_retention_days=retention_days,
        source="environment_or_defaults",
    )


def _unwrap_setting_value(value: Any, default: Any) -> Any:
    # Some older app_settings values use an object shape like {"complete": true}.
    # Product settings use raw JSON values, but this also supports {"value": x}
    # for future compatibility.
    if value is None:
        return default
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def get_product_settings() -> ProductSettings:
    """Return effective settings.

    Priority:
      1. storage DB app_settings rows, when storage is configured
      2. environment variables
      3. code defaults
    """
    defaults = _defaults_from_env()
    if not has_storage_config():
        return defaults

    try:
        with get_storage_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT key, value
                    FROM {SCHEMA}.app_settings
                    WHERE key IN ('scheduler_enabled', 'scheduler_run_times', 'storage_retention_days');
                    """
                )
                rows = cur.fetchall()
    except Exception:
        # During first-time bootstrap or a partially migrated DB, keep the app
        # responsive by falling back to env/default settings.
        return defaults

    values = {row["key"]: row["value"] for row in rows}

    scheduler_enabled = bool(_unwrap_setting_value(values.get("scheduler_enabled"), defaults.scheduler_enabled))
    scheduler_run_times = validate_scheduler_run_times(
        list(_unwrap_setting_value(values.get("scheduler_run_times"), defaults.scheduler_run_times))
    )
    storage_retention_days = validate_retention_days(
        int(_unwrap_setting_value(values.get("storage_retention_days"), defaults.storage_retention_days))
    )

    return ProductSettings(
        scheduler_enabled=scheduler_enabled,
        scheduler_run_times=scheduler_run_times,
        storage_retention_days=storage_retention_days,
        source="storage_db",
    )


def update_product_settings(
    *,
    scheduler_enabled: bool | None = None,
    scheduler_run_times: list[str] | None = None,
    storage_retention_days: int | None = None,
) -> ProductSettings:
    """Validate and persist product settings to storage DB app_settings."""
    if not has_storage_config():
        raise RuntimeError("Storage is not configured yet. Complete setup before editing product settings.")

    current = get_product_settings()
    next_enabled = current.scheduler_enabled if scheduler_enabled is None else bool(scheduler_enabled)
    next_times = current.scheduler_run_times if scheduler_run_times is None else validate_scheduler_run_times(scheduler_run_times)
    next_days = current.storage_retention_days if storage_retention_days is None else validate_retention_days(storage_retention_days)

    rows = {
        "scheduler_enabled": next_enabled,
        "scheduler_run_times": next_times,
        "storage_retention_days": next_days,
    }

    with get_storage_connection() as conn:
        with conn.cursor() as cur:
            for key, value in rows.items():
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.app_settings(key, value, updated_at)
                    VALUES (%s, %s::jsonb, now())
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = now();
                    """,
                    (key, json.dumps(value)),
                )
        conn.commit()

    return get_product_settings()
