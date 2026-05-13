# GutenDocx Session Handoff

Last updated: 2026-05-13 UTC

## Start Here

Read:

1. `PROJECT_LOG.md`
2. `AGENTS.md`
3. `.cursor/SESSION_HANDOFF.md`
4. `Docs/Implementation_Status_2026-05-12.md`
5. `Docs/Deploy_Runbook.md`
6. `Docs/README.md`

Do not rely on older Windsurf/Claude-specific files as active memory unless the user explicitly asks to reactivate them.

## Current Baseline

- Project path: `/ai/gutendocx`.
- Public URL: `https://gutendocx.unicloud.ca`.
- Purpose: private DOCX normalization / PDF export tool for one client plus the developer.
- Public discovery / SEO is not a goal.
- Public access is intentionally protected by Cloudflare Access.
- Server ingress: Cloudflare Tunnel `mainserver` -> `http://localhost:8000`.
- Runtime service: `gutendocx.service`.
- Runtime bind: `127.0.0.1:8000`.
- Runtime user: `root`, retained for now as a legacy compatibility constraint.
- Server/security ownership: `/ai/SECURITY`.
- App ownership: this repo.

## Recent Audit

2026-05-13 Windows upload compatibility fix:

- Client reported that on Windows, after pressing "Upload files", files were not visible/selectable.
- Main cause found in Web UI: hidden upload input used `webkitdirectory`, which opens folder-selection behavior instead of a normal file picker in Windows browser UX.
- Updated `gutendocx/web/static/index.html` so the primary upload control is a normal multi-file `.docx` picker with an explicit DOCX `accept` filter.
- Restored user-facing handling for empty/non-DOCX selections.
- Verified the running app serves the updated static HTML from disk via `http://127.0.0.1:8000/`; no service restart or Docker rebuild was needed.
- Ask the client to hard-refresh on Windows (`Ctrl+F5` or `Ctrl+Shift+R`) before retesting.

2026-05-12 read-only security alignment audit:

- `gutendocx.service` is active and listens on `127.0.0.1:8000`.
- `https://gutendocx.unicloud.ca/` returns a Cloudflare Access login redirect without an Access session.
- Local checks for `/`, `/health`, `/config`, `/files/simples`, `/fonts/list`, and `/openapi.json` work.
- `/output` is mounted as static app output. This is acceptable only behind Cloudflare Access; generated client files should still be treated as sensitive.
- The app has no built-in login and relies on Cloudflare Access, localhost bind, and host firewall.
- `dev.sh` uses `--reload --host 0.0.0.0`; do not use it as the production launcher.
- The repo has pre-existing uncommitted app/config changes. Do not assume they belong to this documentation alignment work.

2026-05-12 Codex documentation standardization:

- Added `PROJECT_LOG.md`, `Docs/Implementation_Status_2026-05-12.md`, `Docs/Deploy_Runbook.md`, and `Docs/README.md`.
- Updated `AGENTS.md` with cold-start order, documentation rules, and dormant-agent mirror guidance.
- Updated README production notes.
- No runtime, Cloudflare, firewall, database, or application behavior was changed.

## Next Recommended Work

1. Confirm the client Windows retest for `Upload files...`.
2. Keep Cloudflare Access enabled for `gutendocx.unicloud.ca`.
3. Add server-side hardening around the existing root runtime without changing users first:
   - consider a systemd drop-in with `NoNewPrivileges=true`, `PrivateTmp=true`, and narrowly scoped write paths after testing in a maintenance window.
   - do not change this casually because the app uses LibreOffice/Docker and writes to project directories.
4. Add a cleanup/retention policy for `Uploads/` and `output/` if client files should not stay on disk indefinitely.
5. Reconcile pre-existing uncommitted changes before any code-level security edits.

## Known Commands

```bash
systemctl status gutendocx --no-pager --lines=80
systemctl cat gutendocx
ss -lntup | rg ':8000'
curl -fsS http://127.0.0.1:8000/health
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://gutendocx.unicloud.ca/
```
