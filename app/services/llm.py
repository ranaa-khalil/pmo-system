"""LLM resilience wrapper — ONE door for every AI call (ADR: the LLM layer).

Every AI call goes through call_llm: ~20s timeout per attempt, exactly one
retry (2 attempts total), a deterministic fallback on failure (AI NEVER
blocks a user flow — the fallback string is deliberately non-JSON so
downstream parsers yield {} and the caller's own deterministic path runs),
and one LlmUsage row per call. Tenant LLM keys come from tenant_config —
key VALUES are never logged or recorded.
"""
import json
import logging
import time

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger("app.llm")

FALLBACK_TEXT = "AI service unavailable — the deterministic fallback was used."
TIMEOUT_S = 20.0
ATTEMPTS = 2  # 1 attempt + exactly 1 retry
RETRY_DELAY_S = 1.0
UNLIMITED = 999999  # count-metric sentinel (matches usage_service.UNLIMITED)


class LLMStreamError(Exception):
    """The streaming LLM call failed (unconfigured key, connect, status, or
    a mid-stream break). The caller's deterministic path runs on this —
    never a broken half answer reaches a user flow."""


def _enforce_ai_quota(tenant_config: dict | None) -> None:
    """Raise 403 when the tenant's monthly AI-call quota is exhausted (FR-T6).

    The quota numbers ride in tenant_config from get_ai_config — computed on
    the caller's session, so the wrapper never opens its own. Gating at the
    ONE door means every metered call (llm_usage rows) passes here first; a
    rejected call makes no HTTP request and writes no llm_usage row.
    """
    if not tenant_config:
        return
    limit = tenant_config.get("ai_calls_limit")
    used = tenant_config.get("ai_calls_used")
    if limit is None or used is None or int(limit) >= UNLIMITED:
        return
    if int(used) >= int(limit):
        raise HTTPException(
            status_code=403,
            detail=f"Quota exceeded: AI call limit is {limit}/month (current: {used}). "
                   f"Upgrade your plan for more AI calls.",
        )


# Public alias for the SSE route (phase 3): the stream endpoint gates quota
# BEFORE the response starts so a 403 keeps clean status semantics.
enforce_ai_quota = _enforce_ai_quota


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
    # Plan quota gate (FR-T6): BEFORE any HTTP attempt — a rejected call
    # never reaches the provider and is never metered into llm_usage.
    _enforce_ai_quota(tenant_config)
    started = time.monotonic()
    ok = False
    provider_usage = None
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
                # Per-capability metering: the provider's usage payload (when
                # present) fills the nullable prompt/completion token columns.
                usage = data.get("usage")
                if isinstance(usage, dict):
                    provider_usage = usage
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
        _record_usage(tenant_config, feature, ok, time.monotonic() - started, provider_usage)


def stream_llm(
    system_prompt: str,
    user_prompt: str,
    tenant_config: dict | None = None,
    max_tokens: int = 1500,
    json_mode: bool = False,
    feature: str = "ai",
):
    """Streaming variant of call_llm — the ONE door, stream shape (phase 3).

    Yields content deltas as they generate from an OpenAI-compatible
    /chat/completions SSE stream (stream=True). One LlmUsage row per call
    (same feature label; usage aggregated from the final chunk when the
    provider reports it). The quota gate runs first — a rejected call makes
    no HTTP request and is never metered. Retry contract: only a failure
    BEFORE the first delta is retried (the same one-retry allowance; attempt
    2 drops stream_options for strict providers); a mid-stream break raises
    LLMStreamError — retrying would duplicate the deltas already delivered.
    Unconfigured key and every failure raise LLMStreamError so the caller's
    deterministic fallback runs. Never returns a broken half answer."""
    _enforce_ai_quota(tenant_config)
    started = time.monotonic()
    ok = False
    provider_usage = None
    yielded = 0
    try:
        api_key, base_url, model = _resolve_config(tenant_config)
        if not api_key:
            logger.info("AI not configured (feature=%s) — streaming fallback", feature)
            raise LLMStreamError("AI not configured")

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "stream": True,
            # OpenAI-standard: the final chunk carries the usage payload —
            # the streamed call's metering.
            "stream_options": {"include_usage": True},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error = None
        for attempt in range(ATTEMPTS):
            body = dict(payload)
            if attempt > 0:
                body.pop("stream_options", None)
            try:
                with httpx.Client(timeout=TIMEOUT_S) as client:
                    with client.stream(
                        "POST", f"{base_url}/chat/completions", headers=headers, json=body
                    ) as resp:
                        if resp.status_code >= 400:
                            raise RuntimeError(f"HTTP {resp.status_code}")
                        for line in resp.iter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data_str = line[len("data:"):].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            usage = chunk.get("usage")
                            if isinstance(usage, dict):
                                provider_usage = usage
                            choices = chunk.get("choices") or []
                            delta = None
                            if choices:
                                delta = (choices[0].get("delta") or {}).get("content")
                            if delta:
                                yielded += 1
                                yield delta
                ok = True
                return
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:  # noqa: BLE001 — the fallback never raises through
                if yielded:
                    # Mid-stream break: a retry would duplicate the deltas
                    # already delivered — fail through, the caller degrades.
                    raise LLMStreamError(
                        f"stream broke after {yielded} deltas: {type(exc).__name__}"
                    ) from exc
                last_error = exc
                logger.warning(
                    "LLM stream failed (feature=%s attempt=%s/%s): %s",
                    feature, attempt + 1, ATTEMPTS, type(exc).__name__,
                )
                if attempt < ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY_S)
        raise LLMStreamError(
            f"stream failed: {type(last_error).__name__ if last_error else 'no content'}"
        )
    finally:
        _record_usage(tenant_config, feature, ok, time.monotonic() - started, provider_usage)


def _record_usage(
    tenant_config: dict | None,
    feature: str,
    ok: bool,
    elapsed_s: float,
    provider_usage: dict | None = None,
) -> None:
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
                prompt_tokens=_token_count(provider_usage, "prompt_tokens"),
                completion_tokens=_token_count(provider_usage, "completion_tokens"),
                error=None if ok else "fallback",
            ))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — usage bookkeeping must never raise through
        logger.exception("LlmUsage row write failed")


def _token_count(usage: dict | None, key: str) -> int | None:
    """An int token count from the provider's usage payload, or None —
    absent/invalid values stay NULL (the columns are nullable by design)."""
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
