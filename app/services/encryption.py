"""Encryption service for infrastructure secrets using Fernet symmetric encryption."""
import os
import warnings
from pathlib import Path

from cryptography.fernet import Fernet


def _load_env():
    """Load .env file if INFRA_ENCRYPTION_KEY is not already in the environment."""
    if os.getenv("INFRA_ENCRYPTION_KEY"):
        return
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


_load_env()

# Master key from environment — generated once with Fernet.generate_key()
_MASTER_KEY = os.getenv("INFRA_ENCRYPTION_KEY", "")


def _get_fernet() -> Fernet:
    """Get a Fernet instance, generating an ephemeral key if none is configured."""
    key = _MASTER_KEY
    if not key:
        key = Fernet.generate_key().decode()
        warnings.warn(
            "INFRA_ENCRYPTION_KEY not set — using ephemeral key. "
            "Secrets will be unreadable after restart."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


_fernet = _get_fernet()


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string, return base64 ciphertext string."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a base64 ciphertext string, return plaintext."""
    return _fernet.decrypt(ciphertext.encode()).decode()


def mask_value(value: str | None = None, visible_chars: int = 0) -> str:
    """Return a masked version of a value."""
    if not value:
        return "••••••••"
    if visible_chars <= 0:
        return "•" * 12
    if len(value) <= visible_chars:
        return "•" * len(value)
    return value[:visible_chars] + "•" * (len(value) - visible_chars)
