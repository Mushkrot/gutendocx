# GutenDocx Session Handoff

Last updated: 2026-05-19 UTC

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
- Admin panel: `/admin`, protected by app-level Cloudflare Access email check. Only `highmac@gmail.com` is allowed by default (`GUTENDOCX_ADMIN_EMAILS` can override/extend).
- Server/security ownership: `/ai/SECURITY`.
- App ownership: this repo.
- `config.yaml` is intentionally modified by the platform during normal Web UI use. Treat its diffs as runtime/user state unless the task explicitly concerns config defaults or settings.
- Diagnostic audit events are written to `output/audit_events.jsonl`. They should capture what the user clicked/tried, selected options, uploaded file metadata, endpoint timings, outputs, and errors without storing document contents.

## Recent Audit

2026-05-26 low-risk logging cleanup:

- Created baseline checkpoint commit `c20203e` before changes; `config.yaml` remained runtime/user-editable state and was not staged.
- Added `/favicon.ico` returning HTTP 204 to remove recurring browser 404 noise from audit logs.
- Added Web UI `auditErrorData()` helper so client error events keep bounded `error` text plus structured `error_summary` fields for HTTP status and Cloudflare HTML title/code when present.
- No DOCX pipeline, Apply/job execution, AI cost calculation, model governance, retention cleanup, Cloudflare Access, or bind behavior was changed.
- Verification passed: `./gutenberg/bin/python -m py_compile gutendocx/web/server.py`; extracted Web UI script passed `node --check -`.
- Production was restarted and verified: services active, port `8000` still localhost-bound, local `/health` OK, `/favicon.ico` returns 204, public URL still redirects to Cloudflare Access.

2026-05-26 updated `Para1` manual-line-break alignment:

- Client reported the workflow is working well and requested `Para1=>left`.
- `gutendocx/core/whole.py` now keeps the same deterministic `Para1` rule for non-heading body paragraphs with manual line breaks, but sets both the `Para1` style and matching paragraphs to left alignment.
- `gutendocx/tests/test_para1_manual_breaks.py` now expects left alignment for the targeted paragraph/style and still covers ordinary body paragraphs, built-in headings, and learned heading mappings.
- `config.yaml` remains runtime/user-editable state and was not intentionally changed.
- Verification passed: py_compile for the changed Python files, `./gutenberg/bin/python -m pytest gutendocx/tests/test_para1_manual_breaks.py -q` with 4 tests.
- Production was restarted and verified: services active, port `8000` still localhost-bound, local `/health` OK, public URL still redirects to Cloudflare Access.

2026-05-19 confirmed `Para1` manual-line-break style rule:

- Client requested and then confirmed a new body paragraph style rule:
  - existing behavior: Headings are handled separately; other body paragraphs remain Body Text/Normal;
  - requested behavior: among non-heading paragraphs, detect `^l` / `@L@` line breaks; paragraphs containing that marker/break should get style `Para1`; `Para1` text should be centered; all other non-heading paragraphs should stay `Normal` as now. Superseded on 2026-05-26 by client request `Para1=>left`.
- Analysis result:
  - This is a deterministic DOCX body-formatting change, not an AI/prompt change.
  - Relevant code is in `gutendocx/core/whole.py`:
    - `_apply_body_style_overrides()` currently applies Body formatting to non-heading body paragraphs.
    - `_apply_headings_style_overrides()` matches built-in Heading styles and learned `detected_style_mapping`.
    - `apply_whole_document()` currently runs body overrides, heading overrides, special overrides, then page/section/footer work.
  - Current runtime config may map headings as custom Word styles, for example `Headings: Heading 2`, `Heading2: Heading 3`, `Heading3: Para 08`, with `Body: Normal`. Treat `config.yaml` diffs as runtime state unless the task explicitly requires changing defaults.
- Implemented in `gutendocx/core/whole.py`:
  - `_paragraph_has_manual_line_break()` detects Word manual line breaks (`<w:br>` with no type or `textWrapping`), plus `"\n"`, literal `@L@`, and literal `^l` fallbacks.
  - `_apply_para1_manual_line_break_style()` creates/updates paragraph style `Para1`, centers it, and applies it only to non-heading body paragraphs with manual line breaks. Superseded on 2026-05-26: the rule now left-aligns `Para1`.
  - `apply_whole_document()` now runs this pass after body/headings overrides and includes the result in `whole.para1_manual_breaks`.
  - `Para1` is whitelisted during optional unused-style cleanup.
- Added focused tests in `gutendocx/tests/test_para1_manual_breaks.py` for body-with-break, body-without-break, built-in heading-with-break, and learned-heading-mapping-with-break behavior.
- Added `pytest` to `requirements.txt` and installed it in the project venv.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/whole.py gutendocx/tests/test_para1_manual_breaks.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests/test_para1_manual_breaks.py -q` passed: 4 tests.
- Production service was restarted and verified:
  - `gutendocx.service` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - public URL still redirects to Cloudflare Access login.

2026-05-13 background batch jobs:

- Added `POST /jobs/apply` and `GET /jobs/{job_id}`.
- Batch Apply in the Web UI now starts a background job and polls job status instead of holding a long `/apply` request open through Cloudflare.
- Job state is persisted under `output/jobs/`.
- Duplicate queued/running jobs are reused based on a hash of batch files and Apply options, reducing accidental double processing after visible timeouts.
- Stage A hardening is implemented: job JSON tracks per-file `queued/running/completed/failed`, batch Apply supports partial success, and batch XLSX reports include `Status` and `Error`.
- Stage B cleanup is implemented: `POST /jobs/cleanup` defaults to dry-run and can remove old finished jobs plus related output/upload artifacts under safe directories.
- Stage C controls are implemented: `POST /jobs/{job_id}/cancel`, `POST /jobs/{job_id}/retry_failed`, and basic Web UI Cancel / Retry failed controls.
- Stage D restart recovery is implemented: queued/running persisted jobs are resubmitted at startup; already completed files with existing output are skipped, while unfinished/running files are queued again.
- Admin panel is implemented at `/admin`: AI cost summary/recent usage, storage overview, and dry-run/real cleanup controls. Admin APIs and direct `/static/admin.html` access require `highmac@gmail.com` from Cloudflare Access headers.
- AI model selection is admin-only. The main UI shows a disabled model selector, `/settings/model` exposes the current configured model, and Apply/Analyze/job APIs force user-supplied `model` to `config.yaml`'s `cover.vision.model`.
- Body-only batch Apply no longer spends AI tokens on cover dry-run solely for XLSX report metadata. Cover metadata can be blank when `apply_cover=false`; DOCX/PDF output is unchanged.
- Scheduled cleanup is enabled by default and removes uploaded/generated files older than 15 days, excluding audit/cost logs and active job state.
- Legacy `/batch/status/{batch_id}` remains available as a fallback/recovery endpoint.

2026-05-13 OpenAI prompting/AI usage analysis:

- Saved official OpenAI prompt/model guide snapshots under `Docs/OpenAI_Guides/`.
- Added `Docs/AI_Prompting_and_Usage_Analysis_2026-05-13.md` with current AI usage map, prompt/model notes, Cloudflare timeout explanation, and AI optimization candidates.
- Added a risky-change QA rule to `AGENTS.md`: commit current state first, define before/after tests, record baseline, make the smallest change, rerun the same tests, compare results, and keep only changes with clear benefit/no regression.
- Do not change production prompts/model defaults without first discussing the proposal and QA plan with the user.

2026-05-13 AI model/pricing refresh:

- Added `gpt-5.4-nano` to the Web UI model selector and backend cost accounting table.
- Refreshed UI/backend token prices against current OpenAI API docs.
- Removed the unverified `gpt-5.1-mini` option from the UI/backend pricing table; current official API docs list `gpt-5-mini`, `gpt-5.4-mini`, and `gpt-5.4-nano`, but not a general `gpt-5.1-mini` API model.
- Default remains `gpt-4o-mini` until quality/cost benchmarking proves a better replacement for GutenDocx.

2026-05-13 Windows upload compatibility fix:

- Client reported that on Windows, after pressing "Upload files", files were not visible/selectable.
- Main cause found in Web UI: hidden upload input used `webkitdirectory`, which opens folder-selection behavior instead of a normal file picker in Windows browser UX.
- Updated `gutendocx/web/static/index.html` so the primary upload control is a normal multi-file `.docx` picker with an explicit DOCX `accept` filter.
- Restored user-facing handling for empty/non-DOCX selections.
- Verified the running app serves the updated static HTML from disk via `http://127.0.0.1:8000/`; no service restart or Docker rebuild was needed.
- Ask the client to hard-refresh on Windows (`Ctrl+F5` or `Ctrl+Shift+R`) before retesting.

2026-05-13 full pending-change commit:

- Remaining pending app changes were committed after the upload fix.
- Includes AI usage/cost accounting, `gpt-5-mini` cover vision default, batch `/apply` processing, XLSX batch report generation, PDF page counting with `pypdf`, cover detection improvements, UI display of actual AI spend, and dependency updates.
- `dev.sh` is now tracked as a development helper; do not use it as production launcher because it binds `0.0.0.0` with reload.
- Production service was not restarted as part of this commit.

2026-05-13 config state clarification:

- User clarified that `config.yaml` is expected to be edited by the platform during normal operation.
- Do not treat incidental `config.yaml` diffs as an error.
- Do not commit or revert `config.yaml` automatically; inspect whether the change belongs to the requested task.

2026-05-13 diagnostic audit logging:

- Added structured server and client audit events for uploads, analyze, apply, TOC apply, learn cover/body, reset, download, HTTP timings, and errors.
- Main log file: `output/audit_events.jsonl`.
- Purpose: diagnose client reports without needing the client to reconstruct every click/checkbox/file choice manually.
- Privacy rule: log metadata and options only; do not log DOCX text/content or credential headers.

2026-05-13 client-test repairs:

- Fixed heading override flow: nested UI heading controls are normalized server-side, learned `detected_style_mapping` is saved, and whole-document apply uses mapped styles such as `Para 08` instead of only built-in `Heading*` styles.
- Added `GET /batch/status/{batch_id}` plus UI polling after `HTTP 524`, so large batch results can be recovered when Cloudflare times out while the server continues processing.
- Verified `/batch/status/batch_1778675324` returns ready/download metadata for the client's 6-file batch that produced a 524 screenshot.

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
2. Plan an AI model/pricing refresh: review newer models up to ChatGPT 5.5, update model choices/pricing, and benchmark the best model for this workflow.
3. Plan an admin AI cost dashboard based on the user's existing dashboard from another project.
4. Evaluate a possible UI redesign using the user's existing design from another project.
5. Design admin/user roles with different permissions and dashboards before implementing built-in auth.
6. Keep Cloudflare Access enabled for `gutendocx.unicloud.ca`.
7. Add server-side hardening around the existing root runtime without changing users first:
   - consider a systemd drop-in with `NoNewPrivileges=true`, `PrivateTmp=true`, and narrowly scoped write paths after testing in a maintenance window.
   - do not change this casually because the app uses LibreOffice/Docker and writes to project directories.
8. Add a cleanup/retention policy for `Uploads/` and `output/` if client files should not stay on disk indefinitely.

## Future Roadmap Notes

- AI model refresh should include newly available OpenAI/ChatGPT models up to ChatGPT 5.5, UI model-list updates, current token pricing, and workflow-specific testing to select an optimal model.
- Future model testing should include Google `gemini-2.5-flash-lite` as a candidate for cover/body vision classification. Do not implement it yet; first design provider abstraction and run A/B tests against `gpt-4o-mini`.
- Admin dashboard work should reuse principles from the user's existing AI cost dashboard in another project.
- UI redesign work should review the user's existing alternate design from another project before changing GutenDocx.
- Built-in users/roles would be a security model change from the current Cloudflare Access-only approach.

## Known Commands

```bash
systemctl status gutendocx --no-pager --lines=80
systemctl cat gutendocx
ss -lntup | rg ':8000'
curl -fsS http://127.0.0.1:8000/health
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://gutendocx.unicloud.ca/
```
