"""Check that a deployed (or local) LinkDown site is exactly a given release. Standard library only.

    python web/tools/verify_release.py https://<site> --expected-release-sha HEX
    python web/tools/verify_release.py web/app/dist   --expected-release-sha HEX

1. sha256(release.json) must equal the externally anchored value you supply (deploy record in
   git, GitHub Release SHA256SUMS or the report). The site's own copy is never the anchor.
2. Every file listed in release.json must be served with exactly the listed sha256.
3. Every asset that a published HTML page (index.html and each prerendered route page) loads must
   be listed (nothing unlisted is executed). Navigation links (<a href>) are pages, not assets.
4. Optionally (--asset-list FILE, one path per line, e.g. from the build artifact) every path in
   that list must be listed in release.json.
Exit 0 only if all checks pass.

Behind Cloudflare Access (the protected preview), set CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET
to a service token's values; they are then sent as CF-Access-Client-Id / CF-Access-Client-Secret on
https requests. Without them nothing extra is sent. If Access answers instead of the site, release.json
is the login page and check 1 fails: a protected site is never mistaken for a verified one. The token goes
to the site's exact origin only; it is removed from any redirect that leaves that origin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# src/href on any tag except <a>: scripts, styles, preloads, icons and images are loaded; links are followed.
ASSET_REF = re.compile(r'<(?!a[\s>])[a-z][a-z0-9-]*\b[^>]*?\b(?:src|href)="(/[^"#?]+)"', re.IGNORECASE)


def access_headers() -> dict[str, str]:
    """Cloudflare Access service-token headers, only when both values are set in the environment."""
    cid, secret = os.environ.get("CF_ACCESS_CLIENT_ID"), os.environ.get("CF_ACCESS_CLIENT_SECRET")
    return {"CF-Access-Client-Id": cid, "CF-Access-Client-Secret": secret} if cid and secret else {}


def _origin(url: str) -> tuple[str, str, int | None]:
    u = urllib.parse.urlsplit(url)
    return (u.scheme, (u.hostname or "").lower(), u.port or {"https": 443, "http": 80}.get(u.scheme))


class _StripOnCrossOriginRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies request headers onto every redirect it follows; drop the Access token if one leaves the origin."""

    def __init__(self, origin):
        super().__init__()
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin(new.full_url) != self.origin:
            for name in [h for h in new.headers if h.lower().startswith("cf-access-client")]:
                new.remove_header(name)
        return new


def fetcher(source: str, headers: dict[str, str] | None = None):
    """`headers` (default: access_headers(), and only for an https source) go to the source's exact origin only."""
    if re.match(r"^https?://", source):
        base = source.rstrip("/") + "/"
        origin = _origin(base)
        hdrs = headers if headers is not None else (access_headers() if base.startswith("https://") else {})
        opener = urllib.request.build_opener(_StripOnCrossOriginRedirect(origin))

        def get(path: str) -> bytes:
            url = urllib.parse.urljoin(base, urllib.parse.quote(path.lstrip("/")))
            req = urllib.request.Request(url, headers=hdrs if _origin(url) == origin else {})
            with opener.open(req, timeout=30) as r:                     # noqa: S310 (https/http only)
                return r.read()
        return get
    root = Path(source)

    def get_local(path: str) -> bytes:
        p = (root / path.lstrip("/")).resolve()
        if root.resolve() not in p.parents and p != root.resolve():
            raise FileNotFoundError(path)
        return p.read_bytes()
    return get_local


def verify(source: str, expected_release_sha: str, asset_list: list[str] | None = None) -> list[str]:
    get = fetcher(source)
    problems: list[str] = []
    try:
        raw = get("release.json")
    except Exception as e:                                              # noqa: BLE001
        return [f"release.json could not be fetched: {e}"]
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_release_sha:
        return [f"release.json sha256 {digest} differs from the external anchor {expected_release_sha}"]
    rel = json.loads(raw)
    files = rel.get("files", {})
    if "release.json" in files:
        problems.append("release.json lists itself (self-reference)")
    for path, meta in sorted(files.items()):
        try:
            data = get(path)
        except Exception as e:                                          # noqa: BLE001
            problems.append(f"{path}: not served ({e})")
            continue
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            problems.append(f"{path}: content differs from release.json")
        if digest.encode() in data:
            problems.append(f"{path}: contains the release.json digest (self-reference)")
    pages = ["index.html"] + sorted(p for p in files if p.endswith(".html") and p != "index.html")
    for page in pages:
        try:
            html = get(page).decode("utf-8", "replace")
            for ref in sorted(set(ASSET_REF.findall(html))):
                if ref.lstrip("/") not in files:
                    problems.append(f"{page} references {ref}, which release.json does not list")
        except Exception as e:                                          # noqa: BLE001
            problems.append(f"{page} could not be checked: {e}")
    for path in asset_list or []:
        if path and path not in files:
            problems.append(f"{path}: deployed but not listed in release.json")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--expected-release-sha", required=True)
    ap.add_argument("--asset-list", type=Path)
    a = ap.parse_args(argv)
    assets = a.asset_list.read_text().split() if a.asset_list else None
    problems = verify(a.source, a.expected_release_sha, assets)
    for p in problems:
        print("RELEASE FAIL " + p)
    if not problems:
        rel = json.loads(fetcher(a.source)("release.json"))
        print(f"RELEASE: PASS {rel['release_id']} commit {rel['git_commit']} ({len(rel['files'])} files)")
        for b in rel.get("bundles", []):
            print(f"  bundle {b['bundle_id']} audit head {b['audit_head']}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
