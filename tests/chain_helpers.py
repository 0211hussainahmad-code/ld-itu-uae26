"""Build small, VALID checkpoint chains for gate and report tests (eval/checkpoint.py)."""
import json
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "eval"))
import checkpoint as ckpt  # noqa: E402


def make_run(tmp, status, recs, final=True, identity=None, raws=None, part=1):
    """A part folder whose chain holds `recs` (one record file each, optional raw dicts by key)."""
    st = ckpt.Store(tmp, part, identity or {"commit": "x"})
    st.promote({}, [], {}, status="base")
    ents = {}
    for r in recs:
        k = ckpt.okey(r["case"], r["config"], r["repeat"])
        v = st.next_version("records", k)
        rel, sha = st.put("records", f"{k}.{v}.json", r)
        raw = (raws or {}).get(k)
        rrel, rsha = st.put("raw", f"{k}.json", raw) if raw is not None else (None, None)
        ents[k] = {"record": rel, "record_sha256": sha, "raw": rrel, "raw_sha256": rsha, "part": part}
    st.promote(ents, [], {}, status=status, final=final)
    write_views(tmp)
    return tmp


def write_views(tmp):
    state, probs = ckpt.validate(tmp)
    assert not probs, probs
    lines = "".join(json.dumps(r, default=str) + "\n" for r in state["records"].values())
    (tmp / "results.jsonl").write_text(lines)
    (tmp / "summary.json").write_text(json.dumps({"status": {"status": state["status"]},
                                                  "run_meta": {"checkpoint": json.loads((tmp / ckpt.POINTER).read_text())}}))
