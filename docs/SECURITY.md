# Security and accessibility review (Phase 8)

Scope: the code in this repository running locally against **synthetic data**. This is not a hardened internet-facing deployment, and the notes below say where that matters.

## What was checked
| Area | Result |
|---|---|
| Dependencies | `pip-audit` and `npm audit --omit=dev` report no known vulnerabilities at release; both run in CI (`make audit`). |
| SQL injection | Dashboard queries use bound parameters; sort columns come from a fixed allow-list. |
| User-written SQL (assistant) | Three layers (syntax tree, query plan, engine lock). 54 unsafe SQL and 14 unsafe questions refused; see [ASSISTANT.md](ASSISTANT.md). |
| File access from SQL | Engine started with external access disabled and configuration locked before serving. |
| Input validation | Request bodies are typed (pydantic); statuses are enumerated; notes and names have length limits; the form requires a name and, for explained or resolved, a note. |
| Browser | Security headers on every page (`nosniff`, frame denial, same-origin referrer, restricted permissions); `X-Powered-By` removed; CORS limited to the local dashboard origin and three methods. |
| Secrets | None in the repository. The optional model key is read from the environment only. |
| Logging | One structured JSON line per API request (method, path, status, milliseconds); no query text or request bodies are logged. Pipeline alerts go through `tally.alerts`. |
| Data | Synthetic only. No customer, bank or employer data anywhere. |

## Known limits (stated, not hidden)
- **No sign-in.** The decision form asks for a name, which is recorded in the history, but nothing proves who typed it. Anything beyond a local demo needs real authentication and per-user roles before the write endpoint is exposed.
- **No rate limiting or TLS** in the app itself; put it behind a proxy for anything shared.
- A single API process holds the database; it is not built for many concurrent writers.

## Accessibility (WCAG 2.1 AA, automated)
The acceptance suite runs axe-core (WCAG 2a, 2aa, 2.1 AA rules) on all six pages and fails on any serious or critical finding. It found real issues during hardening, now fixed: muted text and the warning colour fell below 4.5:1 contrast, and decorative bars were exposed as unnamed meters. Also in place: skip link, landmarks, labelled form fields, focus trap and Esc in the dialog, visible focus, no horizontal scroll at 390 px.

Automated checks catch roughly a third of accessibility problems. A manual screen-reader pass (scenario R5) is part of manual UAT and is **not** claimed here.
