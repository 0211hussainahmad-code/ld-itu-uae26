# Claims register

Rule: the report, video, README and pitch may only contain claims from the **Can say now** column. When a test or source check moves a claim, update this file in the same commit.

Last updated: 7 Nov 2026, public submission copy. Evidence marked (private) is not in this repository: it is retained privately; access to redacted evidence can be coordinated subject to confidentiality, copyright and consent constraints. Original prompt and turn logs and third-party text are not published.

Knowledge base configurations: the 170-chunk figure describes the private, excerpt-containing build (retrieval 27/30 in the top three). The conservative public export omits the 24 verbatim UAE passages (18 PDPL clauses, 6 NCSP-summary passages) and was tested with 146 chunks (retrieval 29/30). Both builds use BM25; a separate local vector index (ITU `KnowledgeBase`, `all-MiniLM-L6-v2`, CPU only) was evaluated privately: 26/30 on the 146-chunk build, below BM25's 29/30. It is not published and is not distributed or hosted. Any retrieval number must say which build it refers to.

Status in one line: the four-role exercise has run end to end only with scripted clients labelled NOT AI; one live single-role decision exists (n = 1); a first genuine-AI four-role attempt (6 Nov 2026) was incomplete (5 of 12 role-event cells) and is not counted; the provider bake-off and a same-tools baseline were not executed; the legal verification ledger has no completed entries.

## Can say now (evidence exists in this repository, or privately where marked)

| Claim | Evidence |
|---|---|
| The separate full-exercise runner covers all four roles in E1, E2 and E3 offline, checks saved-turn integrity, and independently replays gate decisions, approval bindings and final state. This is scripted plumbing evidence, NOT live AI evidence | `tests/test_demonstration.py`, `scripts/demonstrate.py`, `exercise_demo/`, `docs/FULL_EXERCISE.md`; reproduce with `python scripts/demonstrate.py` and `--verify RUN_DIR --expected-head AUDIT_HEAD`; recorded 31 Oct run summary (private: retained privately; access to redacted evidence can be coordinated subject to confidentiality, copyright and consent constraints; not published because run files contain prompts with copyrighted source text) |
| The authority gate gives the expected outcome for all 20 seeded variations, written before the code ran | `tests/test_gate.py::test_all_20_variations_match_expected_outcomes` |
| A prohibition based on a source not checked against the primary text is escalated to a human, not enforced as law | `test_unverified_prohibition_is_escalated_not_silently_allowed` |
| A verified prohibition cannot be approved by a human | `test_verified_prohibition_cannot_go_to_a_human` |
| The gate takes facts from the exercise state; a model cannot change the outcome by lying in its arguments | `test_facts_come_from_state_not_from_model_arguments` |
| Every state change follows a gate decision that allowed it | `test_every_state_change_follows_a_non_prohibited_gate_decision` |
| The audit log detects edited or deleted records; with the head recorded outside the run folder (for example a CI log or a commit message) it also detects truncation. "Tamper-evident", never "immutable" | `tests/test_core.py` audit tests |
| Citations to passages that were not retrieved are flagged | `test_parse_flags_invented_citations_and_converts_messages` |
| The knowledge base is built with ITU's reference chunker and metadata functions, at a recorded commit (full-text documents; curated verbatim clauses are cut at article boundaries by `kb/extract_clauses.py` and carry ITU's metadata) | `kb/build_kb.py`, `itu_metadata` in every chunk, `itu_reference_commit` in `kb/build/kb_manifest.json` |
| A legal rule, whether prohibition or permission, takes effect only with a complete verification-ledger entry (two human verifiers, verbatim quote, file hash); until then the gate escalates. Exercise-only permissions are labelled NOT_ASSESSED, never "lawful" | `tests/test_safety.py` ledger tests, `test_unverified_legal_permission_escalates`, `test_exercise_only_permission_is_labelled_not_assessed` |
| Analyst notes cannot change any gate decision, cannot crowd official text out of the evidence, and cannot by themselves support a gap finding | `test_hostile_analyst_note_changes_no_decision`, `test_notes_cannot_crowd_out_source_text`, `test_unrelated_primary_citation_does_not_lift_a_note_based_gap` |
| A model that proposes only forbidden actions gets none executed; every proposal is still counted and logged | `test_hostile_model_gets_nothing_forbidden_executed` |
| An unresolved-authority action can only proceed through a labelled, SIMULATED competent-authority decision with a written basis; an ordinary approval cannot authorise it | `test_authority_approval_needs_a_written_basis_and_is_labelled` |
| Approvals expire if the state changes; the same action is never executed twice | `test_stale_approval_is_rejected`, `test_same_action_is_not_executed_twice` |
| Every recorded state change and gate decision can be re-derived from the scenario, the rules and the log (replay), independently of the hash chain | `scripts/replay.py`, `test_replay_catches_a_rewritten_log_even_with_a_valid_chain` |
| Retrieval: 27 of 30 draft questions are answered by a top-3 chunk (questions written by the same author as the notes; 29 of 30 before the UAE excerpts were added on 24 Oct) | `python kb/eval_retrieval.py` |
| The knowledge base contains 18 verbatim clauses of the UAE PDPL (Federal Decree-Law 45/2021, official English translation from the UAE legislation portal), each machine-checked as verbatim and on the stated page of a file whose sha256 is recorded, and 6 verbatim passages from two official government pages summarising the National Cloud Security Policy. Always add: 6 of the 18 PDPL clauses are `human_checked` (both team members checked headings, article numbers and pages; word match by machine check plus an independent GPT reviewer), 12 are `extracted_unverified`, the verification ledger is empty, and the summary pages are not the policy text | `kb/extract_clauses.py` (rebuild from the official PDF, see `kb/SUBMISSION_PACKAGE/README.md`), `kb/build/fetch_manifest.json` (file sha256); the excerpt file `kb/curated/clauses.yaml` is not published in this copy (private: retained privately; access to redacted evidence can be coordinated subject to confidentiality, copyright and consent constraints; not published because no redistribution licence for the UAE texts was found) |
| The PDPL's official English text excludes government data and governmental entities that control or process personal data from its scope (Art. 2(2)(a)-(b), p. 6). Cite the article; never restate it as a claim that government data is unregulated | Chunk `uae-pdpl-2021#art2` after rebuilding from the official PDF; excerpt file (private) |
| Model sentences that use legal-authority words (lawful, authorised, compliant, ...) without an "unverified" or "assumption" label are flagged, counted and labelled in every run report: "UNVERIFIED LEGAL WORDING", or "NEEDS HUMAN LEGAL REVIEW" when a verified source is cited. Nothing is marked legally verified automatically | `test_smoke2_legal_wording_is_flagged_as_unverified`, `test_release_assertion_every_flagged_sentence_is_labelled_in_the_report` |
| Replay fails if the rules, ledger, topology or scenario have changed since the run, and states that it does not check citation relevance or legal correctness | `test_replay_fails_when_the_run_inputs_have_changed` |
| All network figures are synthetic | `config/topology.yaml` header and the `synthetic: true` check |
| A real language model (Groq `openai/gpt-oss-120b`) made a live decision in the exercise (Event 2, one role): it weighed 5 options, chose the in-country endpoint, the gate permitted it as an exercise action (not a legal finding), and the simulated state changed. The run is logged, verified and replayable. Always add: this was the second attempt, after a first run stopped by the gate, and it is one run (n = 1). Both smoke runs used prompts-0.3, which showed only the first 700 characters of each passage (fixed in prompts-0.4) | Live run `20261023T190532Z-smoke` and the team's review records (private: retained privately; access to redacted evidence can be coordinated subject to confidentiality, copyright and consent constraints; not published because run files contain prompts with copyrighted source text) |
| An earlier live run where the model proposed moving confidential files abroad was stopped by the gate and nothing executed | Live run `20261023T185114Z-smoke` (private: retained privately; access to redacted evidence can be coordinated subject to confidentiality, copyright and consent constraints; not published because run files contain prompts with copyrighted source text) |
| The verification ledger has no completed entries, so no gate decision in any run rests on verified law; every legal rule escalates as `INSUFFICIENT_AUTHORITY_OR_EVIDENCE` | `kb/verification_ledger.yaml` (`entries: []`), `tests/test_gate.py` |
| A static website replays one offline NOT-AI four-role run (bundle `a918b89a9b4271a1`, 127 audit records) and re-verifies its hash chain in the browser; it publishes no prompts, turn files or third-party text. Not deployed | `web/data/bundles/manifest.json`, `web/publication/` |
| The provider bake-off was specified, frozen and preflight-checked, but **not executed**; no bake-off result exists | Benchmark harness and freeze tags (private) |

## Cannot say yet (planned; needs the evidence in the right column)

| Claim | What would make it true |
|---|---|
| "Live AI agents" in a full multi-role exercise | A live four-role run that passes `scripts/demonstrate.py --verify ... --require-live --require-interactive-human`, with its audit head anchored outside the run folder and provider usage reconciled. Status: the first attempt (6 Nov 2026) was incomplete (5 of 12 role-event cells); it is not counted |
| Any reliability or quality rate for the AI | The bake-off and evaluation runs (one smoke run is n = 1) |
| Any statement about model quality (accuracy, refusal rate, citation rate) | Eval harness over the 20 variations with a real model |
| Which model provider is best, or "we chose model X because it reasons better about UAE law" | Bake-off results (provisional: frozen pre-primary-UAE-text corpus (ITU source chunks plus labelled analyst notes)) and then a source-verified UAE legal cohort (GPT-6 R0b R18) |
| Citations support the model's legal or data-location claims ("grounded", "cited") | UAE primary texts in the KB (R1, T11) and citation relevance scored in the bake-off and eval. Today the one live citation (Y.3172 c22) does **not** support its claim |
| "Better than a single agent" | Same-tools single-agent baseline, run on the same cases (1–3 Nov) |
| "Tested by outside users" | Two external browser tests of the deployed app |
| "Clause-level verified UAE law" for the National Cloud Security Policy | Team opens the CSC PDF, records the clause numbers, sets `verification: primary_verified` |
| "Human-verified PDPL clauses" (ledger entries) | Signed by both team members on 25 Oct. Their own check covers headings, articles and pages; the word-level match rests on the machine check plus GPT-6. The ledger entries were deferred until after the bake-off run, which was not executed; the ledger has no completed entries. Until then say "checked by the team and independently verified as verbatim", not "verified law" |
| Any gap is "supported" | Primary-text comparison, a search for counter-examples, and wording reviewed by both team members |
| Retrieval score on blind questions | 20 questions written by the team without reading the notes |
| Arabic support | Arabic sources in the KB and Arabic retrieval questions |
| "LinkDown is deployed / publicly available" | A deployment URL that opens from two outside devices, recorded with date and commit. CI success is not deployment evidence |
| "The judges can add an event during the run" | A tested event-injection path. Today an added event means editing a scenario copy and re-running |
| "The knowledge base is vectorized / distributed / hosted in the ITU AI for Good Lab" | A built and tested vector index (ITU `KnowledgeBase`, recorded in the KB manifest), and separately any hosting in the Lab. A local index was evaluated privately (26/30 on the 146-chunk build, below BM25) and is not published; no distributed or hosted index exists; retrieval is BM25 |
| "The knowledge base is complete for UAE cloud policy" | NCSP v2.0 primary text in the KB with clause numbers, checked by both team members |

## Never say (from the revision pack, section 9)

- "Nobody has ever built this." (Prior art exists: New Delhi Build-a-thon 5.0 women's prize "Handshake Protocol: law-aware AI agents for 5G emergency response"; ITU Riyadh 2026 winners SANAD, AI Guardian and Samaam for deterministic policy gates with citations; Microsoft Agent Governance Toolkit; tabletop exercises; network digital twins.)
- "Our gate is a novel safety mechanism." (It is standard practice; our contribution is the exercise and the gap findings.)
- "The UAE has no legal protections for government data."
- "Foreign-cloud fallback is always illegal."
- "TDRA must impose exactly this national traffic-priority order."
- "Our simulated routes show actual du/e& traffic or real capacities."
- "This agent has actual government authorization."
- "The system is compliant with all UAE laws."
- "The judges will select this because it scores 90+."
- "We expose the model's chain of thought." (We log prompts, retrieved passages, replies, tool calls and short written justifications; not hidden reasoning.)
- "The AI's decision was legally grounded / lawful / compliant." (The endpoint switch was an exercise permission, `NOT_ASSESSED`; its legal wording was unverified.)
- "Model X was shown to be best at UAE legal reasoning." (No UAE source is verified yet; any bake-off result is provisional.)
- "The live run shows the model succeeds" or any success rate from the smoke runs. (Two development runs, the second after a prompt revision; not a blind rate.)
- "Four AI agents ran the full crisis exercise." (Only scripted clients have; the live attempt was incomplete.)
- "Our CI shows the system is deployed / works in production." (CI runs offline tests; nothing is deployed.)
- "We benchmarked providers and chose the best one." (The bake-off was not executed.)
- "The gate enforces UAE law." (The ledger is empty; every legal rule escalates.)
- "The 6 Nov live run partly succeeded", or any rate derived from 5/12. (An incomplete attempt is reported as incomplete.)
- "Verified by the team" for the 12 `extracted_unverified` PDPL clauses.
