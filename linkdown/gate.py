"""Deterministic authority gate (an engineering adaptation of the policy ("P") node of
ITU-T Y.3172 (06/2019), clause 8.1; see that Recommendation for its definition).

The language models only PROPOSE actions. This module decides, without any model
call, whether a proposal is PERMITTED, PROHIBITED or INSUFFICIENT_AUTHORITY_OR_EVIDENCE.
It is an exercise rule engine, not a statement of UAE law and not a legal authority.

Safety properties (tested in tests/test_gate.py):
  1. Facts come from the authoritative exercise state, never from the model's
     arguments. A model cannot make confidential records "baseline" by saying so.
  2. A legal rule (prohibition OR permission) takes effect only when its clause is VERIFIED:
     the rule says primary_verified AND it points to a complete entry in the
     verification ledger (section, page, verbatim quote, two named human
     verifiers, date, and the sha256 of the source file, which must match the
     fetch manifest). Otherwise the gate escalates (INSUFFICIENT). Every decision also
     carries legal_status; NOT_ASSESSED means an exercise (sandbox) permission only,
     never a statement that an action is lawful in the UAE.
  3. Nothing the model writes, and nothing in the knowledge base, can mark a rule
     as verified: the gate reads only config/rules.yaml, kb/verification_ledger.yaml
     and kb/build/fetch_manifest.json, all reviewed files in the repository.
  4. Approval classes: PROHIBITED cannot be approved; PERMITTED high-impact actions
     need an OPERATIONAL approval; INSUFFICIENT needs a (simulated) COMPETENT-AUTHORITY
     decision with a written basis. An operational click never counts as legal authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PERMITTED = "PERMITTED"
PROHIBITED = "PROHIBITED"
INSUFFICIENT = "INSUFFICIENT_AUTHORITY_OR_EVIDENCE"
OUTCOMES = (PERMITTED, PROHIBITED, INSUFFICIENT)

APPROVAL_NONE = "none"
APPROVAL_OPERATIONAL = "operational"
APPROVAL_AUTHORITY = "competent_authority"

ROOT = Path(__file__).resolve().parent.parent
LEDGER_FIELDS = ("source_id", "section", "page", "quote", "verified_by", "verified_on", "source_sha256")
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class RuleHit:
    rule_id: str
    kind: str            # legal | exercise
    effect: str          # PERMITTED | PROHIBITED | INSUFFICIENT_... | note
    explain: str
    source: str | None = None
    clause: str | None = None
    verification: str | None = None
    ledger: str | None = None
    verified: bool = False
    downgraded: bool = False

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, False)}


@dataclass
class Decision:
    outcome: str
    requires_human: bool
    facts: dict
    trail: list[RuleHit] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    approval: str = APPROVAL_NONE
    legal_status: str = "NOT_ASSESSED"
    state_version: int | None = None
    state_digest: str | None = None
    action_id: str | None = None

    @property
    def summary(self) -> str:
        lead = next((h for h in self.trail if h.effect not in ("note",)), None)
        why = lead.explain if lead else "No rule covers this action."
        extra = {APPROVAL_OPERATIONAL: " Operational approval required.",
                 APPROVAL_AUTHORITY: " Needs a competent-authority decision with a written basis."}.get(self.approval, "")
        return f"{self.outcome}: {why}{extra}"

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "requires_human": self.requires_human, "approval": self.approval,
                "legal_status": self.legal_status,
                "facts": self.facts, "conditions": self.conditions,
                "trail": [h.as_dict() for h in self.trail], "summary": self.summary,
                "state_version": self.state_version, "state_digest": self.state_digest,
                "action_id": self.action_id}


def action_id(role: str, tool: str, args: dict, state_version: int | None) -> str:
    raw = json.dumps([role, tool, args, state_version], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def ledger_problems(entry: dict | None, rule: dict, manifest: dict) -> list[str]:
    """Why a ledger entry does not (yet) prove a clause. Empty list = verified."""
    if not entry:
        return ["no verification-ledger entry"]
    out = [f"missing {f}" for f in LEDGER_FIELDS if not entry.get(f)]
    if entry.get("source_id") and entry["source_id"] != rule.get("source"):
        out.append("ledger entry is for a different source")
    if len(set(entry.get("verified_by") or [])) < 2:
        out.append("needs two different human verifiers")
    sha = str(entry.get("source_sha256") or "")
    if sha and not _SHA.match(sha):
        out.append("source_sha256 is not a sha256 hex digest")
    rec = (manifest.get(rule.get("source")) or {}).get("sha256")
    if not rec:
        out.append("source file hash not on record in the fetch manifest")
    elif sha and rec != sha:
        out.append("source file hash does not match the fetch manifest")
    return out


class Gate:
    def __init__(self, rules: dict, ledger: dict | None = None, manifest: dict | None = None):
        self.version = rules["version"]
        self.perms: dict[str, list[str]] = rules["tool_permissions"]
        self.legal: list[dict] = rules["legal"]
        self.exercise: list[dict] = rules["exercise"]
        self.ledger = {e["id"]: e for e in (ledger or {}).get("entries", []) or []}
        self.manifest = manifest or {}
        # Verification is decided once, at load time, from reviewed files only.
        self.verified: dict[str, bool] = {}
        self.verification_notes: dict[str, list[str]] = {}
        for r in self.legal:
            if r.get("verification") != "primary_verified":
                self.verified[r["id"]] = False
                continue
            probs = ledger_problems(self.ledger.get(r.get("ledger")), r, self.manifest)
            self.verified[r["id"]] = not probs
            self.verification_notes[r["id"]] = probs

    @classmethod
    def load(cls, path: str | Path, ledger_path: str | Path | None = None,
             manifest_path: str | Path | None = None) -> "Gate":
        rules = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        lp = Path(ledger_path) if ledger_path else ROOT / "kb/verification_ledger.yaml"
        mp = Path(manifest_path) if manifest_path else ROOT / "kb/build/fetch_manifest.json"
        ledger = yaml.safe_load(lp.read_text(encoding="utf-8")) if lp.exists() else {}
        manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
        return cls(rules, ledger, manifest)

    # -- facts -----------------------------------------------------------
    @staticmethod
    def derive_facts(role: str, tool: str, args: dict, state: Any) -> dict:
        """Build gate facts from the authoritative state. Model arguments are only
        used to pick WHICH object the action refers to, never its properties."""
        facts: dict[str, Any] = {"role": role, "tool": tool}
        if tool == "transfer_records":
            rs = state.record_sets.get(args.get("record_set", ""))
            dest = state.regions.get(args.get("dest_region", ""))
            facts["record_set_known"] = rs is not None
            facts["dest_known"] = dest is not None
            if rs is not None:
                facts["data_class"] = rs["data_class"]
                facts["personal_data"] = rs["personal_data"]
            if dest is not None:
                facts["dest_in_uae"] = bool(dest["in_uae"])
                facts["keys_in_uae"] = bool(dest["in_uae"] or state.service.get("hold_your_own_key_in_uae", False))
            facts["entity_type"] = state.service["entity_type"]
        elif tool == "switch_ai_endpoint":
            ep = state.endpoints.get(args.get("region", ""))
            facts["dest_known"] = ep is not None
            if ep is not None:
                facts["dest_available"] = bool(ep.get("available", False))
            facts["moves_records"] = bool(ep is not None and ep.get("needs") == "full_records"
                                          and args.get("region") != state.service.get("records_region"))
        elif tool == "set_service_mode":
            facts["mode"] = args.get("mode")
        return facts

    # -- matching --------------------------------------------------------
    @staticmethod
    def _matches(when: dict, facts: dict) -> bool:
        for key, want in (when or {}).items():
            if key not in facts:
                return False
            have = facts[key]
            if isinstance(want, list):
                if have not in want:
                    return False
            elif have != want:
                return False
        return True

    def decide(self, role: str, tool: str, args: dict, state: Any) -> Decision:
        facts = self.derive_facts(role, tool, args, state)
        version = getattr(state, "version", None)
        digest = state.digest() if hasattr(state, "digest") else None
        stamp = {"state_version": version, "state_digest": digest,
                 "action_id": action_id(role, tool, args, version)}

        if tool not in self.perms.get(role, []):
            rule = next(r for r in self.exercise if r["id"] == "ER-ROLE")
            hit = RuleHit("ER-ROLE", "exercise", PROHIBITED, rule["explain"])
            return Decision(PROHIBITED, False, facts, [hit], **stamp)

        if facts.get("record_set_known") is False or facts.get("dest_known") is False:
            hit = RuleHit("ER-UNKNOWN-OBJECT", "exercise", PROHIBITED,
                          "The action refers to a record set or region that does not exist in the exercise state.")
            return Decision(PROHIBITED, False, facts, [hit], **stamp)

        trail: list[RuleHit] = []
        conditions: list[str] = []
        requires_human = False

        for r in self.legal:
            if not self._matches(r.get("when", {}), facts):
                continue
            ok = self.verified.get(r["id"], False)
            hit = RuleHit(r["id"], "legal", r["effect"], r["explain"], r.get("source"),
                          r.get("clause"), r.get("verification"), r.get("ledger"), ok)
            if r["effect"] in (PROHIBITED, PERMITTED) and not ok:
                # Symmetric: an unverified source can neither prohibit nor permit as law.
                hit.downgraded = True
                verb = "prohibiting" if r["effect"] == PROHIBITED else "permitting"
                if r.get("verification") == "primary_verified":
                    why = "; ".join(self.verification_notes.get(r["id"], []))
                    hit.explain += (f" [Marked primary_verified but not proven ({why}),"
                                    f" so the gate escalates instead of {verb}.]")
                else:
                    hit.explain += (" [Indicated by a source not yet checked against the primary text,"
                                    f" so the gate escalates instead of {verb}.]")
            trail.append(hit)
            conditions += r.get("conditions", [])

        for r in self.exercise:
            if r["id"] == "ER-ROLE" or not self._matches(r.get("when", {}), facts):
                continue
            trail.append(RuleHit(r["id"], "exercise", r["effect"], r["explain"]))
            requires_human |= bool(r.get("requires_human"))
            conditions += r.get("conditions", [])

        effects = [h for h in trail if h.effect != "note"]
        if any(h.effect == PROHIBITED and not h.downgraded for h in effects):
            outcome = PROHIBITED
        elif any(h.effect == INSUFFICIENT or h.downgraded for h in effects):
            outcome = INSUFFICIENT
        elif any(h.effect == PERMITTED for h in effects):
            outcome = PERMITTED
        else:
            trail.append(RuleHit("ER-NO-RULE", "exercise", INSUFFICIENT,
                                 "No rule covers this action, so it is escalated rather than allowed."))
            outcome = INSUFFICIENT

        if outcome == PROHIBITED:
            requires_human, approval = False, APPROVAL_NONE        # cannot be approved away
        elif outcome == INSUFFICIENT:
            requires_human, approval = True, APPROVAL_AUTHORITY    # never an ordinary click
        else:
            approval = APPROVAL_OPERATIONAL if requires_human else APPROVAL_NONE

        legal = [h for h in trail if h.kind == "legal" and h.effect != "note"]
        if any(h.effect == PROHIBITED and h.verified for h in legal):
            legal_status = "VERIFIED_PROHIBITED"
        elif any(h.downgraded or h.effect == INSUFFICIENT for h in legal):
            legal_status = "UNVERIFIED_OR_INSUFFICIENT"
        elif legal and all(h.verified for h in legal):
            legal_status = "VERIFIED_PERMITTED"
        else:
            legal_status = "NOT_ASSESSED"   # exercise rule only: a sandbox permission, not a legal finding

        rank = {PROHIBITED: 0, INSUFFICIENT: 1, PERMITTED: 2, "note": 3}
        trail.sort(key=lambda h: (rank.get(INSUFFICIENT if h.downgraded else h.effect, 9), h.kind != "legal"))
        return Decision(outcome, requires_human, facts, trail, sorted(set(conditions)), approval,
                        legal_status, **stamp)
