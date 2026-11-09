# AI assistance and authorship

LinkDown was built by Team Twofold (two BRAC University students) with substantial help from AI tools. This file says who did what, as far as the project records show.

## Development

| Contributor | Role | What the records show |
|---|---|---|
| Anthropic Claude (claude.ai build chats, Claude Code) | Main implementation agent | Wrote most of the code, tests, knowledge-base tooling, website and documentation. In the private development repository, 100 of the 123 commits on the website branch (PR #5 head) are authored "Claude". The public repository has a fresh history, so this cannot be checked from it. |
| OpenAI Codex | Implementation agent from 31 Oct 2026 | Built and hardened the four-role runner and live-demo safeguards (`exercise_demo/`, `scripts/demonstrate.py`) and safety fixes to the benchmark harness, by team decision. Several of these commits carry the repository owner's account name, not "Codex", so git metadata alone under-counts this work. |
| OpenAI GPT model (the team's "GPT-6" reviewer) | Independent reviewer and researcher | Reviewed designs, freezes and evidence and set release conditions. Independently checked six PDPL quotations against the official file. Wrote no project code. |
| Team members | Owners | Set the scope, downloaded the UAE source files, checked the legal clauses (both members signed for 6 PDPL clauses), approved every spend and decision, and are responsible for the submission. |

Attribution of individual commits to tools comes from the project handover and branch history. It was not verified commit by commit.

## In the running system

- Live runs used one model: `openai/gpt-oss-120b`, served by Groq (directly, or through OpenRouter pinned to Groq). No model was fine-tuned or trained.
- The offline runs use a scripted test double labelled `TEST-DOUBLE-NOT-AI`. It is not AI.
- The authority gate, human approval queue, audit log and replay are deterministic code. No model takes part in a gate decision.
- Prompts, retrieved passages, replies and the model's stated reasons are logged. Providers' hidden reasoning tokens are not requested or stored.
