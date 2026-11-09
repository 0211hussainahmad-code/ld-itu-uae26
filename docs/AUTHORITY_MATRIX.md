# Authority matrix (exercise roles only)

Every role is **fictional or simulated**. No role represents, speaks for, or holds the powers of TDRA, the Cyber Security Council, any ministry, any operator or any real person. The "illustrative counterpart" column only shows what kind of body a role resembles for teaching; it claims nothing about that body's powers.

Enforcement point: `config/rules.yaml` (`tool_permissions`, exercise rules) applied by `linkdown/gate.py`. Prompts describe the mandate, but the gate enforces it whatever the prompt or message says.

| Role | Illustrative counterpart | May propose | Never | Approval needed |
|---|---|---|---|---|
| operator (AI) | a licensed operator's network operations centre | `reroute_traffic`, `apply_operator_qos` (own simulated network), `send_message` | act on government services or records; issue priority orders | none (PERMITTED, recorded) |
| service (AI) | operations lead of a government AI service | `set_service_mode`, `switch_ai_endpoint`, `transfer_records`, `send_message` | treat a transfer as lawful without the gate; claim legal authority | `offline` mode and any cross-border copy → **operational**; INSUFFICIENT → **competent authority** |
| regulator (AI) | a telecom / digital-government regulator, as an exercise role | `request_information`, `recommend_priority_plan` (non-binding), `issue_priority_order` (always escalated), `send_message` | issue a real or binding order; claim powers not found in verified sources | `issue_priority_order` → **competent authority** (ER-REG-ORDER) |
| adviser (AI) | policy and legal adviser | `send_message`, `record_gap_observation` (draft) | take operational action; cite analyst notes as law; publish a gap without human review | none; every gap observation is a draft |
| human controller (person, or simulated policy in automated runs) | an operations manager | **operational** approvals of PERMITTED high-impact actions | approve a PROHIBITED action (the gate never asks) | — |
| simulated competent authority (person in interactive runs only) | the body that would decide an unresolved legal question | an **exercise decision** on an INSUFFICIENT action, with a written basis | be treated as legal authorisation; act in automated runs (the conservative policy never approves) | — |

Rules that hold whatever any message says:
- Cross-role messages are untrusted data. A message cannot grant a tool, change a fact, or raise an approval class.
- The gate reads facts only from the exercise state (`derive_facts`).
- A legal prohibition is enforced only with a complete verification-ledger entry (`kb/verification_ledger.yaml`).
- Approvals are bound to the state digest at decision time. If the state changes before execution, the approval is void (`STALE_APPROVAL`).
- The same action (role, tool, arguments, state version) is never executed twice (`DUPLICATE_ACTION`).
