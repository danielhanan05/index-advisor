"""Consistent API error helpers and exception handlers."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def error_detail(
    *,
    title: str,
    message: str,
    error_type: str = "API_ERROR",
    details: Any | None = None,
    action_items: list[str] | None = None,
    context: dict[str, Any] | None = None,
    raw_error: str | None = None,
) -> dict[str, Any]:
    """Return the single structured error shape used by the backend.

    The frontend expects these keys when rendering API error dialogs.  Keep this
    as the only backend error-detail builder to avoid slightly different error
    shapes across routers/services.
    """
    return {
        "error_type": error_type,
        "title": title,
        "message": message,
        "details": details or "",
        "action_items": action_items or [],
        "context": context or {},
        "raw_error": raw_error or (str(details) if details else message),
    }


def api_error(
    status_code: int,
    *,
    title: str,
    message: str,
    error_type: str = "API_ERROR",
    details: Any | None = None,
    action_items: list[str] | None = None,
    context: dict[str, Any] | None = None,
    raw_error: str | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=error_detail(
            title=title,
            message=message,
            error_type=error_type,
            details=details,
            action_items=action_items,
            context=context,
            raw_error=raw_error,
        ),
    )


def _looks_like_connection_timeout(raw: str) -> bool:
    lower = raw.lower()
    timeout_markers = [
        "timeout",
        "timed out",
        "connection attempt failed",
        "could not connect to server",
        "no route to host",
        "network is unreachable",
        "host is unreachable",
        "operation timed out",
        "server closed the connection unexpectedly",
    ]
    return any(marker in lower for marker in timeout_markers)


def database_timeout_error_detail(*, raw: str, storage: bool = False) -> dict[str, Any]:
    subject = "storage" if storage else "target"
    return error_detail(
        error_type="STORAGE_CONNECTION_TIMEOUT" if storage else "TARGET_CONNECTION_TIMEOUT",
        title="Storage connection timed out" if storage else "Target connection timed out",
        message=f"The app could not connect to the {subject} PostgreSQL database within 15 seconds.",
        details=raw,
        action_items=[
            "Verify the PostgreSQL service is running.",
            "Check that the host and port are correct and reachable from this machine.",
            "Check firewall, Docker, VM, VPN, or network routing rules between the app and PostgreSQL.",
            "Verify PostgreSQL is listening on the expected address and port.",
            "Verify pg_hba.conf allows this client/user to connect.",
            "Check SSL mode if the server requires or rejects SSL connections.",
        ],
        raw_error=raw,
        context={"timeout_seconds": 15},
    )


def storage_bootstrap_error_detail(exc: BaseException) -> dict[str, Any]:
    raw = str(exc)
    lower = raw.lower()

    if "pg_partman" in lower or "partman" in lower:
        return error_detail(
            error_type="STORAGE_PARTMAN_EXTENSION_ERROR",
            title="Storage setup failed: pg_partman is missing",
            message=(
                "The app could connect to PostgreSQL and create storage_db, but the storage schema migration "
                "requires pg_partman and PostgreSQL says that extension is not installed/available on the server."
            ),
            details=raw,
            action_items=[
                "Install the pg_partman package/extension on the PostgreSQL server OS.",
                "Add pg_partman_bgw to shared_preload_libraries if automatic retention/background maintenance is required.",
                "Restart PostgreSQL after changing shared_preload_libraries.",
                "Run the setup again after PostgreSQL restarts.",
            ],
            raw_error=raw,
        )

    if "permission denied" in lower or "createdb" in lower or "create database" in lower:
        return error_detail(
            error_type="STORAGE_PERMISSION_ERROR",
            title="Storage setup failed: database permission problem",
            message=(
                "The app could not create/configure storage_db on the same PostgreSQL host. "
                "The supplied user may be missing CREATEDB or required schema/extension permissions."
            ),
            details=raw,
            action_items=[
                "Verify the PostgreSQL user can connect to the maintenance database, usually postgres.",
                "Grant CREATEDB to the user or create storage_db manually and configure the app to use it.",
                "Verify the user can create schemas, tables, and required extensions inside storage_db.",
            ],
            raw_error=raw,
        )

    if _looks_like_connection_timeout(raw):
        return database_timeout_error_detail(raw=raw, storage=True)

    if "could not translate host" in lower or "connection refused" in lower or "password authentication failed" in lower:
        return error_detail(
            error_type="STORAGE_CONNECTION_ERROR",
            title="Storage setup failed: connection problem",
            message="The app could not connect to PostgreSQL using the supplied host, port, username, password, or SSL mode.",
            details=raw,
            action_items=[
                "Check host, port, username, password, database name, and SSL mode.",
                "Verify PostgreSQL is reachable from this machine.",
                "Verify pg_hba.conf allows this client/user to connect.",
            ],
            raw_error=raw,
        )

    return error_detail(
        error_type="STORAGE_BOOTSTRAP_ERROR",
        title="Storage setup failed",
        message=(
            "The app could not finish configuring storage_db. The database may have been created, "
            "but the schema was not fully migrated."
        ),
        details=raw,
        action_items=[
            "Read the details below and fix the PostgreSQL-side issue.",
            "Run setup again after the database/server issue is fixed.",
        ],
        raw_error=raw,
    )


def connection_test_error_detail(exc: BaseException) -> dict[str, Any]:
    raw = str(exc)
    if _looks_like_connection_timeout(raw):
        return database_timeout_error_detail(raw=raw, storage=False)

    return error_detail(
        error_type="TARGET_CONNECTION_ERROR",
        title="Target connection failed",
        message="The app could not connect to the target PostgreSQL database with the supplied details.",
        details=raw,
        action_items=[
            "Check host, port, database name, username, password, and SSL mode.",
            "Verify the PostgreSQL server is reachable from this machine.",
            "Verify PostgreSQL is listening on the expected address and port.",
            "Check firewall, Docker, VM, VPN, or network routing rules.",
            "Verify pg_hba.conf allows this client/user to connect.",
        ],
        raw_error=raw,
    )


def _normalize_detail(status_code: int, detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict) and "message" in detail:
        return detail
    if isinstance(detail, str):
        return error_detail(
            title=f"HTTP {status_code}",
            message=detail,
            error_type="HTTP_ERROR",
            details=detail,
        )
    return error_detail(
        title=f"HTTP {status_code}",
        message="Request failed",
        error_type="HTTP_ERROR",
        details=detail,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": _normalize_detail(exc.status_code, exc.detail)})


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": error_detail(
                title="Validation failed",
                message="The request body or query parameters are invalid.",
                error_type="VALIDATION_ERROR",
                details=exc.errors(),
                action_items=["Check the highlighted fields and send the request again."],
            )
        },
    )
