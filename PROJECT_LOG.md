# GutenDocx - Project Log

**Cold start (new Codex chat, no history):** Read `PROJECT_LOG.md` -> `AGENTS.md` -> `.cursor/SESSION_HANDOFF.md` -> `Docs/Implementation_Status_2026-05-12.md` -> `Docs/Deploy_Runbook.md` -> `Docs/README.md`.

**Token discipline:** Read only through **Current Session**, **Current State**, and **Next Tasks** first. Open deeper historical docs only when needed.

---

## Current Session - Resume Point

**2026-05-13:** Fixed Windows upload picker compatibility.

Current iteration:

- Investigated a client report that after pressing "Upload files" on Windows no files were visible/selectable.
- Root cause: the hidden upload input had been using `webkitdirectory`, which opens a folder picker rather than a normal file picker in Windows browser UX.
- Updated the Web UI upload input to use normal multi-file `.docx` selection with an explicit DOCX `accept` filter.
- Restored clear client-side handling for "no DOCX selected" and skipped non-DOCX files.
- Verified the running FastAPI service serves the updated `index.html` from disk; no service restart or Docker rebuild is required for this static HTML change.
- Production security model remains unchanged: Cloudflare Access protected, tunnel to `127.0.0.1:8000`.
- Committed the remaining pending app changes as requested:
  - GPT-5 Mini default for cover vision;
  - OpenAI token usage extraction and AI cost summaries;
  - batch `/apply` handling with per-file output directories, ZIP packaging, PDF page counts, and XLSX report generation;
  - cover detection improvements for rendered page breaks and author/year grouping;
  - UI display of actual AI spend returned by `/apply`;
  - added dependencies `python-multipart`, `openpyxl`, and `pypdf`;
  - added `dev.sh` as a local development launcher only, not for production.

Previous iteration:

**2026-05-12:** Brought GutenDocx documentation up to the current Codex project standard.

Current iteration:

- Added Codex-oriented project memory and startup docs.
- Documented that GutenDocx is a standalone private-client app, not a BuddhistHelp dependency.
- Confirmed production model: Cloudflare Tunnel -> `127.0.0.1:8000`, protected by Cloudflare Access.
- Documented that root runtime is retained for legacy compatibility; do not migrate to a non-root user unless explicitly requested.
- Documented that `/ai/SECURITY` owns server exposure, Cloudflare Access/Tunnel/DNS/WAF, firewall, monitoring, backups, and `/ai/PORTS.yaml`.
- No service, firewall, Cloudflare, database, or application runtime state changes were made during this documentation pass.

## Current State

| Area | Status |
| --- | --- |
| Project | `/ai/gutendocx`, standalone private-client DOCX normalization / PDF export app |
| Primary user model | One client plus developer; public search/SEO is not a goal |
| Public URL | `https://gutendocx.unicloud.ca` |
| Public access | Cloudflare Access protected |
| Public ingress | Cloudflare Tunnel `mainserver` -> `http://localhost:8000` |
| App service | `gutendocx.service` |
| App bind | `127.0.0.1:8000` |
| Runtime user | `root`, retained as an explicit legacy compatibility constraint |
| App auth | No built-in login; relies on Cloudflare Access + localhost bind + host firewall |
| Outputs | `Uploads/` and `output/` may contain client files and generated artifacts |
| Server ops owner | `/ai/SECURITY` |
| Port inventory | `/ai/PORTS.yaml` |
| Git state | Pre-existing uncommitted code/config changes are present; inspect before committing |
| Upload input | Normal multi-file `.docx` picker; do not use `webkitdirectory` for the main "Upload files" button unless adding a separate folder-upload flow |

## Completed Work

### 2026-05-13

1. Fixed the main Web UI upload picker for Windows/browser compatibility by removing folder-picker behavior from the primary file upload control.
2. Added an explicit `.docx` accept filter to the upload input.
3. Kept the server upload endpoint unchanged; it already accepts one or many DOCX files and preserves relative paths when provided.
4. Verified local production service serves the updated static HTML without restart.

### 2026-05-12

1. Created `AGENTS.md` with Codex workflow, safety rules, project/server ownership boundary, and verification commands.
2. Created `.cursor/SESSION_HANDOFF.md` as the concise resume point for Codex/Cursor-style sessions.
3. Added README production operations notes.
4. Created `PROJECT_LOG.md` as the lean project memory entrypoint.
5. Created `Docs/Implementation_Status_2026-05-12.md` as the current implementation snapshot.
6. Created `Docs/Deploy_Runbook.md` with production checks, restart rules, and Cloudflare Access expectations.
7. Created `Docs/README.md` as the active documentation index.
8. Updated `/ai/SECURITY` and `/ai/PORTS.yaml` to record GutenDocx's server-security model.

## Next Tasks

1. **Client Windows retest:** ask the client to hard-refresh (`Ctrl+F5` / `Ctrl+Shift+R`) and confirm `Upload files...` opens a DOCX file picker.
2. **Reconcile uncommitted changes:** inspect existing modified code/config files before any new implementation work or commit.
3. **Service hardening without user migration:** keep root runtime, but later test a systemd drop-in such as `NoNewPrivileges=true`, `PrivateTmp=true`, and constrained write paths.
4. **Data retention:** decide whether to periodically clean old `Uploads/` and `output/` files.
5. **Access verification:** keep Cloudflare Access enabled for `gutendocx.unicloud.ca`; do not convert the app to anonymous public access without explicit approval.
6. **Production docs upkeep:** after non-trivial app or operations changes, update `PROJECT_LOG.md`, `.cursor/SESSION_HANDOFF.md`, `Docs/Implementation_Status_2026-05-12.md`, and `Docs/Deploy_Runbook.md` if affected.

## Useful Verification Commands

```bash
systemctl is-active gutendocx cloudflared server-firewall tailscaled ssh
systemctl status gutendocx --no-pager --lines=80
systemctl cat gutendocx
ss -lntup | rg ':8000'
curl -fsS http://127.0.0.1:8000/health
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://gutendocx.unicloud.ca/
```

Expected:

- `gutendocx` and infrastructure services are active.
- Port `8000` is bound to `127.0.0.1`.
- Local `/health` returns OK.
- Public unauthenticated requests redirect to Cloudflare Access login.
