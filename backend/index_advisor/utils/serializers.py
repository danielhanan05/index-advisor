"""JSON-serialization helpers for psycopg/Postgres row data.

Moved here from api/serializers.py so that service-layer modules can import
these utilities without taking a dependency on the API layer.

``api/serializers.py`` is kept as a re-export shim so existing import sites
continue to work without modification during the migration.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convert psycopg/Postgres values into JSON-safe Python values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: to_jsonable(v) for k, v in dict(row).items()}


def rows_to_list(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row_to_dict(row) or {} for row in rows]
