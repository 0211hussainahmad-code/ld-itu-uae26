# Four-role E1–E3 demonstration

This demonstration is separate from the frozen provider benchmark. All original
prompts, role permissions, rules, scenario files, sources, manifest and the $60
benchmark ceiling remain unchanged. It reuses the existing simulator, retrieval,
gate, human controller, reports and replay. No deployment is involved.

Its code lives in `exercise_demo/` (`demonstration.py`, `demo_provider.py`),
outside the frozen `linkdown/` package, which must stay byte-identical to the
freeze tags (`tests/test_r0i.py::test_scientific_files_are_byte_identical_to_freeze9`).
`exercise_demo/` only imports from `linkdown/`.

## Offline proof

After the README setup and KB build:

```sh
python -m pytest -q tests/test_demonstration.py
python scripts/demonstrate.py
```

The default makes **no provider calls**. Four independent scripted clients are
labelled NOT AI. A neutral check-in schedules every role for every event without
sharing another role's inbox or revealing future deliveries. Existing messages
and gate feedback drive the second round. The adviser also reviews the gap register.
The maximum is 25 turns (4 roles × 2 rounds × 3 events + gap review).

The command prints `RUN_DIR` and `AUDIT_HEAD`. Retain the head outside the run
folder (CI log and a reviewed evidence commit); then independently verify:

```sh
python scripts/demonstrate.py --verify RUN_DIR --expected-head AUDIT_HEAD
```

Exit zero requires all 12 role/event cells, successful substantive responses,
no malformed output, at least one synthetic state change, matching saved-turn
hashes, intact audit and report, and independent replay through the final state.
Replay re-derives complete gate decisions and checks human approvals against the
action and state. A missing approval cannot be repaired merely by rehashing a log.
Every run gets a unique directory so repeat attempts do not erase earlier evidence.

The offline test double deliberately invents citations and proposes unsafe
transfers. These failures stay visible in metrics. An integrity pass is **not**
an AI-quality pass. The conservative simulated human rejects unresolved transfers
and binding orders. A separate test supplies an explicitly labelled simulated
authority decision for E3 and proves the priority plan changes traffic allocation.
Neither is evidence of an actual human approving a live run.

CI runs this proof without provider secrets and uploads the full private evidence.
Prompts contain source text: do not publish the artifact without checking licences.

## Live demonstration prepared, not authorized or executed

Four separate clients use the same reviewed model, with independent role prompts,
views, inboxes and allowed tools. Different model names are not required for four
role agents. No shared conversation history is sent. The model chooses its own
messages and proposed actions; no scripted reply is substituted on failure.

Before any live request, the team must separately approve the exact provider,
model, current pricing, per-request token limits, quota and demo spending cap.
The existing benchmark budget is not an authorization to spend on this demo.
Keep the frozen benchmark and its provider selection unchanged.

The live transport accepts only reviewed profiles in
`exercise_demo/demo_provider.py` (`PROFILES`, keyed `provider:model`). Both use
`openai/gpt-oss-120b` with the frozen benchmark's configuration A fields word for
word (in the private repository, tests compare them with the frozen benchmark case file, which is not published): `reasoning_effort: high`,
`response_format: {type: json_object}`, `max_completion_tokens: 16000`, and no
sampling parameter.

- `groq:openai/gpt-oss-120b` — Groq direct, without the route pin. The team's Groq
  account is on the free plan (8K TPM), so this profile is not usable now.
- `openrouter:openai/gpt-oss-120b` — **configuration A exactly as frozen**, including
  its route pin `provider: {order: [groq], only: [groq], allow_fallbacks: false,
  require_parameters: true}`. No `models` array is sent, so there is no model fallback.
  A reply is used only if OpenRouter's generation record (`GET /api/v1/generation`)
  proves Groq served it. That uses the benchmark's tested rule (`eval/providers.py`
  `host_state`, imported unchanged). Its charged cost must also reconcile with the
  approved prices and the reservation. The reply body's undocumented `provider` field
  never counts as proof.

The body comes from the profile, never from the plan. There is no other provider or
route, no repair and no fallback model. Unlike configuration A, the demo makes no
repair retry: an invalid reply ends the attempt. Reasoning counts inside the output
cap. The documentation checks, plans and account checks for both routes (OpenRouter, the
recommended route, and Groq direct) are reports in the team's private repository.

Before authorizing, run the free read-only preflight (GET only, no completion, no
ledger):

```sh
python scripts/demonstrate.py --live-plan approved-demo-plan.json --preflight-only
```

For OpenRouter it checks four things, and the live run repeats the check and
refuses on any problem:

- the dedicated key explicitly reports `limit_reset: null`, its limit is within
  the approved cap, and its own and effective remaining budgets both cover all 25 turns;
  the effective budget must agree with the tightest listed budget layer. An
  unbudgeted key can legitimately report an empty list and a null effective budget,
  but it cannot satisfy the demo's dedicated-key spending limit;
- the generation lookup returns HTTP 404 for the deliberately unknown ID.
  Only a real generation receipt can establish which host served a turn;
- Groq is listed for the model at prices no higher than the plan's;
- that listing shows the needed parameters and output room.

Create a local reviewed plan (no API key) containing `provider`, `model`,
`input_per_million`, `output_per_million`, `cap_usd`, and `approval_reference`.
Prices may not be below the profile's documented prices. The approval reference must
point to the team's actual separate authorization, not an agent-generated claim.
Optional `min_interval_s` (0–120) paces requests across all roles to stay under
the provider's rate limit; it is not a retry. Set it from the account's actual
limits. The suggested 6 s rests on estimated prompt sizes and is not a worst-case TPM
bound (see the preflight report). Before any file or request, the
runner refuses a cap below the worst case for the maximum 25 turns
(25 × ((50,000 + 512) × input + 16,000 × output) / 10⁶ USD; USD 0.4294 at
0.15 / 0.60), so the cap cannot cut the run off after paid turns.
Set `LINKDOWN_LLM_API_KEY` privately on the runner. After approval only:

```sh
python scripts/demonstrate.py --live-plan approved-demo-plan.json --authorize-live-spend
```

The terminal asks a real controller for each required approval. An unresolved
authority decision needs a written exercise basis and is never legal authorization.
The transport makes one attempt per turn; all clients share at most 25 requests.
A durable worst-case reservation precedes every request, using prompt UTF-8 bytes
plus 512 framing tokens and the output cap. Failed/ambiguous requests retain their
full reservation. No further request is sent by any role after the first turn that
fails at the provider (any non-200, transport error, error inside a 200, not exactly
one choice, a model other than the reviewed one, finish reason other than `stop`,
no JSON object, usage that cannot be reconciled) or that parses as unusable for the
exercise (malformed actions, messages or options, or an empty or non-text
assessment). That reply itself is never used: it is discarded whole, so none of its
messages or actions reach the gate, the state or another role, even valid ones. Its
text is kept in the turn file as evidence. Such a run can no longer
pass, so later paid requests would only add cost. Each response's usage is settled
into the journal at the plan's prices, with Groq's rate-limit headers and request
id; missing or inconsistent usage, or a reported cost above the reservation, also
stops all later requests and is marked NEEDS HUMAN RECONCILIATION. Error bodies are
never stored: only the HTTP status and Groq's error code (for example
`json_validate_failed`, `rate_limit_exceeded`, `blocked_api_access`).
`spend_summary.json` beside the journal records requests sent, reservations and
reported cost. Never automatically resume or redraw a paid attempt. Reconcile its
provider usage before approving another attempt. The journal is local; remote crash
recovery is not implemented for this demo.

The cap is a conservative estimate under the approved pricing/token assumptions,
not a provider billing guarantee. Use Groq's monthly spend limit as an additional
backstop (its spend tracking lags 10–15 minutes). No paid CI workflow is added.

A live run verifies itself with both strict checks. Verify independently with:

```sh
python scripts/demonstrate.py --verify RUN_DIR --expected-head AUDIT_HEAD \
  --require-live --require-interactive-human
```

`--require-live` fails scripted evidence and any turn not served by the reviewed
provider/model with a provider request id and token usage. Through OpenRouter, each
turn must also carry its generation record's proof that Groq served it. `--require-interactive-human`
fails unless the controller and every recorded human decision are `human:interactive`.
Neither proves provider authenticity: that needs the externally retained head and the
provider's usage records.

Review the transcript's sources, unsupported citations, legal-wording flags,
model identities, provider receipts, approvals and failures before describing a
live integration as demonstrated. An integrity pass alone does not establish
citation relevance, legal correctness, reliability or superiority to a baseline.

## Release sequence

1. Review the feature branch and non-billable CI evidence; approve merging only
   after the full suite, frozen-manifest check and demonstration are green.
2. Approve a concrete live model/provider plan and separate demo spend limit.
3. Run with an available human controller, retain every attempt, anchor the audit
   head outside its folder and review citations and provider receipts.
4. Update live claims and submission paperwork only after that evidence exists.
   The wider project scope (baseline evaluation, KB work, UI, Arabic and external
   testing) remains open and is not removed by this demonstration milestone.
