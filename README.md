# LinkDown — judge guide

**A synthetic crisis exercise for AI-run government services when the internet links fail.**
Team Twofold (BRAC University) · ITU AI for Good Lab Hackathon: United Arab Emirates, 2026 · technical report: `report/LinkDown_TECHNICAL_REPORT.pdf`

Four role agents (network operator, operations lead of an AI-run government service, regulator role, policy and legal adviser) handle three cascading connectivity events. Each role sees only its own view and inbox. Every proposed action passes a deterministic authority gate, organised as the ITU-T Y.3172 policy (P) node, that returns `PERMITTED`, `PROHIBITED` or `INSUFFICIENT_AUTHORITY_OR_EVIDENCE`. High-impact actions stop at a human approval queue. Every step is written to a hash-chained audit log that can be replayed independently. **Everything is synthetic.** Nothing connects to a real network, service or authority.

## 1. What you can check, and what kind of evidence it is

| You can… | Kind of evidence | How |
|---|---|---|
| Run all tests, offline | Engineering controls behave as specified. **Not** legal compliance, **not** AI quality | §3 step 4 |
| Run the full four-role, three-event exercise and verify it independently | **Scripted clients labelled NOT AI** (12 of 12 role-event cells). Plumbing evidence, not AI evidence | §3 steps 5–6 |
| Replay a recorded run in the browser and re-check its hash chain | The same scripted NOT-AI run (bundle `a918b89a9b4271a1`, 127 records, audit head `86b18428c0af7220c93c5aa5b901c1b5fdbb119e098305b4aca6c8ed66249812`) | §3 step 7 |
| Rebuild and query the knowledge base | Built with ITU's reference code; BM25 retrieval | `kb/SUBMISSION_PACKAGE/README.md` |
| Read the source provenance | 20 sources with status, licence and sha256 | `kb/SUBMISSION_PACKAGE/` |

What is retained privately (not published, because the files contain prompts with ITU and UAE source text; access to redacted evidence can be coordinated subject to confidentiality, copyright and consent constraints):

- the two live single-role runs with a real model (Groq `openai/gpt-oss-120b`, 23 Oct 2026). Run 1 was stopped by the gate, nothing executed. Run 2 chose the in-country endpoint, the state changed, and the log verified and replayed. n = 1;
- the full run folders (prompts, retrieved passages, replies) of any run.

What does **not** exist yet:

- a live four-role run that passes verification. The first genuine-AI attempt (6 Nov 2026) was incomplete, reaching 5 of 12 role-event cells, and is not counted;
- the provider bake-off;
- a same-tools single-agent baseline;
- any completed legal-verification ledger entry;
- a public vector index (a private local one scored 26/30 against BM25's 29/30 on the 146-chunk build; `kb/SUBMISSION_PACKAGE/README.md` §3);
- a deployment.

## 2. Requirements

- Python 3.12 (CI) or 3.13; git; about 200 MB of disk for ITU's reference repository (fetched at a pinned commit, not redistributed here).
- Node 22, only for the website.
- No API key and no paid service for anything in §3.

## 3. Reproduce (offline, free)

```bash
# 1. ITU reference code at the pinned commit (chunker and metadata functions)
bash scripts/get_itu_reference.sh
# 2. Python dependencies
pip install -r requirements.txt
# 3. Knowledge base (builds kb/build/chunks.jsonl locally; source text is never committed)
python kb/build_kb.py
python kb/eval_retrieval.py
# 4. Tests (no test should skip in this copy; 5 are deselected, see §5)
python -m pytest -q -rs
# 5. Four-role E1-E3 exercise, scripted clients labelled NOT AI; prints RUN_DIR and AUDIT_HEAD
python scripts/demonstrate.py
# 6. Independent verification of that run (integrity, coverage, replay through the final state)
python scripts/demonstrate.py --verify RUN_DIR --expected-head AUDIT_HEAD
# 7. Website (static replay)
cd web/app && npm ci && npm run build && npm run preview    # http://localhost:4173
```

On Windows, run step 1 in Git Bash and set `PYTHONUTF8=1` before the tests.

Step 5 creates a new run with its own audit head, so pass the head that step 5 printed to step 6, not the published head `86b18428…`. The published head is checked on the website's Audit page (step 7) and in §1.

Expected results for this export are recorded in `PUBLIC_EXPORT_MANIFEST.json` and in §6 of this file.

Do not publish anything under `runs/`. Run folders contain prompts with copyrighted source text.

**Optional live run (costs money; not needed for judging).** `scripts/demonstrate.py --live-plan … --authorize-live-spend` with your own key for a reviewed profile. It refuses to start without a spending plan, a cap that covers the worst case, and an interactive human controller. See `docs/FULL_EXERCISE.md`.

## 3a. Guided walkthrough (about 15 minutes)

Everything below is the scripted run (**TEST-DOUBLE-NOT-AI**). It shows the machinery, not AI behaviour. The single genuine-AI evidence (one live single-role decision, n = 1) is described in the report §5 and is held privately.

| # | Do | You should see |
|---|---|---|
| 1 | Open the site (§3 step 7). Read the landing page's first screen | The headline question (who decides when the cables go dark); the TEST-DOUBLE-NOT-AI label beside the action |
| 2 | Scroll Acts I–III; in Act III choose each role chip | Each role's view: what it **Sees**, what it is **Not given**, what it **May propose**. No role is given the network map |
| 3 | Act IV, "The Decision Gate": press **Next** through the six stages | The case-file transfer to Asia-South: its sources, the unverified rules, the outcome *Needs a competent authority*; the simulated controller does not approve; **nothing carried out** |
| 4 | Open **Walkthrough**, step 4 | The binding priority order stops at the gate (records #87 and #112); the scripted gap drafts, and where the five real gap hypotheses are (report §6, `config/gaps.yaml`) |
| 5 | Open **Audit**; choose a record under "Record to change", press **Change it and verify**, then **Restore the original** | First 127 of 127 records rehashed; after the change, the chain breaks at the chosen record; after restoring, 127 of 127 again. Head `86b18428…9812`, the same as §1 of this README |
| 6 | Open **Replay**; jump to event 2; open "the evidence for this decision" | The gate's trail for that decision, its citations and their warnings; Escape closes the drawer |
| 7 | Terminal: §3 steps 5–6 | `RUN_DIR` and `AUDIT_HEAD` printed; the verify step reports `"passed": true`, `coverage` for all 12 role-event cells (E1–E3 × 4 roles), and `metrics` with 19 proposals: 15 `PERMITTED`, 4 `INSUFFICIENT_AUTHORITY_OR_EVIDENCE`, 0 `PROHIBITED`, `human_approved` 0 (the counts in report §5). **Your `AUDIT_HEAD` will differ from the published `86b18428…`**: every run records its own run id and times, so each run has its own head. The published head belongs to the recorded bundle the website replays |
| 8 | Terminal: `python -m pytest -q tests/test_gate.py` | The gate's safety tests pass, including all 20 pre-written variations |
| 9 | Read `docs/CLAIMS.md` | What is and is not claimed. A first genuine-AI four-role attempt (6 Nov 2026) was incomplete (5 of 12 cells) and is not counted |

## 4. Where each judging criterion is addressed

| Criterion | Where to look |
|---|---|
| Knowledge base quality | `kb/SUBMISSION_PACKAGE/`, `kb/sources.yaml`, report §4 |
| Agent capability | Report §5. Scripted runs and n = 1 live evidence only (see §1) |
| Policy, strategy and standards gaps | Report §6 (hypotheses, qualified wording, global examples) |
| Auditability | `linkdown/audit.py`, `scripts/replay.py`, `scripts/demonstrate.py --verify`, the website audit page. Logged per turn: prompt, retrieved passage ids, assessment, options considered with reasons, unknowns, a justification and citations per action, the gate's rule and outcome, the human decision, and state digests. Providers' hidden reasoning tokens are not stored |
| Alignment with ITU standards | Report §3–§4; `linkdown/gate.py` (P node); `config/topology.yaml` (sandbox) |

## 5. What changed from the private repository

This is a clean export: no git history, no evidence branch, no CI artifacts, no credentials. Every file, with its sha256 and origin, is in `PUBLIC_EXPORT_MANIFEST.json`. The public-only changes are:

- comment and doc wording that quoted ITU-T Y.3172 or the PDPL is replaced by clause references (`linkdown/gate.py`, `config/rules.yaml`, `docs/CLAIMS.md`);
- the verbatim UAE excerpts (`kb/curated/clauses.yaml`) are left out;
- the never-run benchmark harness (`eval/`, apart from three transport modules) is left out;
- CI uploads no run folders;
- five tests are deselected in `pytest.ini`: two compare with the omitted benchmark file, three read private website-pipeline files (deployment plan, branch workflow, pipeline requests) that are not in this copy;
- `docs/CLAIMS.md` is the public version of the claims register: private evidence is labelled as such, and the public and private knowledge-base builds are distinguished.

**This export is therefore not byte-identical to the frozen benchmark tags.** Freeze equivalence is checked in the private repository only.

## 6. Results recorded for this export

See `PUBLIC_EXPORT_RESULTS.md` (written when the export is tested).

## 6a. Repository map

| Path | What it is |
|---|---|
| `report/LinkDown_TECHNICAL_REPORT.pdf` | The technical report (official template, 5 pages) |
| `linkdown/` | Exercise engine: authority gate (`gate.py`, the Y.3172 P node), state, simulator, orchestrator, audit log, retrieval |
| `config/`, `scenarios/` | Synthetic topology, rules (legal and exercise), roles, gap register (`config/gaps.yaml`); the three events and 20 variations |
| `exercise_demo/`, `scripts/` | Four-role runner and its verifier; replay; single-run and live entry points |
| `kb/` | Knowledge-base build (ITU reference code), source register, analyst notes, retrieval questions; `kb/SUBMISSION_PACKAGE/` is the KB deliverable |
| `tests/`, `web/tests/` | Python tests (`pytest.ini` explains the 5 deselections) |
| `web/app/` | Static website (replay, walkthrough, audit), with its browser tests |
| `docs/` | Public claims register, authority matrix, four-role runner guide |
| `AI_ASSISTANCE.md`, `THIRD_PARTY_NOTICES.md`, `NOTICES-dependencies.md`, `PUBLIC_EXPORT_MANIFEST.json`, `PUBLICATION_SCAN_REPORT.md` | Authorship, third-party and dependency licences (font licences in `web/app/public/licenses/fonts/`), every file's sha256 and origin, the publication scan |

## 6b. Evidence index

| Claim | Where to check it |
|---|---|
| The gate decides from state facts, not model arguments | `tests/test_gate.py::test_facts_come_from_state_not_from_model_arguments` |
| An unverified legal rule escalates; a verified prohibition never reaches a human | `tests/test_gate.py` |
| The legal verification ledger has no completed entries | `kb/verification_ledger.yaml` |
| Analyst notes change no decision | `tests/test_safety.py::test_hostile_analyst_note_changes_no_decision` |
| The audit log is tamper-evident and independently replayable | `tests/test_core.py`, `tests/test_safety.py`, `scripts/replay.py`, §3 steps 5–6 |
| The four-role E1–E3 run (scripted, NOT AI) passes integrity and replay | §3 steps 5–6; `tests/test_demonstration.py` |
| The website's run and its audit head | `web/data/bundles/manifest.json` (head `86b18428c0af7220c93c5aa5b901c1b5fdbb119e098305b4aca6c8ed66249812`); the site's Audit page rehashes 127/127 |
| KB contents, provenance, licence and verification status | `kb/SUBMISSION_PACKAGE/` |
| Y.3172 and AI Readiness mapping; local-policy mapping; gaps | Report §3, §4, §6; `config/gaps.yaml` |
| What is claimed and what is not | `docs/CLAIMS.md` |

## 7. Licence and credits

- **Licence:** original project code is under the MIT licence (`LICENSE`); original team-written documentation and knowledge-base metadata are under CC BY 4.0 (`LICENSE-docs.md`). Neither covers third-party material. Dependencies keep their own licences.
- Dependencies and fonts keep their own licences: `NOTICES-dependencies.md`. The knowledge-base build needs PyMuPDF (AGPL-3.0 or commercial), which `pip` installs separately.
- ITU reference code (CrashingGuru/ITUAIReadiness, MIT) is fetched, not redistributed.
- ITU publications are © ITU and are not included. UAE and other sources are listed with URLs; their text is not included.
- AI assistance: `AI_ASSISTANCE.md`. Claims we do and do not make: `docs/CLAIMS.md`.
