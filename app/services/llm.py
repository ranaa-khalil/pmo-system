"""LLM resilience wrapper — ONE door for every AI call (ADR: the LLM layer).

Every AI call goes through call_llm: ~20s timeout per attempt, exactly one
retry (2 attempts total), a deterministic fallback on failure (AI NEVER
blocks a user flow — the fallback string is deliberately non-JSON so
downstream parsers yield {} and the caller's own deterministic path runs),
and one LlmUsage row per call. Tenant LLM keys come from tenant_config —
key VALUES are never logged or recorded.
"""
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger("app.llm")

FALLBACK_TEXT = "AI service unavailable — the deterministic fallback was used."
TIMEOUT_S = 20.0
ATTEMPTS = 2  # 1 attempt + exactly 1 retry
RETRY_DELAY_S = 1.0


def _resolve_config(tenant_config: dict | None) -> tuple[str, str, str]:
    """Per-tenant AI settings, else global config. Never logs values."""
    if tenant_config:
        api_key = tenant_config.get("api_key", "")
        base_url = tenant_config.get("base_url", settings.ai_base_url)
        model = tenant_config.get("model", settings.ai_model)
    else:
        api_key = settings.ai_api_key
        base_url = settings.ai_base_url
        model = settings.ai_model
    return api_key, base_url, model


def call_llm(
    system_prompt: str,
    user_prompt: str,
    tenant_config: dict | None = None,
    max_tokens: int = 1500,
    json_mode: bool = False,
    feature: str = "ai",
) -> str:
    """Call the LLM through the resilience layer. Never raises through."""
    started = time.monotonic()
    ok = False
    try:
        api_key, base_url, model = _resolve_config(tenant_config)
        if not api_key:
            logger.info("AI not configured (feature=%s) — deterministic fallback", feature)
            return FALLBACK_TEXT

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(ATTEMPTS):
            try:
                with httpx.Client(timeout=TIMEOUT_S) as client:
                    resp = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                ok = True
                return data["choices"][0]["message"]["content"]
            except Exception as exc:  # noqa: BLE001 — the fallback never raises through
                logger.warning(
                    "LLM call failed (feature=%s attempt=%s/%s): %s",
                    feature, attempt + 1, ATTEMPTS, type(exc).__name__,
                )
                if attempt < ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY_S)
        return FALLBACK_TEXT
    finally:
        _record_usage(tenant_config, feature, ok, time.monotonic() - started)


def _record_usage(tenant_config: dict | None, feature: str, ok: bool, elapsed_s: float) -> None:
    """One LlmUsage row per call. Key values are never recorded."""
    try:
        from app.database import SessionLocal
        from app.models.llm_usage import LlmUsage

        tenant_id = tenant_config.get("tenant_id") if tenant_config else None
        db = SessionLocal()
        try:
            db.add(LlmUsage(
                tenant_id=tenant_id, feature=feature[:50], ok=ok,
                latency_ms=int(elapsed_s * 1000),
                error=None if ok else "fallback",
            ))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — usage bookkeeping must never raise through
        logger.exception("LlmUsage row write failed")
