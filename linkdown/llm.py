"""Provider-agnostic chat client for OpenAI-compatible APIs.

One client covers the ITU reference stack (Ollama exposes /v1), Groq, Google
Gemini's OpenAI-compatible endpoint, OpenRouter and OpenAI. Every call returns
the provider, model, latency and token usage so the audit log can record exactly
which model produced which words.

Configure with environment variables (never commit keys):
  LINKDOWN_LLM_PROVIDER   ollama | groq | gemini | openrouter | openai | custom
  LINKDOWN_LLM_MODEL      model id at that provider
  LINKDOWN_LLM_API_KEY    key (not needed for ollama)
  LINKDOWN_LLM_BASE_URL   optional override of the provider's base URL
  LINKDOWN_LLM_MIN_INTERVAL_S  optional pause between calls (free tiers have
                          tokens-per-minute limits; e.g. 20 for Groq's free plan)
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

import httpx

PRESETS = {
    "ollama": "http://localhost:11434/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
}


@dataclass
class LLMResult:
    ok: bool
    data: dict | None
    text: str
    provider: str
    model: str
    latency_ms: int
    usage: dict = field(default_factory=dict)
    error: str | None = None
    is_ai: bool = True
    request_id: str | None = None      # provider's request id (header or body), for audit and support
    response_id: str | None = None     # the completion id in the response body
    finish_reason: str | None = None   # "stop", "length" (truncated), ...


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1500
    timeout_s: float = 90.0
    json_mode: bool = True
    min_interval_s: float = 0.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = os.environ.get("LINKDOWN_LLM_PROVIDER", "").strip()
        model = os.environ.get("LINKDOWN_LLM_MODEL", "").strip()
        if not provider or not model:
            raise RuntimeError("Set LINKDOWN_LLM_PROVIDER and LINKDOWN_LLM_MODEL (see README, 'Live model').")
        return cls(provider=provider, model=model,
                   api_key=os.environ.get("LINKDOWN_LLM_API_KEY") or None,
                   base_url=os.environ.get("LINKDOWN_LLM_BASE_URL") or None,
                   min_interval_s=float(os.environ.get("LINKDOWN_LLM_MIN_INTERVAL_S") or 0))

    @property
    def url(self) -> str:
        base = self.base_url or PRESETS.get(self.provider)
        if not base:
            raise RuntimeError(f"Unknown provider '{self.provider}' and no LINKDOWN_LLM_BASE_URL")
        return base.rstrip("/") + "/chat/completions"


def extract_json(text: str) -> dict | None:
    """Parse a JSON object from model text (handles ```json fences and stray prose)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    start, depth = t.find("{"), 0
    if start < 0:
        return None
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    v = json.loads(t[start:i + 1])
                    return v if isinstance(v, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def request_id(r: httpx.Response, payload: dict) -> str | None:
    """The provider's request id: the x-request-id header (Groq, OpenAI, OpenRouter),
    else Groq's x_groq.id in the body."""
    rid = r.headers.get("x-request-id") or r.headers.get("request-id")
    if not rid and isinstance(payload.get("x_groq"), dict):
        rid = payload["x_groq"].get("id")
    return str(rid) if rid else None


class LLMClient:
    is_ai = True

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._http = httpx.Client(timeout=cfg.timeout_s)
        self._last_call = 0.0

    @property
    def label(self) -> str:
        return f"{self.cfg.provider}:{self.cfg.model}"

    def _post(self, messages: list[dict], json_mode: bool) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        body = {"model": self.cfg.model, "messages": messages,
                "temperature": self.cfg.temperature, "max_tokens": self.cfg.max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return self._http.post(self.cfg.url, headers=headers, json=body)

    @staticmethod
    def _retry_after(r: httpx.Response, attempt: int) -> float:
        """Seconds to wait after a rate limit: the provider's Retry-After header if
        present (capped at 60 s), otherwise exponential back-off."""
        try:
            return min(60.0, max(1.0, float(r.headers.get("retry-after", ""))))
        except ValueError:
            return float(min(30, 2 ** (attempt + 1)))

    def complete_json(self, system: str, user: str) -> LLMResult:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        wait = self.cfg.min_interval_s - (time.monotonic() - self._last_call)
        if self._last_call and wait > 0:
            time.sleep(wait)
        t0 = time.monotonic()
        last_err, json_mode = None, self.cfg.json_mode
        for attempt in range(6):
            self._last_call = time.monotonic()
            try:
                r = self._post(messages, json_mode)
            except httpx.HTTPError as e:
                last_err = f"network: {e}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 400 and json_mode and "response_format" in r.text:
                json_mode = False          # provider does not support JSON mode; retry without it
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(self._retry_after(r, attempt))
                continue
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
                break
            payload = r.json()
            choice = payload["choices"][0]
            text = choice["message"].get("content") or ""
            data = extract_json(text)
            if data is None and attempt < 5:
                messages = messages + [{"role": "assistant", "content": text},
                                       {"role": "user", "content": "Reply again with ONE valid JSON object only."}]
                continue
            return LLMResult(data is not None, data, text, self.cfg.provider,
                             payload.get("model", self.cfg.model),
                             int((time.monotonic() - t0) * 1000), payload.get("usage", {}),
                             None if data is not None else "model did not return valid JSON",
                             request_id=request_id(r, payload), response_id=payload.get("id"),
                             finish_reason=choice.get("finish_reason"))
        return LLMResult(False, None, "", self.cfg.provider, self.cfg.model,
                         int((time.monotonic() - t0) * 1000), {}, last_err)
