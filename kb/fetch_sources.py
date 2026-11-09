"""Download the knowledge-base sources listed in kb/sources.yaml.

Run this on a team laptop (the build workspace cannot reach UAE government
sites). It only downloads files: it never executes them.

    python kb/fetch_sources.py            # fetch every auto_fetch source not yet on disk
    python kb/fetch_sources.py --force    # fetch again and overwrite
    python kb/fetch_sources.py --only uae-pdpl-2021

Files go to kb/docs/ (gitignored: no redistribution licence is assumed).
kb/build/fetch_manifest.json records URL, HTTP status, bytes, sha256 and time
for every attempt, so the knowledge base can be rebuilt and checked later.

Sources with auto_fetch: false (for example the CSC policy PDF, whose site
disallows automated fetching) must be downloaded by hand in a browser and saved
under kb/docs/<local_file>. The script then records their hash as well.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

KB = Path(__file__).resolve().parent
DOCS, BUILD = KB / "docs", KB / "build"
UA = "LinkDown-KB-fetch/0.1 (ITU AI for Good hackathon research; one request per document)"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*", default=None, help="source ids to fetch")
    ap.add_argument("--register", nargs="*", default=None, metavar="ID=PATH",
                    help="record the hash of a file the team downloaded by hand (not copied, not fetched)")
    ap.add_argument("--by", default="team", help="who downloaded the registered file")
    ap.add_argument("--on", default=None, help="download date of the registered file (YYYY-MM-DD)")
    args = ap.parse_args()

    reg = yaml.safe_load((KB / "sources.yaml").read_text(encoding="utf-8"))
    DOCS.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    man_path = BUILD / "fetch_manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}

    if args.register:
        known = {s["id"]: s for s in reg["sources"]}
        for item in args.register:
            sid, _, path = item.partition("=")
            if sid not in known or not path:
                print(f"REFUSED {item}: use ID=PATH with an id from kb/sources.yaml")
                return 1
            f = Path(path)
            manifest[sid] = {"id": sid, "url": known[sid]["url"], "file": known[sid].get("local_file") or f.name,
                             "status": "manual_download", "downloaded_by": args.by, "downloaded_on": args.on,
                             "bytes": f.stat().st_size, "sha256": sha256(f),
                             "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            print(f"{'manual_download':<26} {sid}  sha256 {manifest[sid]['sha256']}")
        man_path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        print(f"manifest: {man_path.relative_to(KB.parent)}")
        return 0

    todo = [s for s in reg["sources"] if s.get("local_file") and (not args.only or s["id"] in args.only)]
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60) as client:
        for s in todo:
            dest = DOCS / s["local_file"]
            entry = {"id": s["id"], "url": s["url"], "file": s["local_file"],
                     "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            if dest.exists() and not args.force:
                entry.update(status="present", bytes=dest.stat().st_size, sha256=sha256(dest))
            elif not s.get("auto_fetch", False):
                entry.update(status="manual_download_required")
                print(f"MANUAL  {s['id']}: open {s['url']} in a browser and save as kb/docs/{s['local_file']}")
            else:
                try:
                    r = client.get(s["url"])
                    entry["http_status"] = r.status_code
                    entry["content_type"] = r.headers.get("content-type", "")
                    if r.status_code == 200 and r.content:
                        dest.write_bytes(r.content)
                        entry.update(status="fetched", bytes=len(r.content), sha256=sha256(dest))
                    else:
                        entry["status"] = "http_error"
                except httpx.HTTPError as e:
                    entry.update(status="network_error", error=str(e)[:300])
                time.sleep(1.0)    # be polite to government sites
            manifest[s["id"]] = entry
            print(f"{entry['status']:<26} {s['id']}")

    man_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"\nmanifest: {man_path.relative_to(KB.parent)}")
    print("Next: open each new file, check the clause you rely on, update 'verification' in kb/sources.yaml, "
          "then run: python kb/build_kb.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
