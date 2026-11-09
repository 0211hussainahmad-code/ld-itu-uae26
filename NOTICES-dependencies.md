# Dependency licences

This file only lists third-party licences. It grants no licence to LinkDown's own code or documentation.

None of the packages below is included in this repository. They are installed by `pip install -r requirements.txt` or `npm ci`, and each keeps its own licence. Licences as stated in each package's metadata, read 8 Nov 2026.

## Python (requirements.txt)

| Package | Licence |
|---|---|
| httpx | BSD-3-Clause |
| PyYAML | MIT |
| networkx | BSD-3-Clause |
| beautifulsoup4 | MIT |
| ollama | MIT |
| pydantic, pydantic-settings | MIT |
| chromadb | Apache-2.0 |
| pytest | MIT |
| PyMuPDF | AGPL-3.0, or a commercial licence from Artifex |
| Indirect dependencies (installed automatically) | permissive (MIT, BSD, Apache-2.0, ISC), except certifi (MPL-2.0), tqdm (MPL-2.0 and MIT) and orjson (MPL-2.0 and Apache-2.0 or MIT). pymupdf4llm and pymupdf_layout 2.0 are empty packages required by PyMuPDF 2.0 |

PyMuPDF is licensed under AGPL-3.0 (or a commercial licence from Artifex). It is not included in this repository; `pip install -r requirements.txt` installs it, and its own licence applies to it. It is used by `kb/build_kb.py` and `kb/extract_clauses.py` to read PDF files. If you distribute LinkDown together with PyMuPDF, PyMuPDF's licence applies to that distribution.

## Website (web/app/package-lock.json)

| Package | Licence |
|---|---|
| react, react-dom, react-router, zod | MIT |
| Shipped in the built site besides the above: cookie, scheduler, set-cookie-parser | MIT |
| Build-only tools (Vite, TypeScript, Playwright, axe-core and others) | MIT, Apache-2.0, MPL-2.0, ISC or BSD-3-Clause, as stated in the lockfile's packages |

## Fonts embedded in the built website

IBM Plex Sans, IBM Plex Mono and Newsreader (`@fontsource/*` 5.3.0) are licensed under the SIL Open Font License 1.1 (https://openfontlicense.org). They are fetched by `npm ci` and embedded in `web/app/dist` when the site is built. Their licence texts are in `web/app/public/licenses/fonts/` and are copied into the built site with it.

## Security note (9 Nov 2026)

`pip-audit` reports four advisories for chromadb 1.5.9, the latest release: CVE-2026-45829, CVE-2026-45830, CVE-2026-45831 and CVE-2026-45833. They concern Chroma's HTTP server and its server-side authorization. No fixed release exists yet. LinkDown, and the ITU reference code it uses, run chromadb only as an embedded, in-process client (`PersistentClient`, `EphemeralClient`), with no server. Do not expose the knowledge base through `chroma run` or an HTTP client until a fixed release is available.

