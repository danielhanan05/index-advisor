"""Setup/status business logic for the local product installation."""
from __future__ import annotations

from index_advisor.api.errors import storage_bootstrap_error_detail
from index_advisor.api.serializers import row_to_dict, rows_to_list
from index_advisor.config import load_config
from index_advisor.db import get_storage_connection, has_storage_config
from index_advisor.storage.migrations import apply_storage_migrations
from index_advisor.storage.repositories import targets as target_repo
from index_advisor.storage.retention import apply_storage_retention
from index_advisor.storage.settings import get_product_settings


def _retention_pending(message: str) -> dict[str, object]:
    return {
        "enabled": True,
        "retention_days": get_product_settings().storage_retention_days,
        "message": message,
    }


def get_setup_status() -> dict[str, object]:
    cfg = load_config()
    if not has_storage_config():
        return {
            "setup_complete": False,
            "storage_configured": False,
            "storage_database_name": cfg.storage_database_name,
            "storage_source": "frontend_setup_required",
            "target_count": 0,
            "default_target": None,
            "targets": [],
            "storage_error": None,
            "retention": _retention_pending("Retention will start after storage is configured."),
        }

    # If storage exists but the previous bootstrap failed halfway, try to finish
    # migrations again. If they still fail, return a clean setup response instead
    # of crashing /setup/status with UndefinedTable.
    try:
        apply_storage_migrations()
        apply_storage_retention(force=True)
    except Exception as exc:
        return {
            "setup_complete": False,
            "storage_configured": True,
            "storage_database_name": cfg.storage_database_name,
            "storage_source": "frontend_setup_required",
            "target_count": 0,
            "default_target": None,
            "targets": [],
            "storage_error": storage_bootstrap_error_detail(exc),
            "retention": _retention_pending("Retention could not run because storage bootstrap failed."),
        }

    try:
        with get_storage_connection() as conn:
            targets = target_repo.list_targets(conn)
            complete = target_repo.setup_complete(conn)
            target_repo.set_setup_complete(conn, complete)
            conn.commit()
    except Exception as exc:
        return {
            "setup_complete": False,
            "storage_configured": True,
            "storage_database_name": cfg.storage_database_name,
            "storage_source": "frontend_setup_required",
            "target_count": 0,
            "default_target": None,
            "targets": [],
            "storage_error": storage_bootstrap_error_detail(exc),
            "retention": _retention_pending("Retention could not run because setup status query failed."),
        }

    return {
        "setup_complete": complete,
        "storage_configured": True,
        "storage_database_name": cfg.storage_database_name,
        "storage_source": "runtime_or_env",
        "target_count": len(targets),
        "default_target": row_to_dict(targets[0]) if targets else None,
        "targets": rows_to_list(targets),
        "storage_error": None,
        "retention": apply_storage_retention(force=False).as_dict(),
    }
