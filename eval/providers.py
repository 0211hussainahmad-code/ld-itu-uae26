"""Bake-off provider adapters (T09b; GPT-6 R0b R15, R0c 2-3).

The request body for each configuration is built ONLY from the frozen case file
(`configs.<name>.request`) plus the model id and the messages: nothing is added,
renamed or dropped here. `validate()` is the static half of the operational preflight:
it rejects a parameter set that breaks the frozen protocol before any call is made.

Keys come from the environment and are never logged:
  GROQ:       LINKDOWN_GROQ_API_KEY, else LINKDOWN_LLM_API_KEY (the live workflow's secret)
  ANTHROPIC:  ANTHROPIC_API_KEY
  OPENROUTER: OPENROUTER_API_KEY

OpenRouter (bakeoff-cases-0.6, DECISIONS D15) carries config A's frozen request body word
for word (reasoning_effort, response_format, max_completion_tokens) plus a provider pin
that allows exactly one upstream host and no fallback. Which host served a request is
confirmed through OpenRouter's generation-stats endpoint (provider_name).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from deadline_process import run as bounded_http_run

ROOT = Path(__file__).resolve().parent.parent
URLS = {"groq": "https://api.groq.com/openai/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "openrouter": "https://openrouter.ai/api/v1/chat/completions"}
OPENROUTER_GENERATION = "https://openrouter.ai/api/v1/generation"
ANTHROPIC_VERSION = "2023-06-01"
RETRY_STATUS = (429, 500, 502, 503, 504, 529)


def resolve(value):
    """Replace {$file, $key} references (the A-strict schema) with the frozen file's content."""
    if isinstance(value, dict):
        if set(value) == {"$file", "$key"}:
            return json.loads((ROOT / value["$file"]).read_text(encoding="utf-8"))[value["$key"]]
        return {k: resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v) for v in value]
    return value


def validate(name: str, cfg: dict) -> list[str]:
    """Problems with one configuration's frozen parameter set (empty = valid)."""
    req, prov, out = cfg.get("request") or {}, cfg.get("provider"), []
    if prov not in URLS:
        return [f"{name}: unknown provider {prov!r}"]
    for banned in ("temperature", "top_p", "top_k"):
        if banned in req:
            out.append(f"{name}: {banned} must not be sent (same_for_all)")
    if prov == "openrouter":
        pin = req.get("provider") or {}
        slug = cfg.get("upstream_slug")
        if not cfg.get("upstream") or not slug:
            out.append(f"{name}: an OpenRouter config must name its single upstream host (upstream, upstream_slug)")
        elif pin != {"order": [slug], "only": [slug], "allow_fallbacks": False, "require_parameters": True}:
            out.append(f"{name}: provider pin must be order=only=[{slug}], allow_fallbacks false, require_parameters true")
        if "reasoning" in req:
            out.append(f"{name}: use reasoning_effort only (the frozen config A field), not a reasoning object")
    if prov in ("groq", "openrouter"):
        if req.get("max_completion_tokens") != 16000 or "max_tokens" in req:
            out.append(f"{name}: Groq needs max_completion_tokens 16000 and no deprecated max_tokens (R0c 3)")
        if req.get("reasoning_effort") != "high":
            out.append(f"{name}: reasoning_effort must be high (R15)")
        rf = resolve(req.get("response_format") or {})
        if rf.get("type") == "json_schema":
            js = rf.get("json_schema") or {}
            if not (js.get("name") and js.get("strict") is True and isinstance(js.get("schema"), dict)):
                out.append(f"{name}: json_schema needs name, strict: true and a schema object (R0c 2)")
            else:
                out += [f"{name}: {p}" for p in strict_problems(js["schema"])]
        elif rf.get("type") != "json_object":
            out.append(f"{name}: response_format must be json_object or a strict json_schema")
    if prov == "anthropic":
        if req.get("max_tokens") != 16000 or "max_completion_tokens" in req:
            out.append(f"{name}: Anthropic needs max_tokens 16000")
        if (req.get("output_config") or {}).get("effort") != "high":
            out.append(f"{name}: output_config.effort must be high (R15)")
        if "thinking" in req:
            out.append(f"{name}: thinking must be omitted (adaptive default; Opus 5.5 rejects disabling it)")
    if cfg.get("price_usd_per_mtok", {}).get("output") is None:
        out.append(f"{name}: no published output price for the spend guard")
    return out


def strict_problems(schema: dict, path: str = "$") -> list[str]:
    """Groq strict mode: every object closed, every property required (structured-outputs docs)."""
    out = []
    t = schema.get("type")
    if t == "object" or (isinstance(t, list) and "object" in t):
        props = schema.get("properties") or {}
        if schema.get("additionalProperties") is not False:
            out.append(f"{path}: additionalProperties must be false")
        if sorted(schema.get("required") or []) != sorted(props):
            out.append(f"{path}: every property must be required")
        for k, v in props.items():
            out += strict_problems(v, f"{path}.{k}")
    if isinstance(schema.get("items"), dict):
        out += strict_problems(schema["items"], f"{path}[]")
    return out


def build(name: str, cfg: dict, messages: list[dict]) -> tuple[str, dict, dict]:
    """(url, headers WITHOUT the key, body). messages: [{"role": "system"|"user"|"assistant", "content": str}]."""
    req = resolve(copy.deepcopy(cfg["request"]))
    if cfg["provider"] in ("groq", "openrouter"):
        body = {"model": cfg["model"], "messages": messages, **req}
        return URLS[cfg["provider"]], {"Content-Type": "application/json"}, body
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    body = {"model": cfg["model"], "system": system, "messages": rest, **req}
    return URLS["anthropic"], {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION}, body


def auth(provider: str) -> dict:
    if provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY")
        return {"Authorization": f"Bearer {key}"} if key else {}
    if provider == "groq":
        key = os.environ.get("LINKDOWN_GROQ_API_KEY") or os.environ.get("LINKDOWN_LLM_API_KEY")
        return {"Authorization": f"Bearer {key}"} if key else {}
    key = os.environ.get("ANTHROPIC_API_KEY")
    return {"x-api-key": key} if key else {}


def loggable(body: dict) -> dict:
    """The literal request body with each message's text replaced by its sha256 and length.
    Rendered inputs contain copyrighted ITU text, so they are not committed; they are
    regenerated from the tag with `python eval/bakeoff.py --show <case>`."""
    b = copy.deepcopy(body)

    def h(text):
        return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "chars": len(text)}
    if isinstance(b.get("system"), str):
        b["system"] = h(b["system"])
    for m in b.get("messages", []):
        if isinstance(m.get("content"), str):
            m["content"] = h(m["content"])
    return b


@dataclass
class Reply:
    ok: bool
    text: str = ""
    reasoning: str = ""
    usage: dict = field(default_factory=dict)      # input_tokens, output_tokens (incl. reasoning), reasoning_tokens
    model: str = ""
    request_id: str | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    truncated: bool = False
    status: int = 0
    error: str | None = None
    upstream: str | None = None                   # OpenRouter: host named in the reply itself (if any)
    upstream_source: str | None = None            # "error_metadata" (documented) or "reply_body" (undocumented)
    stop_details: dict | None = None              # Anthropic classifier refusal: {type, category, explanation}
    latency_ms: int = 0
    retries: int = 0
    rate_limited: int = 0
    ambiguous: bool = False                       # the request may have reached the provider; no reply known


# exact phrases of Groq's JSON-validation failure (observed bodies), never generic schema words,
# so a request-side error (for example an invalid schema) stays an API error
JSON_FAIL_MARKERS = ("json_validate_failed", "see 'failed_generation'", "failed to generate json",
                     "failed to validate json.",     # observed 26 Oct: "Upstream error from Groq: Failed to validate JSON. Plea..."
                     "structured_generation_failed")


def failed_generation(payload) -> str | None:
    """The model's output when Groq rejected it as invalid JSON, else None.

    Groq's JSON-mode docs say only that the endpoint "will either return valid JSON or throw
    an error"; observed bodies carry code `json_validate_failed` and the output in
    `failed_generation` (sometimes empty). Through OpenRouter the upstream error arrives as
    error.metadata.raw, documented only as the provider's "verbatim payload" (string or
    object). So: take failed_generation wherever it is; if the error is recognisably a
    JSON-validation failure but carries no output, the reply text is empty ("")."""
    err = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(err, dict):
        return None
    if isinstance(err.get("failed_generation"), str):
        return err["failed_generation"]
    raw = (err.get("metadata") or {}).get("raw") if isinstance(err.get("metadata"), dict) else None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            inner = failed_generation(parsed)
            if inner is not None:
                return inner
    elif isinstance(raw, dict):
        inner = failed_generation(raw)
        if inner is not None:
            return inner
    blob = json.dumps(err, ensure_ascii=False).lower()
    return "" if any(m in blob for m in JSON_FAIL_MARKERS) else None


def json_failure(payload) -> str | None:
    """failed_generation() for both shapes seen through OpenRouter: an HTTP 400 error object,
    and (observed 26 Oct, openrouter-check run 40266850609) an HTTP 200 completion whose
    choices[0] has finish_reason "error" and error {code: 502, message: "Upstream error from
    Groq: Failed to validate JSON. ..."}."""
    if not isinstance(payload, dict):
        return None
    fg = failed_generation(payload)
    if fg is None and isinstance(payload.get("choices"), list) and payload["choices"]:
        ch = payload["choices"][0]
        if isinstance(ch, dict) and isinstance(ch.get("error"), dict):
            fg = failed_generation({"error": ch["error"]})
    return fg


def parsed_usage(provider: str, payload: dict) -> dict:
    """Missing/invalid counts stay unknown; only explicitly reported integers count.

    Keep partial valid counts as evidence. No provider has a no-charge exception.
    Malformed optional reasoning details must not discard a received answer.
    """
    u = payload.get("usage")
    u = u if isinstance(u, dict) else {}
    compatible = provider in ("groq", "openrouter")
    keys = ("prompt_tokens", "completion_tokens") if compatible else ("input_tokens", "output_tokens")
    counts = {}
    for target, source in zip(("input_tokens", "output_tokens"), keys):
        value = u.get(source)
        counts[target] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    details = u.get("completion_tokens_details" if compatible else "output_tokens_details")
    details = details if isinstance(details, dict) else {}
    counts["reasoning_tokens"] = details.get("reasoning_tokens" if compatible else "thinking_tokens")
    return counts


def parse(provider: str, status: int, headers: dict, payload: dict) -> Reply:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    fg = json_failure(payload) if provider in ("groq", "openrouter") and status in (200, 400) else None
    if fg is not None:
        # The model DID answer; its answer is invalid JSON. It is treated exactly like an
        # invalid reply from any provider (validator, then the one frozen repair), never as
        # a lost output that a resume or a transport retry could re-draw (0.6, DECISIONS D15).
        meta = (payload.get("error") or {}).get("metadata") if isinstance(payload.get("error"), dict) else None
        host = meta.get("provider_name") if isinstance(meta, dict) and isinstance(meta.get("provider_name"), str) else None
        src = "error_metadata" if host else None
        if host is None and isinstance(payload.get("provider"), str):
            host, src = payload["provider"], "reply_body"
        usage = parsed_usage(provider, payload)
        return Reply(True, text=fg, status=status, finish_reason="json_validate_failed", upstream=host,
                     upstream_source=src, usage=usage,
                     model=payload.get("model", "") if isinstance(payload.get("model"), str) else "",
                     request_id=h.get("x-request-id") or h.get("request-id"),
                     response_id=(payload.get("id") if isinstance(payload.get("id"), str) else None))
    if status != 200:
        msg = (payload.get("error") or {}).get("message") if isinstance(payload.get("error"), dict) else payload.get("error")
        return Reply(False, status=status, error=f"HTTP {status}: {str(msg or payload)[:400]}",
                     request_id=h.get("x-request-id") or h.get("request-id"))
    if provider in ("groq", "openrouter"):
        ch = (payload.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        rid = h.get("x-request-id") or ((payload.get("x_groq") or {}).get("id"))
        return Reply(True, text=msg.get("content") or "", reasoning=msg.get("reasoning") or "",
                     usage=parsed_usage(provider, payload),
                     model=payload.get("model", ""), request_id=rid, response_id=payload.get("id"),
                     finish_reason=ch.get("finish_reason"), truncated=ch.get("finish_reason") == "length", status=200,
                     upstream=(payload.get("provider") if isinstance(payload.get("provider"), str) else None)
                     if provider == "openrouter" else None,
                     upstream_source="reply_body" if provider == "openrouter" and isinstance(payload.get("provider"), str) else None)
    blocks = payload.get("content") or []
    return Reply(True, text="".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
                 reasoning="".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking"),
                 usage=parsed_usage(provider, payload),
                 model=payload.get("model", ""), request_id=h.get("request-id"), response_id=payload.get("id"),
                 finish_reason=payload.get("stop_reason"), truncated=payload.get("stop_reason") == "max_tokens", status=200,
                 stop_details=payload.get("stop_details") if isinstance(payload.get("stop_details"), dict) else None)


ATTEMPT_TIMEOUT_S = 600.0     # one HTTP attempt (connect + send + wait for the whole reply)


class NotSent(Exception):
    """The request never left this machine (no connection): safe to retry like a 5xx."""


class Ambiguous(Exception):
    """The request may have reached the provider (timeout or broken connection after sending):
    it may have been answered and billed, and no reply can be retrieved later. Never resent
    automatically (GPT-6 R0h-B1)."""


def http_transport(url: str, headers: dict, body: dict, timeout: float = ATTEMPT_TIMEOUT_S) -> tuple[int, dict, dict]:
    return _bounded_http("post", url, headers, body, timeout)


def _bounded_http(method, url, headers, body=None, timeout=60.0):
    """Bound the ENTIRE worker lifetime, including DNS, trickling reads and JSON parsing.

    The OS subprocess timeout terminates and reaps the worker; no request thread remains
    running after a timeout. A timed-out POST is ambiguous, never automatically redrawn.
    Process creation/termination still relies on a functioning host OS.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise TimeoutError("no HTTP budget remains")
    try:
        completed = bounded_http_run([sys.executable, str(ROOT / "eval/http_worker.py")],
                                   input=json.dumps({"method": method, "url": url, "headers": headers,
                                                     "body": body, "timeout": timeout}).encode("utf-8"),
                                   capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if method == "get":
            raise TimeoutError("generation lookup wall-clock budget exhausted") from None
        raise Ambiguous("HTTP worker wall-clock budget exhausted; outcome unknown") from None
    except OSError:
        if method == "get":
            raise TimeoutError("bounded generation lookup could not complete") from None
        raise Ambiguous("bounded HTTP worker failed; outcome unknown") from None
    try:
        result = json.loads(completed.stdout)
        if completed.returncode == 0 and "result" in result:
            return tuple(result["result"])
    except (ValueError, TypeError):
        result = {}
    if method == "get":
        raise TimeoutError("generation lookup failed without usable evidence")
    if result.get("error") == "NotSent":
        raise NotSent(result["detail"])
    raise Ambiguous(result.get("detail", "HTTP worker failed without a trustworthy reply"))


def call(name: str, cfg: dict, messages: list[dict], transport=http_transport, sleep=time.sleep,
         max_retries: int = 6, clock=time.monotonic, chain_deadline: float | None = None,
         attempt_timeout_s: float = ATTEMPT_TIMEOUT_S, before_attempt=None) -> tuple[Reply, dict]:
    """One attempt chain of a call: the request plus transport-level retries (429/5xx, or no
    connection), never a second attempt at the task. Returns (reply, loggable request).

    Time (GPT-6 R0h-B2): a retry is started only if waiting for it (Retry-After is honoured, never
    shortened) plus a whole attempt still ends before `chain_deadline`; otherwise the chain ends
    with an API error. `before_attempt()` runs before every attempt (the runner checks its
    deadline there) and may veto it with a reason. A transport failure after sending
    (Ambiguous) ends the chain at once with reply.ambiguous = True: it is never resent."""
    url, headers, body = build(name, cfg, messages)
    t0, retries, limited = clock(), 0, 0
    loggable_req = {"url": url, "headers": {**headers, "auth": "(from environment, not logged)"}, "body": loggable(body)}

    def ended(reason: str, status: int = 0) -> tuple[Reply, dict]:
        rep = Reply(False, status=status, error=reason)
        rep.latency_ms, rep.retries, rep.rate_limited = int((clock() - t0) * 1000), retries, limited
        return rep, loggable_req
    while True:
        if chain_deadline is not None and not math.isfinite(chain_deadline):
            return ended("not sent: invalid chain deadline")
        veto = before_attempt() if before_attempt else None
        if veto:
            return ended(f"not sent: {veto}")
        if chain_deadline is not None and clock() + attempt_timeout_s > chain_deadline:
            return ended("not sent: no time for a whole HTTP attempt")
        try:
            if transport is http_transport:
                status, rh, payload = transport(url, {**headers, **auth(cfg["provider"])}, body,
                                                timeout=attempt_timeout_s)
            else:  # injected offline fixtures use the original three-argument interface
                status, rh, payload = transport(url, {**headers, **auth(cfg["provider"])}, body)
        except NotSent as e:
            status, rh, payload = 0, {}, {"error": {"message": f"not sent ({e})"}}
        except Ambiguous as e:
            rep, req = ended(f"AMBIGUOUS: the request may have reached the provider ({e}); no reply received")
            rep.ambiguous = True
            return rep, req
        if cfg["provider"] == "openrouter" and status == 200 and json_failure(payload) is None:
            status = openrouter_error_status(payload) or status       # a JSON failure is a reply, never retried
        if (status in RETRY_STATUS or status == 0) and retries < max_retries:
            try:
                wait = max(1.0, float({k.lower(): v for k, v in rh.items()}.get("retry-after", "")))
            except ValueError:
                wait = float(min(60, 2 ** (retries + 1)))
            if chain_deadline is not None and clock() + wait + attempt_timeout_s > chain_deadline:
                return ended(f"HTTP {status}: no time left for a retry after {wait:.0f} s "
                             f"(Retry-After honoured; the chain budget ends first)", status)
            limited += status == 429
            retries += 1
            sleep(wait)
            continue
        if status == 0:
            return ended(str((payload.get("error") or {}).get("message")), 0)
        rep = parse(cfg["provider"], status, rh, payload)
        # Unknown usage, including JSON-validation failures, reaches Runner unchanged:
        # it retains the allowance and seals a hold instead of inventing reported counts.
        rep.latency_ms, rep.retries, rep.rate_limited = int((clock() - t0) * 1000), retries, limited
        return rep, loggable_req


def openrouter_error_status(payload: dict) -> int | None:
    """OpenRouter can answer HTTP 200 with an error object instead of a completion (an
    upstream failure after the headers were sent). Treat that as the error it is: its own
    code if it carries one, else 502, so it is retried like any upstream failure."""
    ch = (payload.get("choices") or [{}])[0] if isinstance(payload.get("choices"), list) else {}
    err = payload.get("error") if not payload.get("choices") else ch.get("error")
    if err is None and ch.get("finish_reason") != "error":
        return None
    code = err.get("code") if isinstance(err, dict) else None
    return code if isinstance(code, int) and 400 <= code < 600 else 502


def http_stream(url: str, headers: dict, body: dict, timeout: float = 600.0) -> tuple[int, dict, list[dict]]:
    """POST with stream: true; returns every server-sent JSON chunk (diagnostics only: the
    bake-off itself never streams)."""
    return _bounded_http("stream", url, headers, body, timeout)


def http_get(url: str, headers: dict, timeout: float = 60.0) -> tuple[int, dict, dict]:
    return _bounded_http("get", url, headers, timeout=timeout)


def host_state(entry: dict | None, upstream: str) -> str:
    """Host provenance of one OpenRouter reply (bakeoff-cases-0.9; GPT-6 R0f-2/3, R0g-2/3):
      "mismatch"   any evidence names another host, or the generation record lists an
                   attempt by another host -> an API error, never scored;
      "verified"   ONLY OpenRouter's generation record (GET /api/v1/generation): provider_name
                   is the pinned host AND provider_responses is a present, non-empty,
                   well-formed list (each entry a dict with a string provider_name and an
                   integer status), every attempt by the pinned host, and the statuses are
                   consistent with one serving result: exactly one status 200 for a normal
                   completion, at most one for a JSON-validation failure;
      "unverified" anything else (no record; missing/empty/malformed attempts; a reply with no
                   generation id; the reply-body `provider` field; error metadata): HOST_UNVERIFIED,
                   which never completes a run and withholds selection."""
    if not entry:
        return "unverified"
    up = upstream.lower()
    name = entry.get("provider_name")
    pr = entry.get("provider_responses")
    attempts = [a for a in pr if isinstance(a, dict)] if isinstance(pr, list) else []
    if (isinstance(name, str) and name.lower() != up) or any(
            isinstance(a.get("provider_name"), str) and a["provider_name"].lower() != up for a in attempts):
        return "mismatch"
    if entry.get("evidence") != "generation_record" or not isinstance(name, str):
        return "unverified"
    if not isinstance(pr, list) or not pr or len(attempts) != len(pr):
        return "unverified"
    if any(not isinstance(a.get("provider_name"), str) or not isinstance(a.get("status"), int)
           or isinstance(a.get("status"), bool) for a in attempts):
        return "unverified"
    served = sum(a["status"] == 200 for a in attempts)
    kind = entry.get("reply_kind")
    if kind == "completion":
        return "verified" if served == 1 else "unverified"
    if kind == "json_failure":
        return "verified" if served <= 1 else "unverified"
    return "unverified"


def served_by(gen_id: str, getter=http_get, sleep=time.sleep, tries: int = 8,
              deadline: float | None = None, clock=time.monotonic) -> tuple[str | None, dict]:
    """OpenRouter: (provider_name, stats) of a finished generation. The docs do not say how
    soon the record exists, so a miss is retried with backoff (2, 4, ... 14 s; 56 s in all)
    and the runner sweeps any still-unverified reply again after the cohort."""
    last: dict = {}
    deadline = clock() + 60.0 if deadline is None else deadline
    if not math.isfinite(deadline):
        return None, {"error": "invalid host lookup deadline"}
    for i in range(tries):
        remaining = deadline - clock()
        if remaining <= 0:
            return None, {"error": "host lookup wall-clock budget exhausted", "last": last}
        try:
            if getter is http_get:
                status, _, payload = getter(f"{OPENROUTER_GENERATION}?id={gen_id}", auth("openrouter"),
                                            timeout=min(60.0, remaining))
            else:
                status, _, payload = getter(f"{OPENROUTER_GENERATION}?id={gen_id}", auth("openrouter"))
        except TimeoutError:
            return None, {"error": "host lookup wall-clock budget exhausted"}
        if clock() > deadline:
            return None, {"error": "host lookup returned after its deadline"}
        if status == 200 and isinstance(payload.get("data"), dict):
            d = payload["data"]
            keep = {k: d.get(k) for k in ("provider_name", "model", "upstream_id", "is_byok", "total_cost",
                                          "upstream_inference_cost", "tokens_prompt", "tokens_completion",
                                          "native_tokens_prompt", "native_tokens_completion", "native_tokens_reasoning",
                                          "finish_reason", "native_finish_reason", "provider_responses")}
            return d.get("provider_name"), keep
        last = {"status": status, "error": str(payload)[:200]}
        wait = 2.0 * (i + 1)
        if i + 1 < tries:
            if clock() + wait >= deadline:
                return None, {"error": "no time for another host lookup", "last": last}
            sleep(wait)
    return None, last
