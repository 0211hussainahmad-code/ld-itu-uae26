"""Load and validate the default-deny licence register (web/publication/licences.yaml).

The register decides what may appear publicly. It is checked against the source
register (kb/sources.yaml, read-only): every source must be listed, so a new source
blocks publication until someone decides its licence.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "web/publication/licences.yaml"
SOURCES = ROOT / "kb/sources.yaml"
PUBLISH_MODES = {"metadata_only", "approved_excerpts"}
EXCERPT_KEYS = {"id", "approved_by", "approved_on", "reason"}


class LicenceError(ValueError):
    pass


def load_sources(path: Path = SOURCES) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["sources"]}


def load_register(path: Path = REGISTER, sources_path: Path = SOURCES) -> dict[str, dict]:
    """Return {source_id: entry}. Raises LicenceError on any gap or malformed entry."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("default") != "metadata_only":
        raise LicenceError("register default must be metadata_only (default-deny)")
    entries = data.get("sources") or {}
    sources = load_sources(sources_path)
    missing = sorted(set(sources) - set(entries))
    if missing:
        raise LicenceError(f"sources without a licence decision: {', '.join(missing)}")
    unknown = sorted(set(entries) - set(sources))
    if unknown:
        raise LicenceError(f"register lists sources not in kb/sources.yaml: {', '.join(unknown)}")
    for sid, e in entries.items():
        if not isinstance(e, dict) or e.get("publish") not in PUBLISH_MODES:
            raise LicenceError(f"{sid}: publish must be one of {sorted(PUBLISH_MODES)}")
        if not e.get("licence_basis"):
            raise LicenceError(f"{sid}: licence_basis is required")
        excerpts = e.get("approved_excerpts") or []
        if e["publish"] == "metadata_only" and excerpts:
            raise LicenceError(f"{sid}: metadata_only cannot list approved excerpts")
        if e["publish"] == "approved_excerpts" and not excerpts:
            raise LicenceError(f"{sid}: approved_excerpts needs at least one approved excerpt")
        for x in excerpts:
            if not isinstance(x, dict) or set(x) != EXCERPT_KEYS or not all(str(x[k]).strip() for k in EXCERPT_KEYS):
                raise LicenceError(f"{sid}: each excerpt needs exactly {sorted(EXCERPT_KEYS)}, all non-empty")
    return entries


def source_id_of(cite_id: str) -> str:
    return cite_id.split("#", 1)[0]
