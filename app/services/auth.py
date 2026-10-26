"""Auth service — password hashing and JWT token management."""
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    # bcrypt has a 72-byte limit; truncate if necessary
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
    token_version: int | None = None,
) -> str:
    """Create a JWT access token.

    Carries a unique `jti` (token id) and `tv` (token version). When the
    user's token_version is bumped (password reset, logout-everywhere),
    every previously issued token fails the version check on decode.
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({
        "exp": expire,
        "jti": str(uuid.uuid4()),
    })
    if token_version is not None:
        to_encode["tv"] = token_version
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str, current_token_version: int | None = None) -> dict | None:
    """Decode a JWT token. Returns the payload or None.

    When current_token_version is provided, tokens with an older `tv`
    claim are rejected (revoked by a password reset / logout-everywhere).
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    if current_token_version is not None and payload.get("tv") != current_token_version:
        return None
    return payload


def create_portal_token(client_id: int, expires_delta: timedelta | None = None) -> str:
    """Create a client-portal JWT.

    Scope claim `scope: "portal"` makes it unusable on user APIs: every
    user-API dependency requires a token WITHOUT the portal scope, and the
    portal dependency requires it. Mutual exclusion by construction.
    """
    to_encode = {
        "sub": f"client:{client_id}",
        "scope": "portal",
        "exp": datetime.now(UTC) + (expires_delta or timedelta(hours=12)),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_portal_token(token: str) -> dict | None:
    """Decode a portal token. Returns the payload ONLY if scope == "portal"."""
    payload = decode_access_token(token)
    if payload is None or payload.get("scope") != "portal":
        return None
    return payload
