"""Fail-closed check that preview addresses are NOT publicly readable. Standard library only.

    python web/tools/check_access.py https://linkdown-preview.pages.dev https://preview.linkdown-preview.pages.dev ...

Each address is fetched WITHOUT credentials and WITHOUT following redirects (paths "/" and
"/release.json"). An address passes only if every response is one of:
  - a redirect (301/302/303/307/308) whose Location is on a *.cloudflareaccess.com host
    (the Cloudflare Access login), or
  - 401 or 403.
Anything else fails, including 200, 404, any other redirect and a network error: an address that
cannot be shown to be protected is treated as exposed. Exit 0 and "ACCESS: PROTECTED" only if all pass.
Before any deployment exists, a preview hostname may answer 404: that is NEVER proof of protection,
and this check reports it as a failure. So the pre-upload gate is the project hostname only, and the
decisive check comes after the upload, on all three addresses: the project hostname, the branch alias
and the exact deployment URL. A failure there means: delete that deployment now (CLOUDFLARE_PREVIEW.md).
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request

PATHS = ("/", "/release.json")
ACCESS_SUFFIX = ".cloudflareaccess.com"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):            # noqa: D102
        return None


def classify(status: int, location: str | None) -> str | None:
    """None if this response proves the address is protected, else the reason it does not."""
    if status in (401, 403):
        return None
    if status in (301, 302, 303, 307, 308):
        host = urllib.parse.urlsplit(location or "").hostname or ""
        if host.endswith(ACCESS_SUFFIX):
            return None
        return f"redirects to {location!r}, not to Cloudflare Access"
    return f"answered {status} without credentials"


def probe(url: str, timeout: float = 20) -> list[str]:
    problems: list[str] = []
    opener = urllib.request.build_opener(_NoRedirect)
    for path in PATHS:
        target = url.rstrip("/") + path
        if not target.startswith("https://") and not target.startswith("http://127.0.0.1"):
            problems.append(f"{target}: not https")
            continue
        req = urllib.request.Request(target, headers={"User-Agent": "linkdown-access-check/1"})
        try:
            with opener.open(req, timeout=timeout) as r:                       # noqa: S310
                why = classify(r.status, r.headers.get("Location"))
        except urllib.error.HTTPError as e:
            why = classify(e.code, e.headers.get("Location"))
        except Exception as e:                                                  # noqa: BLE001
            why = f"could not be checked ({e.__class__.__name__}: {e})"
        if why:
            problems.append(f"{target}: {why}")
    return problems


def main(argv=None) -> int:
    urls = list(sys.argv[1:] if argv is None else argv)
    if not urls:
        sys.exit(__doc__)
    problems = [p for u in urls for p in probe(u)]
    for p in problems:
        print("ACCESS FAIL " + p)
    if problems:
        print("ACCESS: NOT PROVEN PROTECTED (treat as exposed)")
        return 1
    print(f"ACCESS: PROTECTED ({len(urls)} address(es), paths {', '.join(PATHS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
