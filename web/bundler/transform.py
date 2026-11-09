"""Turn a verified run folder into a public replay bundle.

Only chain-covered audit records are published (as exact canonical strings). Turn
files are never opened: they hold prompts with third-party text. Context (topology,
roles, scenario) is taken from the repository at the source commit and must match the
fingerprints the run recorded in RUN_START.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from linkdown import provenance as _prov
from linkdown.scenario import apply_variation, load_yaml

from web.bundler.canonical import GENESIS, canonical_body, engine_hash, record_hash, sha256_hex
from web.bundler.schema import SCHEMA_ID, find_forbidden
from web.publication.licences import load_sources, source_id_of

ROOT = Path(__file__).resolve().parents[2]
CITE_ID = re.compile(r"^[a-z0-9][a-z0-9.-]*#[A-Za-z0-9._-]+$")
CITE_KEYS = ("cit", "retrieved")          # payload keys whose list values hold citation ids (cites, *_citations)
INSPECT_FIELDS = ("passed", "mode", "coverage", "problems", "replay", "human", "human_decisions", "served_by",
                  "limitations", "metrics")


class BundleError(RuntimeError):
    pass


def read_records(run_dir: Path) -> list[dict]:
    # Split on "\n" only: str.splitlines() would also split inside a record on U+2028/U+2029/U+0085,
    # which json.dumps(ensure_ascii=False) leaves unescaped.
    text = (run_dir / "audit.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def collect_cite_ids(obj, out: set[str], key: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            collect_cite_ids(v, out, k)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, str) and any(t in key for t in CITE_KEYS):
                out.add(v)
            else:
                collect_cite_ids(v, out, key)


def chunk_ids(chunks_path: Path) -> set[str]:
    return {json.loads(l)["chunk_id"] for l in chunks_path.read_text(encoding="utf-8").split("\n") if l.strip()}


def source_entries(cite_ids: set[str], register: dict, kb_chunk_ids: set[str]) -> dict:
    sources = load_sources()
    out = {}
    for cid in sorted(cite_ids):
        sid = source_id_of(cid)
        meta = sources.get(sid)
        kind = "analyst_note" if "#note" in cid else "source_text"
        entry = {"source_id": sid, "known": meta is not None and sid in register, "in_kb": cid in kb_chunk_ids,
                 "kind": kind, "publish": register.get(sid, {}).get("publish", "unknown")}
        if meta is not None and sid in register:
            for k in ("title", "issuer", "jurisdiction", "url"):
                if meta.get(k) is not None:
                    entry[k] = str(meta[k])
            if meta.get("verification") is not None:
                entry["register_status"] = str(meta["verification"])
            if meta.get("version_date") is not None:
                entry["version_date"] = str(meta["version_date"])
        out[cid] = entry
    return out


def build_context(start_payload: dict) -> dict:
    inputs = start_payload.get("inputs") or {}
    topo_path, roles_path = ROOT / "config/topology.yaml", ROOT / "config/roles.yaml"
    topo_sha, roles_sha = _prov.file_sha(topo_path), _prov.file_sha(roles_path)
    if inputs.get("topology") != topo_sha:
        raise BundleError("config/topology.yaml differs from the run's RUN_START fingerprint")
    if inputs.get("roles") != roles_sha:
        raise BundleError("config/roles.yaml differs from the run's RUN_START fingerprint")
    sc = apply_variation(load_yaml(ROOT / "scenarios/base.yaml"), start_payload.get("variation"))
    sc["id"] = start_payload.get("scenario", sc["id"])
    sc_sha = _prov.scenario_sha(sc)
    if inputs.get("scenario") != sc_sha:
        raise BundleError("scenario differs from the run's RUN_START fingerprint")
    topo = yaml.safe_load(topo_path.read_text(encoding="utf-8"))
    roles = yaml.safe_load(roles_path.read_text(encoding="utf-8"))
    roles_public = {"version": roles.get("version"), "turn_order": roles.get("turn_order"),
                    "roles": {rid: {"title": r.get("title"), "sees": r.get("sees", []), "tools": r.get("tools", [])}
                              for rid, r in roles["roles"].items()}}
    events = [{"id": e["id"], "at_min": e["at_min"], "title": e["title"], "effect": e.get("effect") or {},
               "deliver": [{"to": d.get("to"), "at_min": d.get("at_min"), "kind": d.get("kind"),
                            "text": d.get("text")} for d in e.get("deliver", [])]}
              for e in sc["events"]]
    scenario_public = {"id": sc["id"], "version": sc.get("version"), "title": sc.get("title"),
                       "synthetic": sc.get("synthetic"), "events": events}
    return {"topology": {"sha256": topo_sha, "data": json.loads(json.dumps(topo, default=str))},
            "roles": {"sha256": roles_sha, "data": roles_public},
            "scenario": {"sha256": sc_sha, "data": json.loads(json.dumps(scenario_public, default=str))}}


def build_bundle(run_dir: Path, *, expected_head: str, inspect_report: dict, source_commit: str,
                 generator_run_url: str, register: dict, scanner, kb_chunk_ids: set[str],
                 allow_withheld: bool = False) -> dict:
    """Build the bundle dict. Raises BundleError on any integrity problem (fail closed)."""
    records = read_records(run_dir)
    if not records:
        raise BundleError("empty audit log")
    if not inspect_report.get("passed"):
        raise BundleError("inspect_demonstration did not pass: " + "; ".join(inspect_report.get("problems", [])))
    out, prev, withheld, cites = [], GENESIS, 0, set()
    for i, rec in enumerate(records, 1):
        if rec.get("seq") != i:
            raise BundleError(f"record #{i}: sequence number is {rec.get('seq')}")
        if rec.get("prev") != prev:
            raise BundleError(f"record #{i}: broken link to the previous record")
        body = canonical_body(rec)
        h = record_hash(prev, body)
        if h != rec.get("hash") or engine_hash(rec) != h:
            raise BundleError(f"record #{i}: canonical bytes do not reproduce the recorded hash")
        bad = find_forbidden(rec)
        if bad:
            raise BundleError(f"record #{i}: forbidden fields {bad}")
        hits = scanner.scan_text(body, f"record #{i}")
        if hits:
            if not allow_withheld:
                raise BundleError(f"record #{i}: matches third-party text ({hits[0].chunk_id}); "
                                  "offline bundles may not withhold records")
            withheld += 1
            out.append({"seq": i, "kind": rec["kind"], "actor": rec["actor"], "prev": prev, "hash": h,
                        "body": None, "withheld": True})
        else:
            collect_cite_ids(rec.get("payload"), cites)
            out.append({"seq": i, "kind": rec["kind"], "actor": rec["actor"], "prev": prev, "hash": h,
                        "body": body, "withheld": False})
        prev = h
    if prev != expected_head:
        raise BundleError("chain head does not match the externally captured head")
    start = records[0]
    if start["kind"] != "RUN_START":
        raise BundleError("first record is not RUN_START")
    sp = start["payload"]
    mode = inspect_report.get("mode")
    if mode == "offline-NOT-AI":
        if sp.get("is_ai") is not False or sp.get("model") != "TEST-DOUBLE-NOT-AI":
            raise BundleError("offline bundle whose RUN_START is not the TEST-DOUBLE-NOT-AI client")
        label = "Scripted replay — not AI (TEST-DOUBLE-NOT-AI)"
    elif mode == "live":
        if sp.get("is_ai") is not True:
            raise BundleError("live bundle whose RUN_START is not an AI client")
        label = "Recorded live run"
    else:
        raise BundleError(f"unknown run mode {mode!r}")
    if mode == "offline-NOT-AI" and withheld:
        raise BundleError("offline bundles must have zero withheld records")
    sources = source_entries({c for c in cites if CITE_ID.match(c)}, register, kb_chunk_ids)
    bundle = {
        "schema": SCHEMA_ID,
        "provenance": {
            "mode": mode, "label": label, "run_id": start["run_id"], "scenario": sp.get("scenario"),
            "scenario_version": sp.get("scenario_version"), "variation": sp.get("variation"),
            "model": sp.get("model"), "is_ai": sp.get("is_ai"), "human": sp.get("human"),
            "rules_version": sp.get("rules_version"), "roles_version": sp.get("roles_version"),
            "topology_version": sp.get("topology_version"), "prompt_version": sp.get("prompt_version"),
            "inputs": sp.get("inputs") or {}, "source_commit": source_commit,
            "generator_run_url": generator_run_url, "audit_head": prev, "record_count": len(out),
            "withheld_count": withheld,
            "inspect": {k: inspect_report.get(k) for k in INSPECT_FIELDS},
        },
        "context": build_context(sp),
        "audit": out,
        "sources": sources,
    }
    return bundle


def bundle_id_for(data: bytes) -> str:
    return sha256_hex(data)[:16]
