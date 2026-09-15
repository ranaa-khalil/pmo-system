"""Per-tenant settings service — get/set per-tenant configuration.

Secrets (GitHub token, AI API key) are encrypted at rest using Fernet.
Non-secret values are stored as plaintext.

Falls back to global config (settings.github_token, settings.ai_api_key, etc.)
when a per-tenant setting is not set, so the system works in both modes.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant_setting import (
    SECRET_KEYS,
    SETTING_AI_API_KEY,
    SETTING_AI_BASE_URL,
    SETTING_AI_MODEL,
    SETTING_GITHUB_TOKEN,
    TenantSetting,
)


def _get_fernet() -> Fernet:
    """Create a Fernet instance from the app's secret key.

    Derives a 32-byte key from the app secret_key using SHA-256,
    then base64-encodes it (Fernet requires a URL-safe base64 32-byte key).
    """
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(value: str) -> str:
    """Encrypt a secret value."""
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    """Decrypt a secret value. Returns empty string on failure."""
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        return ""


def get_setting(db: Session, tenant_id: int, key: str) -> str | None:
    """Get a per-tenant setting value.

    Falls back to global config for known keys (github_token, ai_api_key, etc.)
    when the per-tenant setting is not set.
    """
    setting = db.query(TenantSetting).filter(
        TenantSetting.tenant_id == tenant_id,
        TenantSetting.key == key,
    ).first()

    if setting:
        if setting.is_secret:
            return _decrypt(setting.value) if setting.value else ""
        return setting.value

    # Fall back to global config
    if key == SETTING_GITHUB_TOKEN:
        return settings.github_token or None
    if key == SETTING_AI_API_KEY:
        return settings.ai_api_key or None
    if key == SETTING_AI_BASE_URL:
        return settings.ai_base_url or None
    if key == SETTING_AI_MODEL:
        return settings.ai_model or None

    return None


def set_setting(db: Session, tenant_id: int, key: str, value: str) -> TenantSetting:
    """Set a per-tenant setting value. Encrypts secrets."""
    is_secret = 1 if key in SECRET_KEYS else 0
    stored_value = _encrypt(value) if is_secret and value else value

    setting = db.query(TenantSetting).filter(
        TenantSetting.tenant_id == tenant_id,
        TenantSetting.key == key,
    ).first()

    if setting:
        setting.value = stored_value
        setting.is_secret = is_secret
    else:
        setting = TenantSetting(
            tenant_id=tenant_id,
            key=key,
            value=stored_value,
            is_secret=is_secret,
        )
        db.add(setting)

    db.flush()
    return setting


def delete_setting(db: Session, tenant_id: int, key: str) -> bool:
    """Delete a per-tenant setting. Returns True if deleted."""
    setting = db.query(TenantSetting).filter(
        TenantSetting.tenant_id == tenant_id,
        TenantSetting.key == key,
    ).first()
    if setting:
        db.delete(setting)
        db.flush()
        return True
    return False


def get_all_settings(db: Session, tenant_id: int) -> dict:
    """Get all settings for a tenant. Secrets are masked."""
    settings_list = db.query(TenantSetting).filter(
        TenantSetting.tenant_id == tenant_id,
    ).all()

    result = {}
    for s in settings_list:
        if s.is_secret:
            # Return True/False to indicate if the secret is set, not the actual value
            result[s.key] = "[SET]" if s.value else "[EMPTY]"
        else:
            result[s.key] = s.value

    # Include global fallbacks for known keys if not set per-tenant
    if SETTING_GITHUB_TOKEN not in result:
        result[SETTING_GITHUB_TOKEN] = "[GLOBAL]" if settings.github_token else "[EMPTY]"
    if SETTING_AI_API_KEY not in result:
        result[SETTING_AI_API_KEY] = "[GLOBAL]" if settings.ai_api_key else "[EMPTY]"
    if SETTING_AI_BASE_URL not in result:
        result[SETTING_AI_BASE_URL] = settings.ai_base_url or ""
    if SETTING_AI_MODEL not in result:
        result[SETTING_AI_MODEL] = settings.ai_model or ""

    return result


# ─── Convenience functions ────────────────────────────────────

def get_github_token(db: Session, tenant_id: int) -> str | None:
    """Get the GitHub token for a tenant (per-tenant or global fallback)."""
    return get_setting(db, tenant_id, SETTING_GITHUB_TOKEN)


def get_ai_config(db: Session, tenant_id: int) -> dict:
    """Get AI configuration for a tenant (per-tenant or global fallback)."""
    return {
        "api_key": get_setting(db, tenant_id, SETTING_AI_API_KEY) or "",
        "base_url": get_setting(db, tenant_id, SETTING_AI_BASE_URL) or settings.ai_base_url,
        "model": get_setting(db, tenant_id, SETTING_AI_MODEL) or settings.ai_model,
    }


def is_ai_configured_for_tenant(db: Session, tenant_id: int) -> bool:
    """Check if AI is configured for a tenant (per-tenant or global)."""
    config = get_ai_config(db, tenant_id)
    return bool(config["api_key"])
