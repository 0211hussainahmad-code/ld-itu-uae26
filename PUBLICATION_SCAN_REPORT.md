# Publication scan report

Export: `linkdown-public` · files scanned: 175 · reference chunks: 159 (third-party source text from the locally built KB)

**HIGH 0 · MEDIUM 35 · LOW 0**

Codes: T third-party text · Q quotation for human review · S secret pattern · P personal data · L licence · F forbidden file type · C unproven claim. Findings never reproduce the matched text.

A clean T result is not permission to publish: only text present in the KB can be detected. Q findings need a human decision; short quotation is not assumed to be permitted.

| Sev | Code | Where | What |
|---|---|---|---|
| MEDIUM | F | `report/LinkDown_TECHNICAL_REPORT.pdf` | team report PDF: text scanned automatically; inspect the rendered pages by hand before publication |
| MEDIUM | L | `kb/sources.yaml` | licence basis unknown for canada-dadm-2025 |
| MEDIUM | P | `LICENSE:3` | team-member name |
| MEDIUM | P | `report/LinkDown_TECHNICAL_REPORT.pdf` | PDF text: e-mail address at domain gmail.com |
| MEDIUM | P | `report/LinkDown_TECHNICAL_REPORT.pdf` | PDF text: team-member names (expected in the report header; team decision) |
| MEDIUM | P | `web/tests/test_web_publication.py:203` | e-mail address at domain private-example.org |
| MEDIUM | Q | `docs/CLAIMS.md:33` | quoted passage of 10 words beginning 'label are flagged, …' |
| MEDIUM | Q | `docs/CLAIMS.md:49` | quoted passage of 11 words beginning 'we chose model …' |
| MEDIUM | Q | `docs/CLAIMS.md:54` | quoted passage of 9 words beginning 'checked by the …' |
| MEDIUM | Q | `docs/CLAIMS.md:58` | quoted passage of 6 words beginning 'LinkDown is deployed …' |
| MEDIUM | Q | `docs/CLAIMS.md:59` | quoted passage of 9 words beginning 'The judges can …' |
| MEDIUM | Q | `docs/CLAIMS.md:60` | quoted passage of 16 words beginning 'The knowledge base …' |
| MEDIUM | Q | `docs/CLAIMS.md:61` | quoted passage of 9 words beginning 'The knowledge base …' |
| MEDIUM | Q | `docs/CLAIMS.md:65` | quoted passage of 9 words beginning 'Handshake Protocol: law-aware …' |
| MEDIUM | Q | `docs/CLAIMS.md:66` | quoted passage of 7 words beginning 'Our gate is …' |
| MEDIUM | Q | `docs/CLAIMS.md:67` | quoted passage of 9 words beginning 'The UAE has …' |
| MEDIUM | Q | `docs/CLAIMS.md:69` | quoted passage of 8 words beginning 'TDRA must impose …' |
| MEDIUM | Q | `docs/CLAIMS.md:70` | quoted passage of 10 words beginning 'Our simulated routes …' |
| MEDIUM | Q | `docs/CLAIMS.md:71` | quoted passage of 6 words beginning 'This agent has …' |
| MEDIUM | Q | `docs/CLAIMS.md:72` | quoted passage of 8 words beginning 'The system is …' |
| MEDIUM | Q | `docs/CLAIMS.md:73` | quoted passage of 9 words beginning 'The judges will …' |
| MEDIUM | Q | `docs/CLAIMS.md:74` | quoted passage of 7 words beginning 'We expose the …' |
| MEDIUM | Q | `docs/CLAIMS.md:75` | quoted passage of 10 words beginning 'The AI's decision …' |
| MEDIUM | Q | `docs/CLAIMS.md:76` | quoted passage of 11 words beginning 'Model X was …' |
| MEDIUM | Q | `docs/CLAIMS.md:77` | quoted passage of 7 words beginning 'The live run …' |
| MEDIUM | Q | `docs/CLAIMS.md:78` | quoted passage of 8 words beginning 'Four AI agents …' |
| MEDIUM | Q | `docs/CLAIMS.md:79` | quoted passage of 11 words beginning 'Our CI shows …' |
| MEDIUM | Q | `docs/CLAIMS.md:80` | quoted passage of 8 words beginning 'We benchmarked providers …' |
| MEDIUM | Q | `docs/CLAIMS.md:82` | quoted passage of 7 words beginning 'The 6 Nov …' |
| MEDIUM | Q | `kb/SUBMISSION_PACKAGE/README.md:3` | quoted passage of 7 words beginning 'Knowledge base containing …' |
| MEDIUM | Q | `kb/SUBMISSION_PACKAGE/README.md:56` | quoted passage of 8 words beginning 'cross-border transfer of …' |
| MEDIUM | Q | `kb/build_kb.py:52` | quoted passage of 6 words beginning 'alone on a …' |
| MEDIUM | Q | `scenarios/base.yaml:78` | quoted passage of 7 words beginning 'publicly available sources …' |
| MEDIUM | S | `tests/test_demonstration.py` | 2 match(es) of secret pattern '(?i)bearer\s+[A-Za-z0-9.' (test fixture? human to confirm) |
| MEDIUM | S | `tests/test_safety.py` | 1 match(es) of secret pattern '(?i)bearer\s+[A-Za-z0-9.' (test fixture? human to confirm) |
