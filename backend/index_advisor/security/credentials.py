"""Credential encryption helpers for local Index Advisor installations.

Target database passwords are stored encrypted in the storage database.  The
symmetric key is generated once per local installation and kept in the local
config directory, not in the storage database.  Existing legacy plaintext values
are still readable so old installations do not break immediately, but all new or
updated passwords are written as encrypted tokens.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from index_advisor.config import local_config_dir

_ENCRYPTED_PREFIX = "enc:v1:"
_KEY_ENV_VAR = "INDEX_ADVISOR_CREDENTIAL_KEY"
_KEY_FILE_NAME = "credential.key"


class CredentialEncryptionError(RuntimeError):
    """Raised when an encrypted credential cannot be decrypted."""


def credential_key_path() -> Path:
    return local_config_dir() / _KEY_FILE_NAME


def _load_or_create_key() -> bytes:
    env_key = os.getenv(_KEY_ENV_VAR)
    if env_key:
        return env_key.encode("utf-8")

    path = credential_key_path()
    if path.exists():
        return path.read_bytes().strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        # Windows does not fully support POSIX file modes; the file still lives
        # inside the local product config directory.
        pass
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value and value.startswith(_ENCRYPTED_PREFIX))


def encrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if is_encrypted_secret(value):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{_ENCRYPTED_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not is_encrypted_secret(value):
        # Backward compatibility for rows created before credential encryption
        # existed. The next target update/create will write encrypted values.
        return value
    token = value[len(_ENCRYPTED_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialEncryptionError(
            "Could not decrypt the stored target database password. This usually means the local "
            "credential.key file belongs to a different installation. Re-enter the target password "
            "from the Targets/Setup page to re-encrypt it for this installation."
        ) from exc
