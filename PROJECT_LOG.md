# GutenDocx - Project Log

**Cold start (new Codex chat, no history):** Read `PROJECT_LOG.md` -> `AGENTS.md` -> `.cursor/SESSION_HANDOFF.md` -> `Docs/Implementation_Status_2026-05-12.md` -> `Docs/Deploy_Runbook.md` -> `Docs/README.md`.

**Token discipline:** Read only through **Current Session**, **Current State**, and **Next Tasks** first. Open deeper historical docs only when needed.

---

## Current Session - Resume Point

**2026-05-13:** Fixed Windows upload picker compatibility.

Current iteration:

- Added a background job system for batch Apply:
  - `POST /jobs/apply` creates or reuses a queued/running job for the same batch/options signature.
  - `GET /jobs/{job_id}` returns persisted status, progress estimate, result/download metadata, or failure details.
  - Job state is stored under `output/jobs/`.
  - The Web UI uses jobs for batch Apply, avoiding long browser/Cloudflare `/apply` requests as the normal path.
- Stage A job hardening: added exact per-file `queued/running/completed/failed` records, audit events for file start/completion/failure, partial-success batch behavior, and `Status`/`Error` columns in XLSX batch reports.
- Stage B cleanup: added `POST /jobs/cleanup` with dry-run default for old finished jobs and related output/upload artifacts.
- Stage C controls: added cooperative job cancel, retry-failed-files job creation, and basic UI controls for Cancel / Retry failed.
- Stage D restart recovery: queued/running jobs are requeued after service startup; completed files with existing output are skipped instead of reprocessed, and unfinished/running files resume from the next needed file.
- Saved official OpenAI prompt/model guide snapshots under `Docs/OpenAI_Guides/`.
- Added `Docs/AI_Prompting_and_Usage_Analysis_2026-05-13.md` covering current AI usage, prompt/model considerations, Cloudflare timeout architecture, and the required cautious QA rule for risky prompt/model/pipeline changes.
- Added the risky-change QA rule to `AGENTS.md`: commit baseline first, define before/after tests, compare results, and discuss prompt/model changes before implementation.
- Added `gpt-5.4-nano` to the Web UI model selector and backend AI cost table.
- Refreshed the duplicated UI/backend model pricing table against OpenAI API docs as of 2026-05-13.
- Removed the unverified `gpt-5.1-mini` UI/backend pricing entry; current official API docs list `gpt-5-mini`, `gpt-5.4-mini`, and `gpt-5.4-nano`, but not a general `gpt-5.1-mini` model.
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
| Git state | Clean after 2026-05-13 full commit/push except `config.yaml` may change during normal platform use |
| Upload input | Normal multi-file `.docx` picker; do not use `webkitdirectory` for the main "Upload files" button unless adding a separate folder-upload flow |
| Runtime config | `config.yaml` is user/runtime-editable; do not treat incidental diffs as code changes or revert automatically |
| Audit log | `output/audit_events.jsonl` records user actions, selected options, file names/sizes, endpoint timings, outputs, and errors for diagnostics; do not log document contents |

## Completed Work

### 2026-05-13

1. Fixed the main Web UI upload picker for Windows/browser compatibility by removing folder-picker behavior from the primary file upload control.
2. Added an explicit `.docx` accept filter to the upload input.
3. Kept the server upload endpoint unchanged; it already accepts one or many DOCX files and preserves relative paths when provided.
4. Verified local production service serves the updated static HTML without restart.
5. Added structured audit logging for diagnostics:
   - server-side request/action events in `output/audit_events.jsonl`;
   - UI events for upload selection, Apply, TOC, Learn, Reset, Download, success and error paths;
   - endpoint duration, selected options, batch/file metadata, output/download metadata, and error details.
   - logs intentionally avoid document text/content and credential headers.
6. Fixed heading-style application bugs found from the client's test files:
   - backend now understands UI heading overrides shaped as `heading1` / `heading2` / `heading3` / `heading4`;
   - `Learn Body Styles` now persists detected Word style mappings, including custom styles such as `Para 08`;
   - whole-document apply uses detected heading mappings and no longer treats mapped heading styles as Body.
7. Added batch timeout recovery:
   - `GET /batch/status/{batch_id}` reports whether a generated ZIP is ready;
   - UI polls this endpoint after `HTTP 524` on batch Apply and can recover/show the download when the server finishes after Cloudflare times out.
8. Updated the Headings UI so Heading 1, Heading 2, and Heading 3 controls are visible by default; Heading 4 remains dynamic when detected.

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
2. **AI model refresh:** review newly available OpenAI/ChatGPT models up to ChatGPT 5.5, update selectable model list, update token pricing, benchmark quality/cost/latency, and decide whether to replace the current default/optimal model choice.
3. **AI cost admin dashboard:** review the existing dashboard from another project, extract its principles/design, and adapt it to GutenDocx for AI request cost visibility.
4. **Potential UI redesign:** evaluate the alternative UI design from another project and decide whether to migrate GutenDocx to that design.
5. **Users and permissions:** introduce admin/user roles with separate permissions and dashboards; this would change the current security model and must be designed before implementation.
6. **Service hardening without user migration:** keep root runtime, but later test a systemd drop-in such as `NoNewPrivileges=true`, `PrivateTmp=true`, and constrained write paths.
7. **Data retention:** decide whether to periodically clean old `Uploads/` and `output/` files.
8. **Access verification:** keep Cloudflare Access enabled for `gutendocx.unicloud.ca`; do not convert the app to anonymous public access without explicit approval.
9. **Production docs upkeep:** after non-trivial app or operations changes, update `PROJECT_LOG.md`, `.cursor/SESSION_HANDOFF.md`, `Docs/Implementation_Status_2026-05-12.md`, and `Docs/Deploy_Runbook.md` if affected.

## Future Roadmap Ideas

These are future planning items, not permission to implement without a separate request:

1. **OpenAI/ChatGPT model and pricing refresh**
   - Check all relevant models released since this platform was first built, including models up to ChatGPT 5.5.
   - Add appropriate models to the UI selectable model list.
   - Update per-token pricing used for AI cost calculations.
   - Benchmark candidate models for this workflow and compare quality, cost, speed, reliability, and JSON/schema compliance.
   - Re-evaluate the current "optimal" model choice; GPT-4o Mini was previously treated as the cost-effective baseline, but the best choice may have changed.
2. **Administrative AI cost dashboard**
   - User has an existing dashboard from another project.
   - Review that implementation, extract useful principles, and port the appropriate approach to GutenDocx.
   - Dashboard should expose AI request cost, model usage, token totals, and useful operational summaries.
3. **Possible UI redesign**
   - User has an alternative design from another project.
   - Review it and assess whether GutenDocx should migrate to a substantially different interface.
4. **User accounts and permissions**
   - Add admin and normal user concepts.
   - Provide different permissions and dashboards per role.
   - This changes the current "Cloudflare Access only, no built-in login" model, so it requires explicit security/product design before implementation.

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
