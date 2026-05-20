"""PostgreSQL implementation of the database-engine adapter."""
from __future__ import annotations

from typing import Any

from index_advisor.api.errors import connection_test_error_detail
from index_advisor.db import connect_with_timeout, extension_status_for_conninfo
from index_advisor.targets.base import ConnectionTestResult, DatabaseEngineAdapter, RequirementCheckResult
from index_advisor.targets.postgres.analyzer.analyzer import analyze_latest_run
from index_advisor.targets.postgres.collector.collector import collect


class PostgresAdapter(DatabaseEngineAdapter):
    engine = "postgres"
    display_name = "PostgreSQL"
    default_port = 5432
    supports_recommendations = True

    def test_connection(self, conninfo: str) -> ConnectionTestResult:
        try:
            with connect_with_timeout(conninfo, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version() AS version;")
                    row = cur.fetchone()
            return ConnectionTestResult(ok=True, version=row[0] if row else None)
        except Exception as exc:
            return ConnectionTestResult(ok=False, error=str(exc), error_detail=connection_test_error_detail(exc))

    def check_requirements(self, conninfo: str, *, attempt_create: bool = True) -> RequirementCheckResult:
        status: dict[str, Any] = extension_status_for_conninfo(
            conninfo,
            attempt_create=attempt_create,
            require_hypopg=True,
        )
        return RequirementCheckResult(
            ok=bool(status.get("ok")),
            setup_status="READY" if status.get("ok") else "NEEDS_ATTENTION",
            details=status,
        )

    def collect(self, *, target_id: int | None = None) -> str:
        return str(collect(target_id=target_id))

    def analyze_latest_run(self, *, target_id: int | None = None) -> int:
        return int(analyze_latest_run(target_id=target_id))
