"""Engine adapter registry.

PostgreSQL is the only production-ready engine today. MSSQL and Oracle are
intentionally exposed as roadmap metadata for the UI, but their adapters are not
registered until their collectors/analyzers exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from index_advisor.targets.base import DatabaseEngineAdapter
from index_advisor.targets.postgres.adapter import PostgresAdapter


@dataclass(frozen=True)
class EngineMetadata:
    engine: str
    display_name: str
    default_port: int
    status: str
    description: str


_ADAPTERS: dict[str, DatabaseEngineAdapter] = {
    "postgres": PostgresAdapter(),
}

_ENGINE_METADATA: list[EngineMetadata] = [
    EngineMetadata(
        engine="postgres",
        display_name="PostgreSQL",
        default_port=5432,
        status="available",
        description="Fully supported in this version using pg_stat_statements + HypoPG.",
    ),
    EngineMetadata(
        engine="mssql",
        display_name="Microsoft SQL Server",
        default_port=1433,
        status="coming_soon",
        description="Planned future support. UI placeholder only for now.",
    ),
    EngineMetadata(
        engine="oracle",
        display_name="Oracle Database",
        default_port=1521,
        status="coming_soon",
        description="Planned future support. UI placeholder only for now.",
    ),
]


def normalize_engine(engine: str | None) -> str:
    return (engine or "postgres").strip().lower()


def get_adapter(engine: str | None) -> DatabaseEngineAdapter:
    normalized = normalize_engine(engine)
    try:
        return _ADAPTERS[normalized]
    except KeyError as exc:
        raise NotImplementedError(f"Database engine '{normalized}' is not supported yet.") from exc


def list_supported_engines() -> list[dict[str, object]]:
    return [m.__dict__.copy() for m in _ENGINE_METADATA]


def is_engine_supported(engine: str | None) -> bool:
    return normalize_engine(engine) in _ADAPTERS
