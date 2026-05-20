"""Local admin authentication for dangerous write endpoints.

The product is designed as a local installer/desktop-style app.  On first start,
the backend generates a local admin token in the per-user runtime config directory. The React
frontend obtains an HttpOnly same-site cookie through /auth/local-session and
all dangerous endpoints require that token either from the cookie or from the
X-Index-Advisor-Token header.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response

from index_advisor.api.errors import api_error
from index_advisor.config import local_config_dir

_ADMIN_TOKEN_FILE = "admin_token.env"
_ADMIN_COOKIE = "index_advisor_admin_token"
_ADMIN_HEADER = "X-Index-Advisor-Token"

router = APIRouter(prefix="/auth", tags=["auth"])


def admin_token_path() -> Path:
    return local_config_dir() / _ADMIN_TOKEN_FILE


def load_or_create_admin_token() -> str:
    path = admin_token_path()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("INDEX_ADVISOR_ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(
        "# Created by Database Index Advisor. Keep this local file private.\n"
        "# Dangerous API endpoints require this token.\n"
        f'INDEX_ADVISOR_ADMIN_TOKEN="{token}"\n',
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _is_local_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return client_host in {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1", "0:0:0:0:0:0:0:1"}


@router.post("/local-session")
def create_local_session(request: Request, response: Response) -> dict[str, object]:
    if not _is_local_request(request):
        raise api_error(
            403,
            title="Local authentication only",
            message="Admin session bootstrap is only allowed from the local machine.",
            error_type="LOCAL_AUTH_REQUIRED",
            action_items=["Open the product UI on the same computer that runs the backend."],
        )

    token = load_or_create_admin_token()
    response.set_cookie(
        key=_ADMIN_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return {"authenticated": True, "auth_mode": "local_admin_cookie"}


def require_admin_token(
    request: Request,
    x_index_advisor_token: str | None = Header(default=None, alias=_ADMIN_HEADER),
    admin_cookie: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
) -> None:
    expected = load_or_create_admin_token()
    provided = x_index_advisor_token or admin_cookie
    if not provided or not secrets.compare_digest(provided, expected):
        raise api_error(
            401,
            title="Admin authorization required",
            message="This action can change database targets, settings, or indexes and requires the local admin token.",
            error_type="ADMIN_AUTH_REQUIRED",
            action_items=[
                "Open the frontend from the same local machine as the backend.",
                "Refresh the page so the frontend can create a local admin session.",
                "For scripts, send the X-Index-Advisor-Token header from the admin_token.env file in the local config directory.",
            ],
        )


AdminRequired = Depends(require_admin_token)
