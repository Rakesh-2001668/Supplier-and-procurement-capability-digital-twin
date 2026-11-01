"""LLM gateway client (Technical Document §13.3, Blueprint §25).

PIC never calls a model vendor directly. When ``PIC_LLM_GATEWAY_URL`` is set it talks to one LiteLLM-compatible gateway
(``POST {url}/chat/completions`` and ``POST {url}/embeddings``, OpenAI-style JSON); otherwise every caller keeps its
deterministic path. Nothing here can make a business decision: callers pass a validator for the model output and use the
deterministic result whenever the call is off, over budget, fails or returns something the validator refuses.

    PIC_LLM_GATEWAY_URL    base URL of the gateway (e.g. https://litellm.internal:4000/v1)
    PIC_LLM_GATEWAY_KEY    bearer key (virtual key issued by the gateway per tenant/environment)
    PIC_LLM_MODEL          chat model alias (default "pic-chat")
    PIC_LLM_EMBEDDING_MODEL  embedding model alias (default "pic-embed")
    PIC_LLM_TIMEOUT        seconds per attempt (default 20)
    PIC_LLM_RETRIES        retries on connection errors, 429 and 5xx, with exponential back-off (default 2)
    PIC_LLM_KILL_SWITCH    "1"/"true": no call is made for any tenant
    PIC_LLM_RATE_PER_MINUTE   calls per tenant per minute (default 30; rule LLM-GATEWAY ``ratePerMinute`` overrides)
    PIC_LLM_MONTHLY_BUDGET_MICRO  cost budget per tenant and month in millionths of the gateway's currency (default 0 = unlimited;
                                  rule LLM-GATEWAY ``monthlyBudgetMicro`` overrides)
    PIC_LLM_PRICE_IN_MICRO_PER_1K, PIC_LLM_PRICE_OUT_MICRO_PER_1K  token prices used when the gateway does not report a cost
    PIC_LLM_RETENTION_DAYS  how long call metadata is kept (default 90; ``purge_expired`` deletes older rows)
    PIC_LLM_MAX_PROMPT_CHARS  cap on the redacted prompt (default 12000)

Before anything leaves the platform, every message is redacted (GSTIN, PAN, bank account numbers, IFSC, e-mail, phone, Aadhaar,
card numbers, UPI ids): the call log keeps counts and SHA-256 digests of the redacted prompt and answer, never the text.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, current_user
from app.pic.models import LlmCallLog
from app.pic.platform import clock

DEFAULT_RATE = 30
DEFAULT_RETENTION_DAYS = 90
DEFAULT_MAX_PROMPT = 12000


@dataclass
class GatewayResult:
    ok: bool
    text: Optional[str] = None
    data: Any = None
    reason: Optional[str] = None      # why the deterministic fallback is used
    model: Optional[str] = None
    usage: dict = field(default_factory=dict)
    redactions: dict = field(default_factory=dict)


# ---------------------------------------------------------------- redaction
_PATTERNS = [
    ("GSTIN", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("UPI", re.compile(r"\b[\w.-]{2,}@(?:ok[a-z]+|ybl|ibl|axl|paytm|upi|apl|sbi|hdfcbank|icici)\b", re.I)),
    ("AADHAAR", re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("BANK_ACCOUNT", re.compile(r"(?i)(?:a/?c(?:count)?(?:\s*(?:no|number|#))?|account)\W{0,4}\d[\d ]{7,20}\d|\b\d{9,18}\b")),
]


def redact(text: str) -> tuple[str, dict]:
    """Replace personal and bank identifiers by ``[KIND]`` tokens. Returns the text and the number replaced per kind."""
    counts: dict[str, int] = {}
    out = text or ""
    for kind, pattern in _PATTERNS:
        out, n = pattern.subn(f"[{kind}]", out)
        if n:
            counts[kind] = counts.get(kind, 0) + n
    return out, counts


# ---------------------------------------------------------------- configuration
def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(key)
    return value.strip() if value and value.strip() else default


def configured() -> bool:
    return bool(_env("PIC_LLM_GATEWAY_URL"))


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _rule(session: Session) -> dict:
    from app.pic.platform import rules
    from app.pic.platform.errors import Problem
    try:
        return rules.resolve(session, "LLM-GATEWAY").body
    except Problem:
        return {}


def tenant_enabled(session: Session, purpose: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """The AI kill switches: the environment switch, the tenant switch of the agent platform when it exists (engineer A's
    ``agents.tenant_ai_enabled`` / ``ai_enabled``), and the COPILOT agent's own switch for Copilot calls."""
    if _truthy(_env("PIC_LLM_KILL_SWITCH")):
        return False, "PIC_LLM_KILL_SWITCH is on"
    from app.pic.platform import agents
    for name in ("tenant_ai_enabled", "ai_enabled", "tenant_enabled"):
        fn = getattr(agents, name, None)
        if callable(fn):
            try:
                result = fn(session)
            except Exception:  # noqa: BLE001 - a broken switch must fail closed
                return False, "tenant AI switch could not be read"
            enabled, reason = (result if isinstance(result, tuple) else (bool(result), None))
            if not enabled:
                return False, reason or "AI is switched off for this company"
            break
    if purpose == "COPILOT":
        try:
            if agents.get(session, "COPILOT").kill_switch:
                return False, "Copilot kill switch is on"
        except Exception:  # noqa: BLE001 - agent catalogue not seeded for this tenant: no agent switch to honour
            pass
    return True, None


def _post(path: str, body: dict, timeout: float) -> tuple[int, dict, dict]:
    request = urllib.request.Request(f"{_env('PIC_LLM_GATEWAY_URL').rstrip('/')}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json", "accept": "application/json",
                                              **({"authorization": f"Bearer {_env('PIC_LLM_GATEWAY_KEY')}"} if _env("PIC_LLM_GATEWAY_KEY") else {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured URL
            return response.status, json.loads(response.read().decode("utf-8", "replace") or "{}"), dict(response.headers)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace") or "{}")
        except ValueError:
            payload = {}
        return exc.code, payload if isinstance(payload, dict) else {}, dict(exc.headers or {})


def _call(path: str, body: dict) -> tuple[dict, dict, int]:
    """One gateway call with retries (connection errors, 429, 5xx) and exponential back-off. Returns (json, headers, attempts)."""
    timeout = float(_env("PIC_LLM_TIMEOUT", "20"))
    retries = int(_env("PIC_LLM_RETRIES", "2"))
    delay, last = 0.5, "no attempt"
    for attempt in range(1, retries + 2):
        try:
            status, payload, headers = _post(path, body, timeout)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            status, payload, headers, last = 0, {}, {}, f"{type(exc).__name__}: {exc}"
        else:
            if 200 <= status < 300:
                return payload, headers, attempt
            last = f"HTTP {status}: {str((payload.get('error') or {}).get('message') if isinstance(payload.get('error'), dict) else payload.get('error') or '')[:200]}"
            if status not in (429, 500, 502, 503, 504):
                break
        if attempt <= retries:
            time.sleep(delay)
            delay *= 2
    raise GatewayError(last)


class GatewayError(Exception):
    pass


# ---------------------------------------------------------------- budget, rate, log
def _limits(session: Session) -> tuple[int, int, int]:
    rule = _rule(session)
    rate = int(rule.get("ratePerMinute", _env("PIC_LLM_RATE_PER_MINUTE", str(DEFAULT_RATE))))
    budget = int(rule.get("monthlyBudgetMicro", _env("PIC_LLM_MONTHLY_BUDGET_MICRO", "0")))
    days = int(rule.get("retentionDays", _env("PIC_LLM_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))))
    return rate, budget, days


def usage(session: Session) -> dict:
    now = clock.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rate, budget, days = _limits(session)
    spent = session.execute(select(func.coalesce(func.sum(LlmCallLog.cost_micro), 0)).where(LlmCallLog.created_at >= month_start)).scalar()
    last_minute = session.execute(select(func.count()).select_from(LlmCallLog).where(
        LlmCallLog.created_at >= now - timedelta(minutes=1), LlmCallLog.status.in_(("OK", "ERROR")))).scalar()
    by_status = dict(session.execute(select(LlmCallLog.status, func.count()).where(LlmCallLog.created_at >= month_start).group_by(LlmCallLog.status)).all())
    return {"monthSpentMicro": int(spent), "monthlyBudgetMicro": budget, "callsLastMinute": int(last_minute), "ratePerMinute": rate,
            "callsThisMonth": by_status, "retentionDays": days}


def status(session: Session) -> dict:
    enabled, reason = tenant_enabled(session)
    return {"configured": configured(), "gatewayUrl": _env("PIC_LLM_GATEWAY_URL") and "set", "model": _env("PIC_LLM_MODEL", "pic-chat"),
            "embeddingModel": _env("PIC_LLM_EMBEDDING_MODEL", "pic-embed"), "enabled": enabled and configured(), "switchReason": reason,
            "mode": "gateway" if configured() and enabled else "deterministic", **usage(session)}


def _log(session: Session, purpose: str, result: str, *, model=None, reason=None, prompt="", response="", usage_=None, cost=0,
         latency=0, redactions=None) -> None:
    _, _, days = _limits(session)
    usage_ = usage_ or {}
    session.add(LlmCallLog(
        tenant_id=current_tenant(session), purpose=purpose, model=model, status=result, reason=(reason or None) and reason[:300],
        prompt_chars=len(prompt), response_chars=len(response), tokens_in=int(usage_.get("prompt_tokens") or 0),
        tokens_out=int(usage_.get("completion_tokens") or 0), cost_micro=int(cost), latency_ms=int(latency), redactions=redactions or {},
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest() if prompt else None,
        response_sha256=hashlib.sha256(response.encode()).hexdigest() if response else None,
        user_id=current_user(session), retain_until=clock.now() + timedelta(days=days), created_by=current_user(session)))
    session.flush()


def _blocked(session: Session, purpose: str, reason: str, redactions: Optional[dict] = None) -> GatewayResult:
    _log(session, purpose, "BLOCKED", reason=reason, redactions=redactions)
    return GatewayResult(False, reason=reason)


def _precheck(session: Session, purpose: str) -> Optional[GatewayResult]:
    if not configured():
        return GatewayResult(False, reason="PIC_LLM_GATEWAY_URL is not set")
    enabled, why = tenant_enabled(session, purpose)
    if not enabled:
        return _blocked(session, purpose, why or "AI is switched off")
    rate, budget, _ = _limits(session)
    u = usage(session)
    if u["callsLastMinute"] >= rate:
        return _blocked(session, purpose, f"rate limit of {rate} calls per minute reached")
    if budget and u["monthSpentMicro"] >= budget:
        return _blocked(session, purpose, "monthly LLM cost budget is used up")
    return None


def _cost(headers: dict, usage_: dict) -> int:
    reported = next((v for k, v in headers.items() if k.lower() == "x-litellm-response-cost"), None)
    try:
        if reported is not None:
            return int(float(reported) * 1_000_000)
    except ValueError:
        pass
    price_in, price_out = int(_env("PIC_LLM_PRICE_IN_MICRO_PER_1K", "0")), int(_env("PIC_LLM_PRICE_OUT_MICRO_PER_1K", "0"))
    return (int(usage_.get("prompt_tokens") or 0) * price_in + int(usage_.get("completion_tokens") or 0) * price_out) // 1000


# ---------------------------------------------------------------- chat
def chat(session: Session, purpose: str, messages: list[dict], *, validator: Optional[Callable[[str], Any]] = None, json_mode: bool = False,
         max_tokens: int = 600, temperature: float = 0.0) -> GatewayResult:
    """Run one chat completion. ``validator`` receives the model text and returns the parsed value or raises ``ValueError``; a
    refusal counts as a failure and the caller falls back to its deterministic answer. Never raises for gateway problems."""
    blocked = _precheck(session, purpose)
    if blocked is not None:
        return blocked
    redactions: dict[str, int] = {}
    clean = []
    for m in messages:
        text, counts = redact(str(m.get("content") or ""))
        for k, v in counts.items():
            redactions[k] = redactions.get(k, 0) + v
        clean.append({"role": m.get("role", "user"), "content": text})
    prompt = "\n".join(m["content"] for m in clean)
    cap = int(_env("PIC_LLM_MAX_PROMPT_CHARS", str(DEFAULT_MAX_PROMPT)))
    if len(prompt) > cap:
        return _blocked(session, purpose, f"prompt of {len(prompt)} characters exceeds the {cap} limit", redactions)
    model = _env("PIC_LLM_MODEL", "pic-chat")
    body = {"model": model, "messages": clean, "max_tokens": max_tokens, "temperature": temperature,
            **({"response_format": {"type": "json_object"}} if json_mode else {})}
    started = time.monotonic()
    try:
        payload, headers, _ = _call("/chat/completions", body)
        choice = (payload.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        if not text:
            raise GatewayError("the gateway answered without text")
        usage_ = payload.get("usage") or {}
    except GatewayError as exc:
        _log(session, purpose, "ERROR", model=model, reason=str(exc), prompt=prompt, latency=(time.monotonic() - started) * 1000, redactions=redactions)
        return GatewayResult(False, reason=str(exc), model=model, redactions=redactions)
    latency, cost = (time.monotonic() - started) * 1000, _cost(headers, usage_)
    parsed = text
    if validator is not None:
        try:
            parsed = validator(text)
        except ValueError as exc:
            _log(session, purpose, "FALLBACK", model=model, reason=f"answer refused: {exc}", prompt=prompt, response=text, usage_=usage_, cost=cost,
                 latency=latency, redactions=redactions)
            return GatewayResult(False, text=text, reason=f"answer refused: {exc}", model=model, usage=usage_, redactions=redactions)
    _log(session, purpose, "OK", model=model, prompt=prompt, response=text, usage_=usage_, cost=cost, latency=latency, redactions=redactions)
    return GatewayResult(True, text=text, data=parsed, model=model, usage=usage_, redactions=redactions)


def embed(session: Session, purpose: str, texts: list[str]) -> Optional[list[list[float]]]:
    """Embeddings through the gateway (texts redacted first); None when the gateway is not usable."""
    blocked = _precheck(session, purpose)
    if blocked is not None or not texts:
        return None
    clean, redactions = [], {}
    for t in texts:
        text, counts = redact(t)
        clean.append(text)
        for k, v in counts.items():
            redactions[k] = redactions.get(k, 0) + v
    model = _env("PIC_LLM_EMBEDDING_MODEL", "pic-embed")
    started = time.monotonic()
    try:
        payload, headers, _ = _call("/embeddings", {"model": model, "input": clean})
        vectors = [d["embedding"] for d in sorted(payload.get("data") or [], key=lambda d: d.get("index", 0))]
        if len(vectors) != len(clean) or any(not isinstance(v, list) for v in vectors):
            raise GatewayError("the gateway returned a different number of embeddings")
    except (GatewayError, KeyError, TypeError) as exc:
        _log(session, purpose, "ERROR", model=model, reason=str(exc), prompt="\n".join(clean), redactions=redactions)
        return None
    usage_ = payload.get("usage") or {}
    _log(session, purpose, "OK", model=model, prompt="\n".join(clean), usage_=usage_, cost=_cost(headers, usage_),
         latency=(time.monotonic() - started) * 1000, redactions=redactions)
    return vectors


def purge_expired(session: Session) -> int:
    """Delete call metadata past its retention (callable from the retention job)."""
    return session.execute(delete(LlmCallLog).where(LlmCallLog.retain_until < clock.now())).rowcount


def recent_calls(session: Session, limit: int = 50) -> list[dict]:
    rows = session.execute(select(LlmCallLog).order_by(LlmCallLog.created_at.desc()).limit(limit)).scalars().all()
    return [{"at": r.created_at.isoformat(), "purpose": r.purpose, "model": r.model, "status": r.status, "reason": r.reason,
             "promptChars": r.prompt_chars, "responseChars": r.response_chars, "tokensIn": r.tokens_in, "tokensOut": r.tokens_out,
             "costMicro": r.cost_micro, "latencyMs": r.latency_ms, "redactions": r.redactions} for r in rows]


# ---------------------------------------------------------------- JSON output helpers
def json_object(text: str, required: dict[str, type]) -> dict:
    """Validator: the model text (optionally in a ```json fence) must be a JSON object with the required keys and types."""
    body = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", body, re.S)
    if fence:
        body = fence.group(1)
    try:
        data = json.loads(body)
    except ValueError:
        raise ValueError("not valid JSON")
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    for key, kind in required.items():
        if not isinstance(data.get(key), kind) or (kind is str and not data[key].strip()):
            raise ValueError(f"'{key}' is missing or not a {kind.__name__}")
    return data
