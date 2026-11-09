"""Release manifest without self-referential hashing (plan rev 2.1 §18.1; M1-T11).

Runs on a synthetic dist and, when WEB_DIST points at a real build, on that build too.
Test 6 (reproducibility) runs here on synthetic builds and in CI on two real Vite builds
(web/tools/compare_builds.py).
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import shutil
import threading
from pathlib import Path

import pytest

from web.tests.conftest import ROOT
from web.tools.compare_builds import compare
from web.tools.make_release import build_release, file_map
from web.tools.verify_release import verify

INDEX = '<!doctype html><html><head><script type="module" src="/assets/app-1.js"></script>' \
        '<link rel="stylesheet" href="/assets/app-1.css"></head><body></body></html>'


def synthetic_dist(root: Path) -> Path:
    d = root / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "bundles").mkdir()
    (d / "index.html").write_text(INDEX)
    (d / "assets/app-1.js").write_text("console.log('app')")
    (d / "assets/app-1.css").write_text("body{}")
    (d / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n")
    (d / "bundles/manifest.json").write_text(json.dumps({"schema": "linkdown-bundle-manifest/1", "bundles": [
        {"bundle_id": "a" * 16, "sha256": "a" * 64, "audit_head": "b" * 64}]}))
    return d


def release(d: Path) -> str:
    data, digest = build_release(d, "c" * 40, "local:test", "web-test-ccccccc")
    (d / "release.json").write_bytes(data)
    return digest


def dists(tmp_path):
    out = [synthetic_dist(tmp_path)]
    real = os.environ.get("WEB_DIST")
    if real:
        copy = tmp_path / "real-dist"
        shutil.copytree(real, copy)
        (copy / "release.json").unlink(missing_ok=True)
        out.append(copy)
    return out


def test_1_release_json_is_not_in_its_own_file_list(tmp_path):
    for d in dists(tmp_path):
        release(d)
        rel = json.loads((d / "release.json").read_text())
        assert "release.json" not in rel["files"]


def test_2_every_other_file_listed_exactly_once_with_correct_hash(tmp_path):
    for d in dists(tmp_path):
        release(d)
        rel = json.loads((d / "release.json").read_text())
        on_disk = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()} - {"release.json"}
        assert set(rel["files"]) == on_disk and len(rel["files"]) == len(on_disk)
        for path, meta in rel["files"].items():
            assert meta["sha256"] == hashlib.sha256((d / path).read_bytes()).hexdigest()


def test_3_no_file_contains_the_release_json_digest(tmp_path):
    for d in dists(tmp_path):
        digest = release(d)
        for p in d.rglob("*"):
            if p.is_file() and p.name != "release.json":
                assert digest.encode() not in p.read_bytes()
    d = synthetic_dist(tmp_path / "self-ref")
    data, digest = build_release(d, "c" * 40, "local:test", "web-test-ccccccc")
    # A file that embedded release.json's digest would be a self-reference and must be refused.
    (d / "assets/app-1.js").write_text(f"const RELEASE='{digest}'")
    data2, digest2 = build_release(d, "c" * 40, "local:test", "web-test-ccccccc")
    assert digest2 != digest                       # changing a listed file changes release.json


def test_4_one_changed_byte_is_detected_and_named(tmp_path):
    d = synthetic_dist(tmp_path)
    digest = release(d)
    assert verify(str(d), digest) == []
    (d / "assets/app-1.js").write_text("console.log('apq')")
    problems = verify(str(d), digest)
    assert problems == ["assets/app-1.js: content differs from release.json"]


def test_5_changed_release_json_fails_against_the_external_anchor(tmp_path):
    d = synthetic_dist(tmp_path)
    digest = release(d)
    rel = json.loads((d / "release.json").read_text())
    rel["git_commit"] = "d" * 40
    (d / "release.json").write_text(json.dumps(rel, indent=2, sort_keys=True) + "\n")
    problems = verify(str(d), digest)
    assert len(problems) == 1 and "external anchor" in problems[0]


def test_6_rebuild_of_same_inputs_is_reproducible_and_built_at_only_in_release_json(tmp_path):
    a, b = synthetic_dist(tmp_path / "a"), synthetic_dist(tmp_path / "b")
    release(a)
    release(b)
    assert compare(a, b) == []
    assert file_map(a) == file_map(b)
    for d in (a, b):
        hits = [p for p in d.rglob("*") if p.is_file() and b"built_at" in p.read_bytes()]
        assert [p.name for p in hits] == ["release.json"]
    (b / "assets/app-1.css").write_text("body{color:red}")
    assert compare(a, b) == ["differs between builds: assets/app-1.css"]


def test_unlisted_asset_referenced_by_index_is_reported(tmp_path):
    d = synthetic_dist(tmp_path)
    (d / "index.html").write_text(INDEX.replace("</head>", '<script src="/assets/extra.js"></script></head>'))
    digest = release(d)                            # extra.js is referenced but was never built
    data = json.loads((d / "release.json").read_text())
    assert "assets/extra.js" not in data["files"]
    problems = verify(str(d), digest)
    assert any("does not list" in p for p in problems)
    assert any(p.startswith("x.js") for p in verify(str(d), digest, ["x.js"]))


def test_verify_release_over_http(tmp_path):
    d = synthetic_dist(tmp_path)
    digest = release(d)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        assert verify(url, digest) == []
        assert verify(url, "0" * 64) and "external anchor" in verify(url, "0" * 64)[0]
    finally:
        srv.shutdown()


def test_app_fetches_release_json_at_runtime_and_never_imports_it():
    import re
    src = ROOT / "web/app/src"
    for p in src.rglob("*.ts*"):
        assert not re.search(r"""import[^;]*release\.json""", p.read_text(encoding="utf-8")), p
    assert 'fetcher("/release.json")' in (src / "lib/release.ts").read_text(encoding="utf-8")


def test_navigation_links_are_not_assets_but_every_page_is_checked(tmp_path):
    d = synthetic_dist(tmp_path)
    # A prerendered page links to other routes: those are pages, not assets, and pass.
    (d / "index.html").write_text(INDEX.replace("<body></body>", '<body><a href="/walkthrough">Walkthrough</a><a class="x" href="/audit">Audit</a></body>'))
    (d / "audit.html").write_text(INDEX)
    digest = release(d)
    assert verify(str(d), digest) == []
    # A route page that loads an unlisted script is reported, just like index.html.
    (d / "audit.html").write_text(INDEX.replace("</head>", '<link rel="modulepreload" href="/assets/ghost.js"></head>'))
    digest = release(d)
    assert verify(str(d), digest) == ["audit.html references /assets/ghost.js, which release.json does not list"]
