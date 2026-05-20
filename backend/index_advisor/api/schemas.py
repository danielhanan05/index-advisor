"""
Pydantic request models for the FastAPI API.

These models are kept outside router files so validation rules remain shared
and api/main.py can stay focused on app setup only.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class RevalidateRequest(BaseModel):
    bind_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Placeholder values, for example {'$1': 12345, '$2': 'OPEN'} or {'?1': 123}",
    )


class ApplyIndexRequest(BaseModel):
    confirm: str = Field(description="Must be APPLY")


class DatabaseTargetRequest(BaseModel):
    engine: str = Field(default="postgres", description="Database engine. Supported now: postgres. Roadmap: mssql, oracle")
    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: str | None = None
    sslmode: str = "prefer"
    is_default: bool = False

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, value: str) -> str:
        normalized = (value or "postgres").strip().lower()
        if normalized not in {"postgres", "mssql", "oracle"}:
            raise ValueError("engine must be one of: postgres, mssql, oracle")
        return normalized


class DatabaseTargetUpdateRequest(BaseModel):
    engine: str | None = None
    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = None
    username: str | None = None
    password: str | None = None
    sslmode: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None

    @field_validator("engine")
    @classmethod
    def validate_engine(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"postgres", "mssql", "oracle"}:
            raise ValueError("engine must be one of: postgres, mssql, oracle")
        return normalized


class ProductSettingsUpdateRequest(BaseModel):
    scheduler_enabled: bool | None = None
    scheduler_run_times: list[str] | None = Field(default=None, description="Scheduled run times in HH:MM format")
    storage_retention_days: int | None = Field(default=None, ge=1, le=365)

# Generic response models. Exact row payloads are intentionally flexible because
# recommendations/stat rows include JSON, numeric, timestamp, and engine-specific
# metadata, but the top-level API shape is now consistent and documented.
class ItemListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    limit: int | None = None
    offset: int | None = None


class StatusResponse(BaseModel):
    status: str
    id: int | None = None
    message: str | None = None
    target_id: str | None = None


class TargetCreateResponse(BaseModel):
    id: int
    setup_status: str
    extension_status: dict[str, Any] = Field(default_factory=dict)
    connection_error: str | None = None
    connection_error_detail: dict[str, Any] | None = None
    storage_bootstrapped: bool = False
    target_existed: bool = False


class TargetCheckResponse(BaseModel):
    ok: bool
    version: str | None = None
    error: str | None = None
    error_detail: dict[str, Any] | None = None


class TargetExtensionCheckResponse(BaseModel):
    target_id: int
    setup_status: str
    extension_status: dict[str, Any] = Field(default_factory=dict)


class RunDetailResponse(BaseModel):
    run: dict[str, Any]
    counts: dict[str, int]


class RecommendationApplyResponse(BaseModel):
    status: str
    recommendation_id: int
    executed_sql: str


class RecommendationRevalidateResponse(BaseModel):
    recommendation_id: int
    validation_id: int
    validation_type: str
    validated: bool
    query_text: str
    bind_values: dict[str, Any]
    original_cost: float | None = None
    hypothetical_cost: float | None = None
    improvement_pct: float | None = None
    original_plan_json: Any | None = None
    hypothetical_plan_json: Any | None = None
    recommended_index_sql: str
    warning: str | None = None
