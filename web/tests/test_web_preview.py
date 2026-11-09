"""Preview readiness tooling: the artifact gate (prepare_preview.py) and the Access probe (check_access.py).

Both deploy nothing and need no credential. They fail closed: a wrong digest, a tampered file, a
different commit, an unsafe archive, server code, or a preview that answers without credentials
must each be refused.
"""
from __future__ import annotations

import hashlib
import http.server
import threading
import zipfile
from pathlib import Path

import pytest

from web.tools.check_access import classify, probe
from web.tools.make_release import build_release
from web.tools.prepare_preview import check

COMMIT = "345d309d1c42336454804871a25ae7f53559ada8"
HEADERS = ("/*\n  Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'\n"
           "  X-Content-Type-Options: nosniff\n")


def site(root: Path, commit: str = COMMIT) -> tuple[Path, str]:
    d = root / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text('<!doctype html><script type="module" src="/assets/app.js"></script>')
    (d / "audit.html").write_text('<!doctype html><script type="module" src="/assets/app.js"></script>')
    (d / "assets/app.js").write_text("console.log('linkdown')")
    (d / "_headers").write_text(HEADERS)
    data, digest = build_release(d, commit, "https://example.invalid/run/1", release_id="web-test-345d309")
    (d / "release.json").write_bytes(data)
    return d, digest


def zip_dir(d: Path, z: Path, extra: dict[str, bytes] | None = None) -> str:
    with zipfile.ZipFile(z, "w") as f:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                f.write(p, p.relative_to(d).as_posix())
        for name, data in (extra or {}).items():
            f.writestr(name, data)
    return hashlib.sha256(z.read_bytes()).hexdigest()


def test_the_exact_verified_artifact_passes(tmp_path):
    d, rsha = site(tmp_path)
    zsha = zip_dir(d, tmp_path / "a.zip")
    assert check(tmp_path / "a.zip", tmp_path / "out", f"sha256:{zsha}", rsha, COMMIT, "web-test-345d309") == []


def test_a_different_artifact_digest_is_refused(tmp_path):
    d, rsha = site(tmp_path)
    zip_dir(d, tmp_path / "a.zip")
    p = check(tmp_path / "a.zip", tmp_path / "out", "0" * 64, rsha, COMMIT)
    assert p and "differs from the recorded digest" in p[0]
    assert not (tmp_path / "out").exists()                      # nothing extracted


def test_a_tampered_file_is_refused_even_with_a_matching_zip_digest(tmp_path):
    d, rsha = site(tmp_path)
    (d / "assets/app.js").write_text("console.log('changed')")   # after release.json was written
    zsha = zip_dir(d, tmp_path / "a.zip")
    p = check(tmp_path / "a.zip", tmp_path / "out", zsha, rsha, COMMIT)
    assert any("assets/app.js: content differs" in x for x in p)


def test_a_release_json_other_than_the_anchored_one_is_refused(tmp_path):
    d, _ = site(tmp_path)
    zsha = zip_dir(d, tmp_path / "a.zip")
    p = check(tmp_path / "a.zip", tmp_path / "out", zsha, "f" * 64, COMMIT)
    assert any("differs from the external anchor" in x for x in p)


def test_a_build_of_another_commit_is_refused(tmp_path):
    d, rsha = site(tmp_path, commit="1" * 40)
    zsha = zip_dir(d, tmp_path / "a.zip")
    p = check(tmp_path / "a.zip", tmp_path / "out", zsha, rsha, COMMIT)
    assert any("not 345d309" in x for x in p)


@pytest.mark.parametrize("name", ["../evil.js", "/abs.js"])
def test_unsafe_archive_paths_are_refused_before_extraction(tmp_path, name):
    d, rsha = site(tmp_path)
    zsha = zip_dir(d, tmp_path / "a.zip", {name: b"x"})
    p = check(tmp_path / "a.zip", tmp_path / "out", zsha, rsha, COMMIT)
    assert p and "unsafe path" in p[0]
    assert not any((tmp_path / "out").rglob("*"))


def test_server_code_is_refused(tmp_path):
    d, rsha = site(tmp_path)
    zsha = zip_dir(d, tmp_path / "a.zip", {"_worker.js": b"export default {}"})
    p = check(tmp_path / "a.zip", tmp_path / "out", zsha, rsha, COMMIT)
    assert any("static only" in x for x in p)


def test_a_missing_csp_is_refused(tmp_path):
    d, _ = site(tmp_path)
    (d / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n")
    data, rsha = build_release(d, COMMIT, "https://example.invalid/run/1")
    (d / "release.json").write_bytes(data)
    zsha = zip_dir(d, tmp_path / "a.zip")
    p = check(tmp_path / "a.zip", tmp_path / "out", zsha, rsha, COMMIT)
    assert any("Content-Security-Policy" in x for x in p)


def test_a_non_empty_output_directory_is_refused(tmp_path):
    d, rsha = site(tmp_path)
    zsha = zip_dir(d, tmp_path / "a.zip")
    (tmp_path / "out").mkdir()
    (tmp_path / "out/old.html").write_text("old")
    p = check(tmp_path / "a.zip", tmp_path / "out", zsha, rsha, COMMIT)
    assert p and "not empty" in p[0]


# --- Access probe ---------------------------------------------------------------------------------

@pytest.mark.parametrize("status,location,ok", [
    (302, "https://team.cloudflareaccess.com/cdn-cgi/access/login/x", True),
    (403, None, True),
    (401, None, True),
    (200, None, False),                                         # publicly readable
    (404, None, False),                                         # cannot be shown protected
    (302, "https://evil.example/cloudflareaccess.com", False),
    (302, "https://cloudflareaccess.com.evil.example/", False),
])
def test_only_access_redirects_and_refusals_count_as_protected(status, location, ok):
    assert (classify(status, location) is None) is ok


def serve(status: int, location: str | None = None):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                       # noqa: N802
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(b"<!doctype html>LinkDown")

        def log_message(self, *a):                              # quiet
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_probe_refuses_a_preview_that_answers_without_credentials():
    srv, url = serve(200)
    try:
        assert probe(url) and all("answered 200" in p for p in probe(url))
    finally:
        srv.shutdown()


def test_probe_accepts_the_access_login_redirect_and_does_not_follow_it():
    srv, url = serve(302, "https://team.cloudflareaccess.com/cdn-cgi/access/login/linkdown")
    try:
        assert probe(url) == []
    finally:
        srv.shutdown()


def test_probe_treats_an_unreachable_address_as_exposed():
    srv, url = serve(200)
    srv.shutdown()
    srv.server_close()
    assert any("could not be checked" in p for p in probe(url, timeout=2))


def test_probe_refuses_plain_http():
    assert any("not https" in p for p in probe("http://linkdown-preview.pages.dev"))


def test_the_plan_pins_the_values_of_the_frozen_build():
    """The plan carries the exact artifact and release digests the upload must match."""
    plan = (Path(__file__).resolve().parents[1] / "deploy/CLOUDFLARE_PREVIEW.md").read_text()
    for v in (COMMIT, "13275226453", "f6e2fd7ac5e6188b591215cf0517c4cc6eb1da6598ae5a360c18f6a5981edb49",
              "8e5f00134bc0f0ab663c18a8312ed0e9025e1a48e21653224d36de264a07d226", "web-20261103-345d309",
              "wrangler@4.151.3"):
        assert v in plan, v
    assert "name: site-dist" not in plan                        # the old, wrong artifact name is never downloaded


def test_verify_release_sends_access_headers_only_when_both_values_are_set(monkeypatch):
    from web.tools.verify_release import access_headers
    monkeypatch.delenv("CF_ACCESS_CLIENT_ID", raising=False)
    monkeypatch.delenv("CF_ACCESS_CLIENT_SECRET", raising=False)
    assert access_headers() == {}
    monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "id.access")
    assert access_headers() == {}                               # one value alone sends nothing
    monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "s3cret")
    assert access_headers() == {"CF-Access-Client-Id": "id.access", "CF-Access-Client-Secret": "s3cret"}


def test_verify_release_never_sends_the_access_token_to_another_origin_even_through_redirects():
    from web.tools.verify_release import fetcher
    seen: dict[str, list] = {"A": [], "B": []}

    def handler(name, routes):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                                   # noqa: N802
                seen[name].append((self.path, self.headers.get("CF-Access-Client-Id"), self.headers.get("CF-Access-Client-Secret")))
                status, loc = routes.get(self.path, (200, None))
                self.send_response(status)
                if loc:
                    self.send_header("Location", loc)
                self.end_headers()
                self.wfile.write(b"body")

            def log_message(self, *a):
                pass
        return H
    b = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler("B", {}))
    B = f"http://127.0.0.1:{b.server_address[1]}"
    a = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler("A", {
        "/release.json": (302, f"{B}/stolen"), "/audit.html": (308, "/audit")}))
    A = f"http://127.0.0.1:{a.server_address[1]}"
    for srv in (a, b):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        get = fetcher(A, headers={"CF-Access-Client-Id": "id.access", "CF-Access-Client-Secret": "s3cret"})
        get("release.json")                                     # A -> 302 -> B (another origin)
        get("audit.html")                                       # A -> 308 -> A/audit (same origin)
    finally:
        a.shutdown(); b.shutdown()
    assert [p for p, _, _ in seen["B"]] == ["/stolen"]
    assert all(i is None and sec is None for _, i, sec in seen["B"]), seen["B"]
    assert ("/release.json", "id.access", "s3cret") in seen["A"]
    assert ("/audit", "id.access", "s3cret") in seen["A"]       # a same-origin redirect keeps the token
