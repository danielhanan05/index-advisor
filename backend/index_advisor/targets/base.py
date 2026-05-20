"""Common interface for database-engine specific index advisors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    version: str | None = None
    error: str | None = None
    error_detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class RequirementCheckResult:
    ok: bool
    setup_status: str
    details: dict[str, Any] = field(default_factory=dict)


class DatabaseEngineAdapter(ABC):
    """Contract every supported database engine must implement."""

    engine: str
    display_name: str
    default_port: int
    supports_recommendations: bool = True

    @abstractmethod
    def test_connection(self, conninfo: str) -> ConnectionTestResult:
        """Check whether the target connection works."""

    @abstractmethod
    def check_requirements(self, conninfo: str, *, attempt_create: bool = True) -> RequirementCheckResult:
        """Check engine-specific prerequisites needed for collection/analysis."""

    @abstractmethod
    def collect(self, *, target_id: int | None = None) -> str:
        """Collect workload/statistics data for a target and return the collection run id."""

    @abstractmethod
    def analyze_latest_run(self, *, target_id: int | None = None) -> int:
        """Analyze the latest completed collection run for a target."""
