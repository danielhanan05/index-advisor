"""Connection-string helpers shared by API and service layers."""
from __future__ import annotations

from typing import Any

from index_advisor.db import target_conninfo_from_details
from index_advisor.security.credentials import decrypt_secret


def target_conninfo_from_request_body(body: Any) -> str:
    """Build a psycopg conninfo string from a Pydantic model or stored target row.

    This helper intentionally lives outside the FastAPI API layer so services can
    build target connections without importing from ``index_advisor.api``.
    """
    data = body if isinstance(body, dict) else body.model_dump(exclude_unset=True)
    return target_conninfo_from_details(
        host=str(data["host"]),
        port=int(data.get("port") or 5432),
        database_name=str(data["database_name"]),
        username=str(data["username"]),
        password=decrypt_secret(data.get("password")),
        sslmode=str(data.get("sslmode") or "prefer"),
    )
