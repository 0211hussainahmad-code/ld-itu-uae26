"""Licence register, scanners, anchors, request gate and scope guard (M1-T6, M1-T7, M1-T10, M1-T12)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from web.tests.conftest import ROOT, git
from web.publication.claims_lint import lint_text
from web.publication.licences import LicenceError, load_register
from web.publication.scan_secrets import scan_text as secret_scan

REG = ROOT / "web/publication/licences.yaml"


def write_reg(tmp_path, mutate):
    data = yaml.safe_load(REG.read_text())
    mutate(data)
    p = tmp_path / "licences.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_register_covers_every_source_and_defaults_to_metadata_only(register):
    srcs = {s["id"] for s in yaml.safe_load((ROOT / "kb/sources.yaml").read_text())["sources"]}
    assert set(register) == srcs
    assert all(e["publish"] == "metadata_only" for e in register.values())
    assert all(register[s]["publish"] == "metadata_only" for s in register if s.startswith("itu-"))


def test_missing_source_blocks(tmp_path):
    p = write_reg(tmp_path, lambda d: d["sources"].pop("uae-pdpl-2021"))
    with pytest.raises(LicenceError, match="without a licence decision"):
        load_register(p)


def test_excerpt_needs_named_approval_and_metadata_only_cannot_list_excerpts(tmp_path):
    def bad_meta(d):
        d["sources"]["eu-ai-act-art15"]["approved_excerpts"] = [{"id": "x", "approved_by": "a",
                                                                 "approved_on": "2026-11-01", "reason": "r"}]
    with pytest.raises(LicenceError, match="metadata_only"):
        load_register(write_reg(tmp_path, bad_meta))

    def no_approver(d):
        d["sources"]["eu-ai-act-art15"].update(publish="approved_excerpts",
                                               approved_excerpts=[{"id": "x", "approved_on": "2026-11-01",
                                                                   "reason": "short"}])
    with pytest.raises(LicenceError, match="each excerpt"):
        load_register(write_reg(tmp_path, no_approver))


def test_default_must_be_deny(tmp_path):
    with pytest.raises(LicenceError, match="default-deny"):
        load_register(write_reg(tmp_path, lambda d: d.update(default="approved_excerpts")))


def test_licence_scanner_catches_third_party_text_and_ignores_own_notes(scanner, third_party_sentence):
    sentence, chunk_id = third_party_sentence
    hits = scanner.scan_text("prefix words " + sentence + " suffix", "t")
    assert [h.chunk_id for h in hits] == [chunk_id]
    notes = yaml.safe_load((ROOT / "kb/notes.yaml").read_text())["notes"]
    own = next(str(v) for v in notes.values() if len(str(v).split()) > 30)
    assert scanner.scan_text(own, "note") == []
    assert scanner.scan_text("short unrelated synthetic exercise text", "t") == []


def test_secret_scanner_catches_planted_key_without_echoing_it():
    fake = "sk-" + "Z" * 32
    hits = secret_scan(f'{{"x": "{fake}"}}', "f")
    assert hits and all(fake not in h for h in hits)
    assert secret_scan("no secrets here", "f") == []


def test_claims_lint_flags_never_say_wording():
    assert lint_text("A tamper-evident record.", "f") == []
    for bad in ("an immutable log", "live AI agents decide", "the decision was lawful", "grounded answers"):
        assert lint_text(bad, "f"), bad


# ---- anchors -------------------------------------------------------------------------------

def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "README").write_text("x")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def test_anchor_from_the_adding_commit(tmp_path):
    from web.bundler.anchor import AnchorError, anchor_line, find_anchor
    repo = _repo(tmp_path)
    (repo / "b").mkdir()
    (repo / "b/abcdef0123456789.json").write_text("{}")
    git(repo, "add", ".")
    line = anchor_line("abcdef0123456789", "a" * 64, "c" * 40, "https://github.com/o/r/actions/runs/1")
    git(repo, "commit", "-q", "-m", "bundle\n\n" + line)
    a = find_anchor("b/abcdef0123456789.json", "abcdef0123456789", repo)
    assert a.head == "a" * 64 and a.source_commit == "c" * 40
    # A later commit cannot re-anchor: only the adding commit counts.
    (repo / "b/abcdef0123456789.json").write_text('{"x":1}')
    git(repo, "commit", "-qam", "edit\n\n" + anchor_line("abcdef0123456789", "b" * 64, "c" * 40, "u://x"))
    assert find_anchor("b/abcdef0123456789.json", "abcdef0123456789", repo).head == "a" * 64
    (repo / "b/1111111111111111.json").write_text("{}")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "no anchor line")
    with pytest.raises(AnchorError, match="exactly one is required"):
        find_anchor("b/1111111111111111.json", "1111111111111111", repo)


# ---- request gate (§18.3) -------------------------------------------------------------------

def test_request_gate_rules():
    from web.tools.request_gate import BUNDLE, DEPLOY, AUDIT, GateError, decide
    assert decide(None) == {"bundle_requested": False, "audit_requested": False, "deploy_requested": False}
    assert decide([BUNDLE])["bundle_requested"] is True
    assert decide([AUDIT, "web/x.py"])["audit_requested"] is True
    with pytest.raises(GateError):
        decide([DEPLOY])                                  # M1: no deploy at all
    import web.tools.request_gate as g
    old, g.DEPLOY_ENABLED = g.DEPLOY_ENABLED, True
    try:
        with pytest.raises(GateError, match="same push"):
            decide([BUNDLE, DEPLOY])
    finally:
        g.DEPLOY_ENABLED = old


def test_request_gate_on_a_fixture_repo(tmp_path):
    repo = _repo(tmp_path)
    before = git(repo, "rev-parse", "HEAD").strip()
    (repo / "web/requests").mkdir(parents=True)
    (repo / "web/requests/bundle.json").write_text("{}")
    (repo / "web/requests/deploy.json").write_text("{}")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "both requests")
    after = git(repo, "rev-parse", "HEAD").strip()
    from web.tools.request_gate import GateError, changed_paths, decide
    changed = changed_paths(before, after, repo)
    assert set(changed) == {"web/requests/bundle.json", "web/requests/deploy.json"}
    with pytest.raises(GateError):
        decide(changed)
    assert changed_paths("0" * 40, after, repo) is None
    assert changed_paths("deadbeef" * 5, after, repo) is None


def test_workflow_references_no_secrets_and_has_no_deploy_job():
    wf = (ROOT / ".github/workflows/web.yml").read_text()
    assert "secrets." not in wf
    jobs = yaml.safe_load(wf)["jobs"]
    assert "deploy" not in jobs
    on = yaml.safe_load(wf)[True]                         # YAML parses the 'on' key as boolean True
    assert set(on) == {"push"} and on["push"]["branches"] == ["feature/web-vertical-slice"]


# ---- scope guard ----------------------------------------------------------------------------

def test_scope_guard_patterns():
    from web.tools.check_scope import outside_scope
    assert outside_scope(["web/app/src/x.ts", ".github/workflows/web.yml", ".gitignore"]) == []
    assert outside_scope(["linkdown/gate.py", ".github/workflows/ci.yml", "scripts/replay.py",
                          "docs/reports/2026-10-31_offline_exercise.json"]) == [
        "linkdown/gate.py", ".github/workflows/ci.yml", "scripts/replay.py",
        "docs/reports/2026-10-31_offline_exercise.json"]


def test_request_files_are_validated_strictly():
    from web.tools.check_request import check
    ok = {"kind": "offline-NOT-AI", "reason": "r", "requested_by": "someone"}
    assert check("bundle", ok) == []
    assert check("bundle", {**ok, "kind": "live"})                          # live bundles never via CI
    assert check("bundle", {**ok, "approved_by": "x"})                      # no authorization fields
    assert check("audit", {"scope": "read-only", "reason": "r", "requested_by": "x"}) == []
    assert check("deploy", ok)                                              # unknown request kind
    committed = json.loads((ROOT / "web/requests/bundle.json").read_text())
    assert check("bundle", committed) == []


# ---- publication audit (read-only) ---------------------------------------------------------

def test_audit_severity_follows_source_licences():
    from web.publication.audit_repo import licence_severity
    assert licence_severity("itu-t-y3172-2019") == "High"
    assert licence_severity("itu-ai-ready-2-2026") == "High"
    assert licence_severity("uae-pdpl-2021") == "Medium"            # link_and_excerpt: team decision
    assert licence_severity("eu-ai-act-art15") == "Low"
    assert licence_severity("canada-dadm-2025") == "Medium"         # licence still TODO


def test_audit_zip_scan_reports_locations_not_text(tmp_path, scanner, third_party_sentence):
    import zipfile
    from web.publication.audit_repo import Findings, render, scan_zip
    sentence, _ = third_party_sentence
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("run/turns/001_service.json", json.dumps({"user": "context: " + sentence}))
        f.writestr("run/log.txt", "token sk-" + "Q" * 30 + " mail person@private-example.org")
    F = Findings()
    stats = scan_zip(z, scanner, F, "artifacts", "artifact demo")
    assert stats["turn_files"] == 1 and stats["text_scanned"] == 2
    sev = {r[0] for r in F.rows}
    assert "High" in sev and "Medium" in sev and "Low" in sev
    g = {"refs": 1, "branches": [], "tags": [], "commits": 1, "blobs": 1, "blobs_scanned": 1, "binaries": 0,
         "big_skipped": 0, "turn_files": 0, "commit_messages_scanned": 1}
    a = {"artifacts_total": 1, "artifacts_unexpired": 1, "artifacts_scanned": 1, "artifact_families": {"x": 1},
         "runs_total": 0, "logs_scanned": 0, "logs_unavailable": 0, "releases": 0, "pages": "not enabled"}
    report = render("o/r", g, a, F, scanner)
    assert sentence[:60] not in report and "Q" * 30 not in report and "person@" not in report
    assert "private-example.org×1" in report and "nothing was deleted" in report


# ---- role visibility mirrors linkdown/agents.py build_view() -------------------------------

def test_role_visibility_map_matches_build_view_exactly():
    """Fails if build_view() gains or loses a view key, or a role's `sees` names a key the site does not model."""
    import ast
    import re
    src = (ROOT / "linkdown/agents.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "build_view")
    body = ast.get_source_segment(src, fn)
    engine_keys = set(re.findall(r'if "([a-z_]+)" in sees:', body))
    site = json.loads((ROOT / "web/app/src/lib/role-visibility.json").read_text())
    site_keys = {k for k in site if not k.startswith("_")}
    assert engine_keys == site_keys, (engine_keys, site_keys)
    roles = yaml.safe_load((ROOT / "config/roles.yaml").read_text())["roles"]
    for rid, r in roles.items():
        assert set(r.get("sees", [])) <= site_keys, rid
    # build_view never includes per-link capacity or latency, nor node relationships.
    assert '"cap"' not in body and '"ms"' not in body and '"a"' not in body and '"b"' not in body
    assert roles["adviser"].get("sees", []) == []
    # The links key gives id, label and up status only, and only for non-domestic links.
    assert re.search(r'\{"id": l\["id"\], "label": l\["label"\], "up": [^}]*\}\s*for l in state\.topo\.links if l\["group"\] != "domestic"', body)
    # The service key's fields: RoleView shows the three the record contains and names the other four.
    m = re.search(r'for k in \(([^)]*)\)', body)
    assert m and set(re.findall(r'"([a-z_]+)"', m.group(1))) == {
        "name", "owner", "entity_type", "mode", "endpoint_region", "records_region", "hold_your_own_key_in_uae"}
    # Which keys the published record lets the site reconstruct (the rest are named, never invented).
    assert {k: v["shown"] for k, v in site.items() if not k.startswith("_")} == {
        "links": True, "capacity": False, "traffic": True, "service": True, "service_traffic": True,
        "endpoints": False, "demand_classes": True, "record_sets": False}
