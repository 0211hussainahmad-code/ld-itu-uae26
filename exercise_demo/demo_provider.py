"""Explicitly approved, bounded, single-attempt live demonstration transport.

Separate from the frozen provider comparison and outside the frozen `linkdown/`
package. Only reviewed profiles can be used (Groq direct, or OpenRouter pinned to
Groq); the request body is fixed by the profile, never by the plan. Prices are
supplied in the reviewed plan and may not be below the profile's documented
prices. Worst-case reservations are retained even on network errors. Through
OpenRouter, every reply must be proved served by the pinned host (OpenRouter's
generation record) and its charged cost reconciled before it is used.

All four role clients share one DemoBudget. After the first failed, refused,
truncated, unreconciled or unusable turn, no further request is sent: such a run
can no longer pass the demonstration check, so later paid requests would only
add cost.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import sys
import time
from pathlib import Path

from linkdown.llm import LLMClient, LLMResult, extract_json, request_id

# The benchmark's tested host-provenance rule and generation-record lookup (imported,
# never modified): eval/providers.py host_state() and served_by().
_EVAL = str(Path(__file__).resolve().parent.parent / "eval")
if _EVAL not in sys.path:
    sys.path.append(_EVAL)
import providers as bench  # noqa: E402

PROMPT_BYTE_LIMIT = 50000
FRAMING_TOKENS = 512
OUTPUT_CAP_CEILING = 16000
MAX_REQUESTS = 25
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Reviewed live profiles, keyed "provider:model". The model fields are the frozen
# benchmark's configuration A (eval/bakeoff_cases.yaml, configs.A.request) word for
# word; a test compares them. No sampling parameter is sent (provider default), as
# in the benchmark. Reasoning tokens count inside completion_tokens and the output
# cap (observed on the team's account through OpenRouter's Groq route, 26 Oct 2026).
#
# groq: Groq direct, without OpenRouter's route pin. Checked against Groq's docs on
# 1 Nov 2026: docs/model/openai/gpt-oss-120b (USD 0.15 input, 0.075 cached input,
# 0.60 output per million; 65,536 max output), docs/api-reference
# (max_completion_tokens; reasoning_effort low|medium|high for gpt-oss), and
# docs/structured-outputs (json_object on all models).
#
# openrouter: configuration A exactly as frozen, including its route pin: Groq only,
# no provider fallback, and Groq must support every field sent. No `models` array is
# sent, so there is no model fallback. Checked 1 Nov 2026: Groq row on
# openrouter.ai/openai/gpt-oss-120b USD 0.150 / 0.600 (cache read 0.075); docs on
# provider routing, errors, the generation record and key limits.
GROQ_PIN = {"order": ["groq"], "only": ["groq"], "allow_fallbacks": False, "require_parameters": True}
_CONFIG_A = {"reasoning_effort": "high", "response_format": {"type": "json_object"}, "max_completion_tokens": 16000}
PROFILES = {
    "groq:openai/gpt-oss-120b": {
        "provider": "groq", "model": "openai/gpt-oss-120b", "serving": "direct",
        "request": dict(_CONFIG_A),
        "min_price_usd_per_mtok": {"input": 0.15, "output": 0.60},
        "checked": "2026-11-01",
    },
    "openrouter:openai/gpt-oss-120b": {
        "provider": "openrouter", "model": "openai/gpt-oss-120b", "serving": "pinned", "upstream": "Groq",
        "request": {**_CONFIG_A, "provider": GROQ_PIN},
        "min_price_usd_per_mtok": {"input": 0.15, "output": 0.60},
        "checked": "2026-11-01",
    },
}
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
OPENROUTER_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"
_GEN_ID = re.compile(r"^gen-[A-Za-z0-9-]{1,124}$")
PREFLIGHT_GENERATION_ID = "gen-linkdown-preflight-0000000000"     # never a real generation
PRICE_TOLERANCE = 0.01          # charged cost may exceed the plan-price cost by at most 1%


def profile_for(provider, model) -> dict | None:
    return PROFILES.get(f"{provider}:{model}")


RATE_HEADERS = ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests",
                "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens",
                "retry-after")
_SAFE_CODE = re.compile(r"^[a-z0-9_]{1,48}$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")


def worst_case_usd(prompt_bytes: int, max_tokens: int, input_per_million: float,
                   output_per_million: float) -> float:
    """Reservation for one request: prompt UTF-8 bytes (an upper bound on tokens
    for byte-level tokenizers) plus framing, and the full output cap."""
    return ((prompt_bytes + FRAMING_TOKENS) * input_per_million + max_tokens * output_per_million) / 1e6


def _positive(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v > 0


def _count(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, int) and v >= 0


def _safe(v) -> str | None:
    """A provider-supplied identifier, kept only if it cannot carry free text."""
    v = str(v) if v is not None else ""
    return v if _SAFE_VALUE.match(v) else None


def rate_limits(r) -> dict:
    return {k: _safe(r.headers[k]) for k in RATE_HEADERS if k in r.headers}


def error_code(r) -> str | None:
    """Machine-readable error details only, never the message or a raw body: Groq's
    code (e.g. json_validate_failed) or OpenRouter's numeric code with its metadata
    limit_source (e.g. openrouter_key_limit) and provider_name."""
    try:
        err = r.json().get("error") or {}
        meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
        parts = [err.get("code"), err.get("type"), meta.get("limit_source"), meta.get("provider_name")]
    except (ValueError, AttributeError):
        return None
    out = []
    for v in parts:
        v = str(v).lower() if isinstance(v, (str, int)) and not isinstance(v, bool) else None
        if v and _SAFE_CODE.match(v) and v not in out:
            out.append(v)
    return " ".join(out) or None


class DemoStop(RuntimeError):
    """A stop whose message is written by this module only, so it is safe to log."""


class DemoBudget:
    def __init__(self, path: Path, *, cap_usd: float, input_per_million: float,
                 output_per_million: float, max_requests: int = MAX_REQUESTS,
                 min_interval_s: float = 0.0):
        if not all(_positive(v) for v in (cap_usd, input_per_million, output_per_million)):
            raise ValueError("Positive finite reviewed prices and spending cap required")
        if cap_usd > 60 or not 1 <= max_requests <= MAX_REQUESTS:
            raise ValueError("Demo cap cannot exceed $60 or 25 requests")
        if (isinstance(min_interval_s, bool) or not isinstance(min_interval_s, (int, float))
                or not math.isfinite(min_interval_s) or not 0 <= min_interval_s <= 120):
            raise ValueError("min_interval_s must be between 0 and 120 seconds")
        self.path, self.cap = path, cap_usd
        self.input_price, self.output_price = input_per_million, output_per_million
        self.max_requests, self.reserved, self.calls = max_requests, 0.0, []
        self.min_interval, self._last_send = float(min_interval_s), None
        self.reported, self.halted = 0.0, None
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite or implicitly resume a possibly billed attempt.
        with path.open("x", encoding="utf-8") as f:
            f.write(json.dumps({"cap_usd": self.cap, "calls": []}) + "\n")

    def _write(self, row: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def halt(self, reason: str) -> None:
        """Stop all later requests (all roles). The first reason is kept."""
        if self.halted is None:
            self.halted = reason
            self._write({"status": "halted", "after_request": len(self.calls), "reason": reason})

    def reserve(self, system: str, user: str, max_tokens: int) -> dict:
        if self.halted is not None:
            raise DemoStop("Halted after an earlier failed turn; nothing sent")
        size = len((system + user).encode("utf-8"))
        if size > PROMPT_BYTE_LIMIT:
            raise DemoStop("Prompt byte limit exceeded; nothing sent")
        # Conservative byte/token bound plus message framing. Provider-specific
        # charges or hidden billable tokens must be covered by the approved plan;
        # settle() halts the run if a reported cost ever exceeds this reservation.
        cost = worst_case_usd(size, max_tokens, self.input_price, self.output_price)
        if len(self.calls) >= self.max_requests or self.reserved + cost > self.cap:
            raise DemoStop("Demonstration request or spending limit reached; nothing sent")
        if self.min_interval and self._last_send is not None:
            # Optional pacing for provider rate limits (shared by all roles). Not a retry.
            wait = self.min_interval - (time.monotonic() - self._last_send)
            if wait > 0:
                time.sleep(wait)
        self.reserved += cost
        row = {"request": len(self.calls) + 1, "reserved_usd": cost,
               "cumulative_reserved_usd": self.reserved, "status": "reserved-before-send"}
        self._write(row)
        self.calls.append(row)
        self._last_send = time.monotonic()
        return row

    def failed(self, row: dict, http_status: int, code: str | None, limits: dict) -> None:
        """Record a non-200 reply. No usage comes back, so the reservation is kept."""
        self._write({"request": row["request"], "status": "http-error-reservation-retained",
                     "http_status": http_status, "error_code": code, "rate_limits": limits})

    def settle(self, row: dict, usage, limits: dict | None = None, rid: str | None = None) -> bool:
        """Record the provider-reported cost of a request that returned a body.
        The reservation is kept. Missing/invalid usage, or a cost above the
        reservation, halts every later request, needs human reconciliation and
        returns False: the caller must then fail this response too.
        Cached prompt tokens are priced as uncached (an over-count, never under)."""
        try:
            pt, ct = usage["prompt_tokens"], usage["completion_tokens"]
            if not (_count(pt) and _count(ct)):
                raise ValueError
            if "total_tokens" in usage and usage["total_tokens"] != pt + ct:
                raise ValueError        # tokens the split does not explain: never guess their price
            actual = (pt * self.input_price + ct * self.output_price) / 1e6
        except (KeyError, TypeError, ValueError):
            self._write({"request": row["request"], "status": "usage-missing-reservation-retained",
                         "request_id": rid, "rate_limits": limits or {}})
            self.halt("Missing or invalid usage; reservation retained; NEEDS HUMAN RECONCILIATION")
            return False
        row["settled"], row["reported_usd"] = True, actual
        self.reported += actual
        self._write({"request": row["request"], "status": "settled", "prompt_tokens": pt,
                     "completion_tokens": ct, "reported_usd": actual, "reserved_usd": row["reserved_usd"],
                     "request_id": rid, "rate_limits": limits or {}})
        if actual > row["reserved_usd"]:
            self.reserved += actual - row["reserved_usd"]
            self.halt("Reported cost exceeded the reservation; NEEDS HUMAN RECONCILIATION")
            return False
        return True

    def unverified_host(self, row: dict, serving: dict) -> None:
        """OpenRouter: the serving host was not proved to be the pinned one."""
        row["needs_charge"] = True
        self._write({"request": row["request"], "status": "host-not-verified-reservation-retained",
                     "serving": serving})
        self.halt(f"Serving provider {serving.get('state')} (pinned {serving.get('upstream')}); "
                  "reply not used; NEEDS HUMAN RECONCILIATION")

    def charge(self, row: dict, charged, serving: dict) -> bool:
        """OpenRouter: reconcile the cost OpenRouter says it charged (generation record
        total_cost, or the reply's usage.cost if larger). Missing, above the reservation,
        or above the approved prices: halt, and the caller fails this reply too."""
        row["needs_charge"] = True
        if isinstance(charged, bool) or not isinstance(charged, (int, float)) \
                or not math.isfinite(charged) or charged < 0:
            self._write({"request": row["request"], "status": "charge-unverified-reservation-retained",
                         "serving": serving})
            self.halt("Charged cost not verified; reservation retained; NEEDS HUMAN RECONCILIATION")
            return False
        planned = row.get("reported_usd")
        row["charged"] = True
        self.reported += max(0.0, charged - (planned or 0.0))
        self._write({"request": row["request"], "status": "charged", "charged_usd": charged,
                     "plan_price_usd": planned, "reserved_usd": row["reserved_usd"], "serving": serving})
        if charged > row["reserved_usd"]:
            self.reserved += charged - row["reserved_usd"]
            self.halt("Charged cost exceeded the reservation; NEEDS HUMAN RECONCILIATION")
            return False
        if planned is None or charged > planned * (1 + PRICE_TOLERANCE) + 1e-9:
            self.halt("Charged cost is above the approved prices; NEEDS HUMAN RECONCILIATION")
            return False
        return True

    def summary(self) -> dict:
        return {"cap_usd": self.cap, "requests_sent": len(self.calls), "max_requests": self.max_requests,
                "reserved_usd": self.reserved, "reported_usd": self.reported,
                "requests_without_reported_usage": sum(1 for c in self.calls if not c.get("settled")),
                "requests_without_verified_charge": sum(1 for c in self.calls
                                                        if not c.get("charged")),
                "halted": self.halted,
                "note": "Reported cost uses the plan's prices and provider usage; reconcile with provider receipts. "
                        "A request without usage or verified charge remains unresolved; its reservation is retained."}


class DemoClient(LLMClient):
    """One request per turn to a reviewed profile. No repair, retry, provider or
    model fallback; any failure stops every later request of the run. Through
    OpenRouter a reply is used only if its generation record proves the pinned host
    served it and its charged cost reconciles."""
    def __init__(self, cfg, budget, sleep=time.sleep):
        super().__init__(cfg)
        profile = profile_for(cfg.provider, cfg.model)
        if profile is None:
            raise ValueError("Only a reviewed provider/model profile can be used live")
        self.cap = profile["request"]["max_completion_tokens"]
        if not 1 <= self.cap <= OUTPUT_CAP_CEILING:
            raise ValueError("Profile output cap must be between 1 and 16,000 tokens")
        self.profile, self.budget, self._sleep = profile, budget, sleep
        self.last_serving: dict | None = None

    def verify_host(self, gen_id) -> dict:
        """OpenRouter generation record -> host state, via the benchmark's tested rule
        (eval/providers.py host_state; lookup retried with backoff by served_by).
        Only the record verifies; the reply body's `provider` field never does."""
        upstream = self.profile["upstream"]
        if not isinstance(gen_id, str) or not _GEN_ID.match(gen_id):
            return {"state": "unverified", "upstream": upstream, "generation_id": None,
                    "reason": "no valid generation id"}

        def getter(url, _headers):
            r = self._http.get(url, headers={"Authorization": f"Bearer {self.cfg.api_key}"})
            try:
                payload = r.json()
            except ValueError:
                payload = {}
            return r.status_code, dict(r.headers), payload if isinstance(payload, dict) else {}
        _, stats = bench.served_by(gen_id, getter=getter, sleep=self._sleep)
        found = "provider_responses" in stats and "provider_name" in stats
        entry = {**stats, "evidence": "generation_record", "reply_kind": "completion"} if found else None
        state = bench.host_state(entry, upstream)
        pr = stats.get("provider_responses") if found else None
        attempts = [{"provider_name": _safe(a.get("provider_name")),
                     "status": a.get("status") if _count(a.get("status")) else None,
                     "routed_service_tier": _safe(a.get("routed_service_tier"))}
                    for a in pr if isinstance(a, dict)] if isinstance(pr, list) else None
        cost = stats.get("total_cost") if found else None
        tokens = {k: stats.get(k) if _count(stats.get(k)) else None
                  for k in ("native_tokens_prompt", "native_tokens_completion", "native_tokens_reasoning")}
        return {"state": state, "upstream": upstream, "generation_id": gen_id,
                "provider_name": _safe(stats.get("provider_name")) if found else None,
                "model": _safe(stats.get("model")) if found else None,
                "total_cost": cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
                "attempts": attempts, "record_found": found, **tokens}

    def body(self, system: str, user: str) -> dict:
        """The exact request body: the reviewed profile's fields and the two prompts."""
        return {"model": self.cfg.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **copy.deepcopy(self.profile["request"])}

    def stop_live_requests(self, reason: str) -> None:
        """Called by the exercise when a parsed turn is unusable."""
        self.budget.halt(reason)

    def complete_json(self, system, user):
        started = time.monotonic()
        self.last_serving = None
        try:
            row = self.budget.reserve(system, user, self.cap)
            r = self._http.post(self.cfg.url, json=self.body(system, user),
                                headers={"Content-Type": "application/json",
                                         "Authorization": f"Bearer {self.cfg.api_key}"})
            limits = rate_limits(r)
            if r.status_code != 200:
                code = error_code(r)
                self.budget.failed(row, r.status_code, code, limits)
                raise DemoStop(f"HTTP {r.status_code}" + (f" {code}" if code else "") + "; no automatic retry")
            p = r.json()
            if not isinstance(p, dict):
                raise DemoStop("Response is not a JSON object")
            rid = _safe(request_id(r, p))
            reconciled = self.budget.settle(row, p.get("usage"), limits, rid)
            host_error = None
            if self.profile["serving"] == "pinned":
                serving = self.verify_host(p.get("id"))
                if serving["state"] != "verified":
                    self.budget.unverified_host(row, serving)
                    host_error = f"Serving provider {serving['state']}, not proved {serving['upstream']}"
                else:
                    u = p.get("usage") if isinstance(p.get("usage"), dict) else {}
                    costs = [c for c in (serving["total_cost"], u.get("cost"))
                             if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c)]
                    # The generation record's cost is required; the reply's usage.cost only raises it.
                    charged = max(costs) if serving["total_cost"] is not None else None
                    if not self.budget.charge(row, charged, serving):
                        host_error = "Charged cost not reconciled"
            else:
                serving = {"state": "direct", "endpoint": _safe(self.cfg.url.split("://", 1)[-1].split("/", 1)[0])}
            self.last_serving = serving
            if p.get("error"):
                raise DemoStop("Provider returned an error")
            if not isinstance(p.get("choices"), list) or len(p["choices"]) != 1:
                raise DemoStop("Response must contain exactly one choice")
            choice = p["choices"][0]
            if choice.get("error") or choice.get("finish_reason") == "error":
                raise DemoStop("Provider returned an error")
            if p.get("model") != self.cfg.model:
                raise DemoStop(f"Response model {_safe(p.get('model'))} is not the reviewed model; no fallback")
            text = (choice.get("message") or {}).get("content") or ""
            if not isinstance(text, str):
                raise DemoStop("Response content is not text")
            data = extract_json(text)
            finish = choice.get("finish_reason")
            if data is None or finish != "stop":
                self.budget.halt("Invalid, refused or truncated output")
                error = "Invalid, refused or truncated output; no repair"
            elif host_error is not None:
                error = f"{host_error}; {self.budget.halted}; response not used"
            elif not reconciled or self.budget.halted is not None:
                # Fail closed: a response whose cost could not be reconciled (or that
                # coincided with any halt) is never used, even if its JSON is valid.
                error = f"{self.budget.halted}; response not used"
            else:
                error = None
            ok = error is None
            # The model's text is kept as evidence; a failed result carries no data,
            # so none of its messages or actions can reach the exercise.
            return LLMResult(ok, data if ok else None, text, self.cfg.provider,
                             p["model"], int((time.monotonic() - started) * 1000), p.get("usage", {}),
                             error, request_id=rid, response_id=_safe(p.get("id")), finish_reason=_safe(finish))
        except Exception as e:
            # Raw provider bodies/transport exception strings can contain secrets:
            # only messages written by this module, or the exception type, are kept.
            reason = str(e) if isinstance(e, DemoStop) else type(e).__name__
            self.budget.halt(reason)
            return LLMResult(False, None, "", self.cfg.provider, self.cfg.model,
                             int((time.monotonic() - started) * 1000), {},
                             f"{reason}: live turn failed; no retry")


def openrouter_preflight(http, key: str, profile: dict, cap_usd: float, input_price: float,
                         output_price: float, worst_total: float) -> dict:
    """Free, read-only checks before any paid request (GET only; no completion):
    the key must carry a credit limit no higher than the plan cap that still covers the
    worst case; the key must be able to read generation records (host proof); and the
    model's endpoint list must show the pinned host at prices no higher than the
    plan's, with the parameters and room the profile needs."""
    problems, evidence = [], {}
    headers = {"Authorization": f"Bearer {key}"}

    def get(url):
        try:
            r = http.get(url, headers=headers)
            data = r.json().get("data") if r.status_code == 200 else None
            return r.status_code, data
        except Exception as e:                  # never echo bodies or exception text
            return type(e).__name__, None

    status, d = get(OPENROUTER_KEY_URL)
    if not isinstance(d, dict):
        problems.append(f"Key check failed ({status})")
    else:
        evidence["key"] = {k: d.get(k) for k in ("limit", "limit_remaining", "limit_reset", "usage",
                                                 "include_byok_in_limit", "is_free_tier")
                           if d.get(k) is None or isinstance(d.get(k), (int, float, bool))
                           or _safe(d.get(k))}
        limit, remaining = d.get("limit"), d.get("limit_remaining")
        if "limit_reset" not in d or d["limit_reset"] is not None:
            problems.append("Dedicated key must explicitly report limit_reset as null")
        if not _positive(limit):
            problems.append("The API key has no credit limit; set one as the backstop")
        elif limit > cap_usd:
            problems.append(f"Key credit limit USD {limit} is above the plan cap USD {cap_usd}")
        elif limit < worst_total:
            problems.append("Key credit limit cannot fund one complete attempt")
        if not _positive(remaining) or remaining < worst_total:
            problems.append(f"Key credit remaining is below the worst case USD {worst_total:.4f}")
        elif _positive(limit) and remaining > limit:
            problems.append("Key credit remaining exceeds its limit")

        # OpenRouter reports the tightest enforced budget, including shared guardrails.
        layers = d.get("budgets")
        if "effective_budget" not in d or not isinstance(layers, list):
            problems.append("Missing effective budget or invalid budget list")
        elif d["effective_budget"] is None:
            evidence["key"]["effective_remaining_usd"] = None
            if layers or limit is not None or remaining is not None:
                problems.append("Null effective budget conflicts with a reported budget or key limit")
        else:
            budget = d["effective_budget"]
            available = budget.get("remaining_usd") if isinstance(budget, dict) else None
            balances = [layer.get("remaining_usd") if isinstance(layer, dict) else None for layer in layers]
            if not _positive(available) or not balances or not all(_positive(value) for value in balances):
                problems.append("Invalid or exhausted effective budget or budget layer")
            elif available != min(balances) or budget not in layers or (_positive(remaining) and available > remaining):
                problems.append("Effective budget is inconsistent with the budget layers or key credit")
            elif available < worst_total:
                problems.append("Effective spending budget cannot fund one complete attempt")
            else:
                evidence["key"]["effective_remaining_usd"] = available

    # Host proof needs the generation record. An unknown id must come back "not found"
    # (the key may read records), not 401/403 (it may not: every reply would then fail).
    try:
        gen_status = http.get(f"{bench.OPENROUTER_GENERATION}?id={PREFLIGHT_GENERATION_ID}",
                              headers=headers).status_code
    except Exception as e:
        gen_status = type(e).__name__
    evidence["generation_record_access"] = {"probe_status": gen_status}
    if gen_status != 404:
        problems.append(f"Cannot confirm generation-record access ({gen_status}); expected 404 for the unknown id")

    status, d = get(OPENROUTER_ENDPOINTS_URL.format(model=profile["model"]))
    eps = d.get("endpoints") if isinstance(d, dict) else None
    if not isinstance(eps, list):
        problems.append(f"Endpoint list failed ({status})")
        eps = []
    up = profile["upstream"].lower()
    pinned = [e for e in eps if isinstance(e, dict) and str(e.get("provider_name", "")).lower() == up]
    if not pinned:
        problems.append(f"No {profile['upstream']} endpoint is listed for {profile['model']}")
    cap = profile["request"]["max_completion_tokens"]
    evidence["endpoints"] = []
    for e in pinned:
        pr = e.get("pricing") if isinstance(e.get("pricing"), dict) else {}
        sp = {x for x in e.get("supported_parameters") or [] if isinstance(x, str)}
        evidence["endpoints"].append({
            "provider_name": _safe(e.get("provider_name")), "tag": _safe(e.get("tag")),
            "pricing": {k: _safe(v) for k, v in pr.items() if isinstance(v, (str, int, float))},
            "context_length": e.get("context_length"), "max_completion_tokens": e.get("max_completion_tokens"),
            "supported_parameters": sorted(x for x in sp if _safe(x)), "status": e.get("status"),
            "uptime_last_30m": e.get("uptime_last_30m"), "quantization": _safe(e.get("quantization"))})
        try:
            pin, pout = float(pr["prompt"]) * 1e6, float(pr["completion"]) * 1e6
            fees = [float(pr[k]) for k in ("request", "image", "web_search") if k in pr]
            # Reasoning is billed inside the output cap; a cache write may not cost more than input.
            dearer = [float(pr[k]) * 1e6 > limit + 1e-9 for k, limit in
                      (("internal_reasoning", pout), ("input_cache_write", pin)) if k in pr]
        except (KeyError, TypeError, ValueError):
            problems.append("Pinned endpoint price is unreadable")
            continue
        if pin > input_price + 1e-9 or pout > output_price + 1e-9:
            problems.append(f"Pinned endpoint price USD {pin:g} / {pout:g} per million is above the plan's")
        if any(x > 0 for x in fees) or any(dearer):
            problems.append("Pinned endpoint has a charge the reservation does not cover")
        if not {"response_format", "max_tokens"} <= sp or not sp & {"reasoning", "reasoning_effort"}:
            problems.append("Pinned endpoint does not list response_format, max_tokens and reasoning")
        ctx, mct = e.get("context_length"), e.get("max_completion_tokens")
        if not _count(ctx) or ctx < PROMPT_BYTE_LIMIT + FRAMING_TOKENS + cap:
            problems.append("Pinned endpoint context is too small for the largest prompt plus the cap")
        if mct is not None and (not _count(mct) or mct < cap):
            problems.append("Pinned endpoint output limit is below the profile cap")
    return {"ok": not problems, "problems": problems, "evidence": evidence}
