from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


DEFAULT_STORAGE_DATABASE_NAME = "storage_db"
DEFAULT_STORAGE_MAINTENANCE_DB = "postgres"

# Runtime storage connection configured by the frontend setup flow during the
# current backend process. After successful setup, the same value is also saved
# to the local user config directory so restarts remember the storage DB.
_runtime_storage_database_url: str | None = None


def project_root() -> Path:
    """Return the repository/project root directory."""
    return Path(__file__).resolve().parents[2]


def local_config_dir() -> Path:
    """Return the per-user runtime config directory.

    Production/client installs must not write secrets into the application
    directory, because that directory may be read-only, shared by multiple users,
    or replaced during updates.

    Development override:
    - Set INDEX_ADVISOR_CONFIG_DIR=./config if you want the old project-local
      behavior while developing.

    Defaults:
    - Windows: %APPDATA%/IndexAdvisor
    - Linux/macOS: $XDG_CONFIG_HOME/index-advisor or ~/.config/index-advisor
    """
    override = os.getenv("INDEX_ADVISOR_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = os.getenv("APPDATA")
        if base:
            return Path(base) / "IndexAdvisor"
        return Path.home() / "AppData" / "Roaming" / "IndexAdvisor"

    base = os.getenv("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "index-advisor"
    return Path.home() / ".config" / "index-advisor"


def local_storage_env_path() -> Path:
    return local_config_dir() / "storage.env"


def local_credential_key_path() -> Path:
    return local_config_dir() / "credential.key"


def _encrypt_storage_url(value: str) -> str:
    """Encrypt a storage URL for persistence in the local storage.env file.

    Delegates key management to security.credentials so there is exactly one
    Fernet key-loading path in the entire codebase.  The result is a raw Fernet
    token (no ``enc:v1:`` prefix) because storage.env is a separate file-level
    secret that does not share the prefix convention used for DB-stored passwords.
    """
    from index_advisor.security.credentials import _fernet
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_storage_url(value: str) -> str:
    """Decrypt a storage URL read from the local storage.env file.

    Uses the same Fernet instance as security.credentials so that the key file
    is loaded exactly once regardless of which module calls it first.
    """
    from index_advisor.security.credentials import _fernet
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def _load_local_storage_database_url() -> str | None:
    """Read the encrypted storage connection from the local user config dir."""
    path = local_storage_env_path()
    if not path.exists():
        return None
    values = dotenv_values(path)
    encrypted_value = values.get("STORAGE_DATABASE_URL_ENCRYPTED")
    if encrypted_value:
        return _decrypt_storage_url(str(encrypted_value).strip())

    # Backward compatibility for installations created before local config
    # encryption existed. The next successful setup save will write the
    # encrypted form instead.
    value = values.get("STORAGE_DATABASE_URL")
    return str(value).strip() if value else None


def save_local_storage_database_url(storage_database_url: str) -> Path:
    """Persist the storage connection to the local user config directory.

    Environment variable STORAGE_DATABASE_URL still has priority over this file.
    This file is created by the frontend setup flow so normal users do not need
    to set environment variables manually and the backend can reconnect after a
    restart.
    """
    path = local_storage_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted_url = _encrypt_storage_url(storage_database_url)
    path.write_text(
        "# Created by Database Index Advisor first-time setup.\n"
        "# Contains encrypted database credentials. Do not commit or share this file.\n"
        "# STORAGE_DATABASE_URL from the OS environment overrides this value.\n"
        f"# Runtime config directory: {local_config_dir()}\n"
        "# The decryption key is stored locally beside this file as credential.key.\n"
        f'STORAGE_DATABASE_URL_ENCRYPTED="{encrypted_url}"\n',
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        # Windows may ignore POSIX file modes; the file still remains inside
        # the per-user runtime config directory.
        pass
    reset_config()
    return path


def set_runtime_storage_database_url(storage_database_url: str) -> None:
    """Set storage DB conninfo for the current backend process."""
    global _runtime_storage_database_url
    _runtime_storage_database_url = storage_database_url
    reset_config()


def clear_runtime_storage_database_url() -> None:
    global _runtime_storage_database_url
    _runtime_storage_database_url = None
    reset_config()


@dataclass(frozen=True)
class AppConfig:
    target_database_url: str | None
    storage_database_url: str | None
    storage_database_name: str = DEFAULT_STORAGE_DATABASE_NAME
    storage_maintenance_db: str = DEFAULT_STORAGE_MAINTENANCE_DB

    top_query_limit: int = 50
    analyze_query_limit: int = 25
    min_cost_improvement_pct: float = 20.0
    min_recommendation_improvement_pct: float = 10.0
    max_write_ratio_for_index: float = 0.4
    storage_retention_days: int = 30
    scheduler_enabled: bool = True
    scheduler_run_times: str = "06:00,20:00"
    database_connect_timeout_seconds: int = 15


_config: AppConfig | None = None


def load_config() -> AppConfig:
    """Load and cache application config.

    Storage connection priority:
    1. OS/.env STORAGE_DATABASE_URL, for advanced/dev deployments.
    2. Local user config storage.env, created by frontend setup.
    3. Runtime in-memory value, used during the first setup request.

    If none exists, the backend starts in frontend setup mode.
    """
    global _config
    if _config is None:
        load_dotenv()
        env_storage_url = os.getenv("STORAGE_DATABASE_URL")
        local_storage_url = _load_local_storage_database_url()
        _config = AppConfig(
            target_database_url=os.getenv("TARGET_DATABASE_URL"),
            storage_database_url=env_storage_url or local_storage_url or _runtime_storage_database_url,
            storage_database_name=os.getenv("STORAGE_DATABASE_NAME", DEFAULT_STORAGE_DATABASE_NAME),
            storage_maintenance_db=os.getenv("STORAGE_MAINTENANCE_DB", DEFAULT_STORAGE_MAINTENANCE_DB),
            top_query_limit=int(os.getenv("TOP_QUERY_LIMIT", "50")),
            analyze_query_limit=int(os.getenv("ANALYZE_QUERY_LIMIT", "25")),
            min_cost_improvement_pct=float(os.getenv("MIN_COST_IMPROVEMENT_PCT", "20")),
            min_recommendation_improvement_pct=float(
                os.getenv("MIN_RECOMMENDATION_IMPROVEMENT_PCT", os.getenv("MIN_COST_IMPROVEMENT_PCT", "10"))
            ),
            max_write_ratio_for_index=float(os.getenv("MAX_WRITE_RATIO_FOR_INDEX", "0.4")),
            storage_retention_days=int(os.getenv("STORAGE_RETENTION_DAYS", "30")),
            scheduler_enabled=os.getenv("SCHEDULER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "y", "on"},
            scheduler_run_times=os.getenv("SCHEDULER_RUN_TIMES", "06:00,20:00"),
            database_connect_timeout_seconds=int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "15")),
        )
    return _config


def reset_config() -> None:
    """Clear the cached config. Useful after first-time bootstrap or tests."""
    global _config
    _config = None
