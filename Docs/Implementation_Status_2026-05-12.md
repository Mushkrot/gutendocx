# GutenDocx - Implementation Status

**Last updated:** 2026-07-08
**Project path:** `/ai/gutendocx`
**Production URL:** `https://gutendocx.unicloud.ca`

## Summary

GutenDocx is a private-client DOCX normalization and PDF export application. It processes Microsoft Word manuscripts, applies layout/style normalization, updates table-of-contents fields through LibreOffice/PyUNO, and exposes a simple FastAPI-backed web UI.

This project is not a public discovery/SEO site. It is intended for one client plus the developer and is protected by Cloudflare Access.

## Architecture

- Backend: FastAPI in `gutendocx/web/server.py`.
- Frontend: static single-page HTML/JS in `gutendocx/web/static/index.html`.
- Core pipeline: `gutendocx/core/`.
- Config: `config.yaml`, merged with embedded defaults under `gutendocx/configs/default_config.yaml`.
- Runtime config state: `config.yaml` is intentionally edited by the platform during normal Web UI use. Its local diffs may represent current user settings, not developer code changes.
- LibreOffice integration: Docker/PyUNO through `gutendocx/core/libreoffice_toc.py` and `gutendocx/scripts/lo_convert.py`.
- Custom LibreOffice image: `gutendocx/libreoffice:latest`.
- Fonts: local `fonts/` directory, not intended to be tracked in git.
- Runtime output:
  - `Uploads/` for uploaded DOCX files.
  - `output/` for generated DOCX/PDF/ZIP/report/vision artifacts.
  - `output/jobs/` for persisted background job state.
  - `output/audit_events.jsonl` for structured diagnostic audit events.
  - `output/ai_costs.jsonl` for best-effort estimated AI token/cost events.
- Upload UX: the primary "Upload files" control is a normal multi-file `.docx` picker. Do not attach `webkitdirectory` to that control unless adding a separate, explicitly labeled folder-upload feature.
- Word mark cleanup: the main UI has an optional `Clean parasite Word marks` body setting for `^p` / `^l` patterns. It is disabled by default and only cleans eligible blank/manual-line-break-only body gaps before style normalization.
- Body style UI payloads are partial, but the backend preserves the saved Body `size_pt` when the UI sends another Body control without an explicit size. This keeps the common 18pt -> 12pt body pass from being silently dropped while avoiding unrelated defaults such as line spacing.
- Cover style overrides clear direct run formatting for Title, Subtitle, and Author so configured cover role styles are not overridden by source `24pt`/bold run properties.
- Page-number footer styling is re-applied to final DOCX files after LibreOffice round-trip so PAGE fields retain configured font/size/bold/italic values in downloaded DOCX outputs.

## Production Baseline

- Public URL: `https://gutendocx.unicloud.ca`.
- Access control: Cloudflare Access.
- Cloudflare Tunnel: `mainserver`.
- Local target: `http://localhost:8000`.
- systemd service: `gutendocx.service`.
- ExecStart: `/ai/gutendocx/gutenberg/bin/uvicorn gutendocx.web.server:app --host 127.0.0.1 --port 8000`.
- Runtime user: `root`.
- Runtime root decision: accepted for now as a legacy compatibility constraint. Do not migrate to a non-root user without an explicit owner-approved project.
- Server operations owner: `/ai/SECURITY`.
- Server port inventory: `/ai/PORTS.yaml`.

## Security Model

- The app has no built-in login.
- The effective access boundary is:
  - Cloudflare Access at `gutendocx.unicloud.ca`;
  - local bind to `127.0.0.1:8000`;
  - host firewall default-DROP policy;
  - Cloudflare Tunnel as the public ingress path.
- Admin access is additionally enforced inside the app for `/admin` and `/admin/api/*` by checking Cloudflare Access email headers. The default allowed admin email is `highmac@gmail.com` (`GUTENDOCX_ADMIN_EMAILS` can configure the list).
- AI model selection is an admin-only operational setting. Regular users cannot change the model in the main UI, and backend Apply/Analyze/job endpoints force any submitted model value to the configured `cover.vision.model`.
- `/output` is statically mounted by the app. This is acceptable only because Cloudflare Access protects the hostname. Treat generated files as sensitive.
- `Uploads/` and `output/` can contain client manuscripts and generated files. Do not print, commit, or casually summarize their contents.
- `output/audit_events.jsonl` should log user-action metadata, selected options, file names/sizes, timings, outputs, and errors, but not document text/content or credential headers.
- Admin observability is metadata-only: `/admin/api/summary` aggregates persisted jobs, audit events, AI cost events, download confirmations, throughput, slowest jobs, and audit warnings without reading document contents.
- Word mark cleanup audit metadata records counts only: enabled state, pattern count, gaps modified, paragraphs removed, and manual line breaks removed.
- `dev.sh` is development-only because it uses `--reload --host 0.0.0.0`.

## Current Documentation

- `PROJECT_LOG.md`: lean resume state for Codex.
- `AGENTS.md`: agent workflow and safety rules.
- `.cursor/SESSION_HANDOFF.md`: concise current handoff.
- `Docs/Deploy_Runbook.md`: production checks and operational procedures.
- `Docs/README.md`: active documentation index.
- Historical/deeper design docs:
  - `Docs/Project_overview.md`
  - `Docs/PRD.md`
  - `Docs/Integration_report 01.md`
  - `Docs/Integration_report 02.md`
  - `Docs/todo.md`

## Known Current Issues / Risks

1. Runtime is root. This is accepted for now, but systemd hardening should be tested later without changing the runtime user first.
2. Uploaded/generated files are cleaned after 15 days by scheduled retention cleanup. Audit/cost logs remain sensitive operational metadata and are not part of file retention cleanup.
3. Request path/config handling assumes trusted users behind Cloudflare Access. Do not remove Access without first hardening app-level auth and path validation.
4. Built-in users/roles are a future roadmap item and would change the current Cloudflare Access-only app security model.
5. `config.yaml` changes during normal use. Do not automatically commit or revert it without confirming the diff belongs to the requested work.
6. Local docs are older and some historical files describe superseded LibreOffice macro approaches. Prefer `Docs/Integration_report 02.md` for the current LibreOffice/PyUNO architecture.

## Future Roadmap

These items are captured for future planning and should not be implemented without a separate explicit request:

1. Review newly available OpenAI/ChatGPT models up to ChatGPT 5.5, add suitable options to the UI, update token pricing, and test/benchmark which model is optimal for GutenDocx. Include Google `gemini-2.5-flash-lite` as a future benchmark candidate for vision/classification, but do not implement Gemini support before provider-abstraction design and A/B quality tests.
2. Build an administrative AI cost dashboard by reviewing the user's existing dashboard from another project and adapting the useful principles to GutenDocx.
3. Evaluate a possible full UI redesign based on another existing project design the user will provide.
4. Add users and roles: admin and normal user permissions, separate dashboards, and the required app-auth/security model around them.

## Recent Changes

- **2026-07-08:** Fixed a narrow Body style payload issue found from the client's July 1 follow-up. The first affected batch had sent only `styles.body.align=justify`, so the backend replaced the saved Body override with alignment only and never received `size_pt: 12`; later successful runs also changed cleanup patterns and disabled Normalize, making the checkbox look suspicious. A local matrix on `pg2095.docx` showed `Normalize body paragraph styles` does not block `size_pt: 12` when the size is present. `_merge_ui_style_overrides()` and the whole/apply endpoint path now preserve the saved Body `size_pt` when the UI submits a partial Body override without size, but do not pull in unrelated defaults such as line spacing. TOC, `Para1`, body-style normalization internals, and trailing-break body-boundary logic were not changed. Added `gutendocx/tests/test_ui_style_overrides.py`; full pytest passed with 45 tests, server syntax compiled, extracted UI JS syntax passed, `git diff --check` passed, and a real-file sanity check on a `/tmp` copy of the July 1 second-pass `pg2095.docx` showed the old-style `{"body": {"align": "justify"}}` payload now applies both `size_pt: 12.0` and `alignment: justify`. Production was restarted after confirming no active jobs; services stayed active, port `8000` stayed bound to `127.0.0.1`, local `/health` was OK, the public URL redirected to Cloudflare Access, and a live localhost `/whole/apply` on a synthetic `/tmp` DOCX plus temp config returned 200 with `body_changes {'size_pt': 12.0, 'alignment': 'justify'}`.
- **2026-06-27:** Fixed the `pg1868.docx` edge case where a single explicit page/section break in the final paragraph was incorrectly treated as the body boundary. `_compute_body_start_index()` now ignores one final trailing explicit break, while one non-final break and normal two-break cover/blank/body documents preserve their previous behavior. TOC, heading, detected-heading, field, protected-style, and `Para1` exclusions were not loosened. Real-file QA showed the boundary fix made existing `style_overrides.Body.line_spacing: 1.08` active on this recovered body and increased LibreOffice output from 64 to 66 pages, so direct `Body.line_spacing` is skipped only when body starts at `0` because one final explicit break was ignored; other Body overrides still apply. QA on `/tmp` copies showed `pg1868` body analysis at `body_start_index=0` with `528` body paragraphs, `Para1` on `26` manual-line-break paragraphs, TOC SDT field/instruction structure preserved, and PDF page count `64 -> 64`. Regression checks for `pg60112`/`pg60115` still clear eligible `keepNext` to `0` with heading counts preserved, and `pg61492`/`pg61506` structural TOC/table/hyperlink checks remain present. Full pytest passed with 42 tests, Python syntax compiled, and `git diff --check` passed. Commit `20e623d` was pushed, production was restarted, services stayed active, port `8000` stayed bound to `127.0.0.1`, local `/health` was OK, and the public URL still redirects to Cloudflare Access. Live `/apply` on a `/tmp` copy of `pg1868.docx` returned 200, created DOCX/PDF/ZIP, kept final PDF page count at 64, and final DOCX structural checks showed real manual-line-break body paragraphs are `Para1`; runtime `config.yaml` remains user/platform state.
- **2026-06-17:** Added safe body paragraph style normalization for source documents with bad paragraph-style pagination flags. Ordinary post-cover body paragraphs are now moved to a controlled safe body style (`GD Body` when configured Body is `Normal`/`Обычный`) and both the safe style and normalized paragraphs set `keep_with_next=False`, while global Word `Normal` is not modified. The pass excludes headings, detected heading mappings, `Para1`, TOC, field paragraphs, cover/header/footer styles, table geometry, hyperlink relationships, spacing/alignment/indents/numbering. A UI/config toggle `body_style_normalization.enabled` is available as `Normalize body paragraph styles` under `Whole document -> Text styles -> Body Text`; the normal client workflow is unchanged because the setting is enabled by default, and the checkbox is mainly a fallback/off-switch for rare files where original body paragraph styles should be preserved. QA on client examples showed `pg60112` eligible `keepNext` `1 -> 0` and `pg60115` `758 -> 0`; heading counts stayed stable, `Para1` still applies for manual-line-break paragraphs, previous `pg61492`/`pg61506` table/link regressions remained at bad count `0`, and Docker/LibreOffice smoke produced DOCX/PDF for both new files with post-LO eligible `keepNext` still `0`. Full pytest passed with 36 tests, changed Python files compiled, extracted Web UI JS passed `node --check -`, and `git diff --check` passed. Production was restarted and verified with services active, localhost bind, local health, Cloudflare Access redirect, and live `/apply` on both `pg60112.docx` and `pg60115.docx` creating DOCX/PDF/ZIP with final eligible `keepNext` `0`. Runtime `config.yaml` remains user/platform state.
- **2026-06-13:** Added cautious table, hyperlink, and TOC style repair for client examples `pg61492.docx` and `pg61506.docx`. Body font-level overrides now also apply to table-cell text and visible `w:hyperlink` runs while preserving table geometry, hyperlink relationships, and field instructions; final DOCX files also get a post-LibreOffice table/hyperlink repair pass because LibreOffice can strip some run font attributes. TOC styling now supports `Same as Body`, `Same as Heading`, and `Custom` in the Web UI via `style_overrides.TOC`; existing TOC blocks are preserved rather than deleted/reinserted, and TOC styles/result-runs are repaired before/after LibreOffice, including nested `w:sdt/w:sdtContent` TOC blocks. Baseline QA on the examples with target Body `Aptos 10` and TOC `Georgia 9` showed `pg61492` table `164/164` bad, hyperlink `41/41` bad, TOC `52/52` bad, and `pg61506` hyperlink `40/40` bad, TOC `46/46` bad. After core repair, table/hyperlink bad counts reached `0`; existing-source TOC repair reduced TOC bad counts to `0` while preserving field instructions. Full pytest passed with 30 tests and extracted Web UI JS passed `node --check -`. Production endpoint QA after restart passed on both attached files: live `/apply` created DOCX/PDF/ZIP, `pg61492` table/hyperlink/TOC bad counts were `0`, and `pg61506` hyperlink/TOC bad counts were `0`.
- **2026-06-12:** Fixed cover role and page-number style override regressions reported from 2026-06-09 client jobs. Baseline QA on saved outputs showed `Cover Author` direct `24pt`/bold formatting in `pg1125`, `pg1128`, and `pg1133`-`pg1137`, plus missing PAGE-field style properties in all 26 final DOCX files from batches `batch_1780990060`, `batch_1780996526`, and `batch_1780996834`. Cover role application now clears direct run formatting for Title/Subtitle/Author, PAGE fields are created with styled result runs, final DOCX footer PAGE fields are repaired after LibreOffice, and the UI sends explicit unchecked Page Number bold/italic values. After-QA on the same real files returned deterministic cover bad count `0` and footer repair bad count `0 OF 26`; full pytest passed with 25 tests, Python syntax checks passed, and extracted Web UI JS passed `node --check -`. Production was not restarted as part of this work.
- **2026-06-07:** Tightened logging signal and admin operations metrics without changing file processing. Polling noise is reduced by logging only first/state-change/sample `job.checked` and `client.apply_job_polled` events, `/admin/api/summary` now reports download confirmations, average batch duration, average seconds per file, slowest jobs, and cover+vision-without-AI-cost warnings, and `/admin` displays the new metrics/panels. Full pytest, Python syntax, admin JS syntax, live-log summary timing checks passed; production was restarted and verified with localhost binding, local health, admin summary, and Cloudflare Access redirect preserved.
- **2026-06-07:** Extended parasite Word-mark cleanup with a read-only advisor and apply report UX. The UI now keeps the manual `Clean parasite Word marks` textarea and adds `Analyze cleanup` plus `Apply recommended cleanup`; the advisor inspects body blank gaps structurally, recommends high-confidence `^p` / `^l` patterns without sending document text to an external AI service, and fills the editable textarea. The patterns field now labels whether values came from saved config, latest analysis, or manual edits, and the analysis report has a fixed max height with internal scrolling. Successful Apply now shows a short cleanup popup for both manual and recommended runs with patterns used, gaps cleaned, empty paragraphs removed, and manual line breaks removed. Full pytest, Python syntax, UI script syntax, production restart, localhost bind, local health, advisor endpoint, and Cloudflare Access redirect checks passed.
- **2026-06-07:** Added managed parasite Word-mark cleanup for body processing. The UI now exposes `Clean parasite Word marks` under `Whole document -> Text styles`, accepts `^p` / `^l` patterns, and stores them under `word_cleanup` with fixed replacement `^p`. The cleanup pass runs before body/headings/`Para1` style passes, removes only eligible blank/manual-line-break-only body gaps, skips headings/TOC/protected/page-break/section-break/field/object paragraphs, and returns count-only metadata in `whole.word_cleanup` and audit summaries. Full pytest and UI script syntax checks passed; production was restarted and verified with localhost binding, local health, new UI/config availability, and Cloudflare Access redirect preserved.
- **2026-05-26:** Improved logging analytics and admin observability without changing file processing. `/admin/api/summary` now includes read-only `activity` data from existing job/audit/cost metadata, `/admin` shows activity cards plus Recent Jobs, Recent Errors, and Audit Health, new audit events carry schema/source/operation/actor metadata, and new AI cost rows include better job/batch/input context where available. Added focused tests and restarted production after QA; localhost binding, local health, admin summary, and Cloudflare Access redirect were verified.
- **2026-05-26:** Added low-risk observability cleanup: `/favicon.ico` now returns HTTP 204 to reduce audit-log 404 noise, and Web UI client error audit events include bounded error text plus structured `error_summary` fields for easier analysis of HTTP/Cloudflare failures. No document-processing behavior, model governance, retention cleanup, or production exposure was changed; production was restarted and verified with localhost binding, local health, favicon 204, and Cloudflare Access redirect preserved.
- **2026-05-26:** Updated the deterministic body-formatting rule for manual line breaks per client request `Para1=>left`: non-heading body paragraphs containing a Word manual line break still get paragraph style `Para1`, while `Para1` and matching paragraphs are now left-aligned. Focused pytest coverage was updated to preserve heading and learned-heading exclusions; production was restarted and verified with localhost binding, local health, and Cloudflare Access redirect preserved.
- **2026-05-19:** Implemented the confirmed deterministic body-formatting rule for manual line breaks: non-heading body paragraphs containing a Word manual line break (`^l` / `@L@` notation) now get centered paragraph style `Para1`, while headings, TOC/protected styles, and ordinary body paragraphs are left in their existing style behavior. Added focused pytest coverage for the new rule; restarted production after confirming the service remained localhost-bound and verified local health plus the Cloudflare Access redirect.
- **2026-05-13:** Saved official OpenAI prompt/model guide snapshots under `Docs/OpenAI_Guides/`, added `Docs/AI_Prompting_and_Usage_Analysis_2026-05-13.md`, and documented a cautious before/after QA rule for risky prompt/model/pipeline changes.
- **2026-05-13:** Added background Apply jobs for batch processing with persisted job state, duplicate running-job reuse, `/jobs/apply`, `/jobs/{job_id}`, and Web UI polling to avoid Cloudflare `HTTP 524` as the normal batch path.
- **2026-05-13:** Hardened background jobs with per-file progress/status, partial-success batch handling, and `Status`/`Error` columns in the XLSX batch report.
- **2026-05-13:** Added dry-run-first job cleanup endpoint for old finished jobs and related output/upload artifacts.
- **2026-05-13:** Added cooperative job cancellation and retry-failed-files flow with basic Web UI controls.
- **2026-05-13:** Added best-effort restart recovery for background jobs: queued/running jobs are resubmitted after service startup and completed files with existing output are not reprocessed.
- **2026-05-13:** Added Cloudflare-email-gated admin panel at `/admin` for AI cost visibility and file cleanup controls, limited by default to `highmac@gmail.com`.
- **2026-05-13:** Made AI model selection admin-only and backend-enforced so regular users cannot accidentally switch to a more expensive model for large batches.
- **2026-05-13:** Avoided unnecessary AI spending in body-only batch Apply by skipping cover dry-run used only for XLSX report metadata when cover scope is off.
- **2026-05-13:** Added scheduled retention cleanup for uploaded/generated files older than 15 days while preserving audit/cost logs and active job state.
- **2026-05-13:** Refreshed OpenAI model pricing in the Web UI and backend cost accounting tables, added `gpt-5.4-nano` as a selectable model, and removed the unverified `gpt-5.1-mini` UI option.
- **2026-05-13:** Fixed Windows upload picker compatibility by changing the primary Web UI upload control to normal multi-file `.docx` selection with an explicit accept filter. Verified the running service serves the updated static HTML without restart.
- **2026-05-13:** Committed pending app changes for AI usage/cost reporting, `gpt-5-mini` cover vision default, batch `/apply` processing, XLSX report output, PDF page counting, and cover detection improvements. Added `python-multipart`, `openpyxl`, and `pypdf` dependencies.
- **2026-05-13:** Added structured audit logging for server/API events and client UI actions to support self-contained diagnostics of client reports.
- **2026-05-13:** Fixed heading-style application for nested UI heading overrides and learned custom Word style mappings; added batch status polling/recovery for Cloudflare `HTTP 524` timeouts.
- **2026-05-12:** Added current Codex project-memory structure: `PROJECT_LOG.md`, `AGENTS.md`, `.cursor/SESSION_HANDOFF.md`, `Docs/Implementation_Status_2026-05-12.md`, `Docs/Deploy_Runbook.md`, and `Docs/README.md`.
- **2026-05-12:** Read-only server-security audit confirmed `gutendocx.service` is active, bound to `127.0.0.1:8000`, and protected externally by Cloudflare Access.
- **2026-05-12:** `/ai/SECURITY` and `/ai/PORTS.yaml` were updated to include GutenDocx's Cloudflare Access/private-client/root-runtime context.

## Verification Snapshot

Read-only checks performed on 2026-05-12:

- `gutendocx`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` were active.
- `ss -lntup` showed `127.0.0.1:8000`.
- Local `/health`, `/config`, `/files/simples`, `/fonts/list`, and `/openapi.json` returned OK.
- Public unauthenticated requests to `https://gutendocx.unicloud.ca/` and app/API/output paths redirected to Cloudflare Access login.
