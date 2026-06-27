# GutenDocx - Project Log

**Cold start (new Codex chat, no history):** Read `PROJECT_LOG.md` -> `AGENTS.md` -> `.cursor/SESSION_HANDOFF.md` -> `Docs/Implementation_Status_2026-05-12.md` -> `Docs/Deploy_Runbook.md` -> `Docs/README.md`.

**Token discipline:** Read only through **Current Session**, **Current State**, and **Next Tasks** first. Open deeper historical docs only when needed.

---

## Current Session - Resume Point

**2026-06-27:** Fixed `pg1868.docx` single trailing-break body boundary.

Current iteration:

- Investigated the client "stubborn file" `pg1868.docx`.
  - The file has one explicit page/section break at the final paragraph.
  - Before the fix, `_compute_body_start_index()` treated that final marker as a cover/body boundary and returned the end of the document, so body analysis showed zero body paragraphs and no body styles.
  - Treating that lone final break as trailing noise makes the body visible from paragraph `0`, which allows body style detection and `Para1` for manual-line-break paragraphs.
- Implemented cautious recovery:
  - `_compute_body_start_index()` now ignores a single final explicit break as the body boundary;
  - one-break documents with content after the break still start body after that break;
  - two-break cover/blank/body documents still start body after the second break;
  - TOC, heading, detected heading, field, protected-style, and `Para1` exclusion logic was not loosened.
- Page-count guard:
  - real-file QA showed that the boundary fix made existing `style_overrides.Body.line_spacing: 1.08` effective on `pg1868`, increasing LibreOffice output from `64` to `66` pages;
  - the fix therefore skips only direct `Body.line_spacing` when body starts at `0` specifically because one final explicit break was ignored;
  - other Body overrides such as font, size, bold/italic, and justify alignment remain active.
- QA:
  - `pg1868` analyze now reports `body_start_index=0` and `528` body paragraphs;
  - local apply produced `Para1` on `26` manual-line-break paragraphs;
  - existing TOC SDT stayed present with field/instruction structure preserved;
  - local LibreOffice PDF page count stayed `64 -> 64` after the line-spacing guard;
  - real regression checks kept `pg60112` and `pg60115` eligible `keepNext` at `0` after processing and preserved expected heading counts;
  - `pg61492`/`pg61506` table/hyperlink/TOC structural checks remained present.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/whole.py` passed;
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed with `42` tests;
  - `git diff --check` passed.
- No production service restart, live `/apply`, localhost HTTP check, public URL check, Cloudflare change, or systemd action was performed.
- Runtime `config.yaml` remains user/platform state and was not intentionally edited or staged.

**2026-06-17:** Added safe body paragraph style normalization for bad source styles.

Current iteration:

- Investigated client examples `pg60112.docx` and `pg60115.docx`.
  - The reported breakage comes from source paragraph styles carrying page-position flags, especially Word `keep with next` / `не отрывать от следующего`.
  - `pg60115.docx` has `Normal` with style-level `keepNext=True`, affecting 758 eligible body paragraphs.
  - `pg60112.docx` has one eligible body paragraph with effective `keepNext=True`; most body text is on source `Para 01` / `Para 02` / `Para 14` style variants.
- Implemented cautious normalization:
  - ordinary body paragraphs after the cover are assigned to a safe body style (`GD Body` when configured body style is `Normal`/`Обычный`);
  - the global Word `Normal` style is not modified;
  - the safe body style and normalized paragraphs get `keep_with_next=False`;
  - headings, detected heading mappings, `Para1`, TOC, field paragraphs, cover/header/footer styles, table geometry, hyperlink relationships, spacing/alignment/indents/numbering are not intentionally changed.
- Added `body_style_normalization.enabled` with a Web UI toggle under `Whole document -> Text styles -> Body Text` (`Normalize body paragraph styles`) so the operator can disable the repair for a pathological source file.
- Client-facing workflow note:
  - the usual `Apply Styles` workflow is unchanged; the normalization is enabled by default;
  - the new checkbox is mainly a safety off-switch if a rare source file should keep its original body paragraph styles.
- QA:
  - baseline -> after on real files: `pg60112` eligible `keepNext` `1 -> 0`; `pg60115` eligible `keepNext` `758 -> 0`;
  - heading counts stayed stable (`pg60112` `Heading 2: 6`, `pg60115` `Heading 2: 11`);
  - `Para1` exception still applies, with style id `Para1` displayed by Word as `Para 1` on affected manual-line-break paragraphs;
  - previous regression samples stayed green: `pg61492` table bad `0/164`, non-TOC hyperlink bad `0/41`; `pg61506` non-TOC hyperlink bad `0/40`;
  - Docker/LibreOffice smoke produced DOCX/PDF for `pg60112` and `pg60115`, and post-LO eligible `keepNext` remained `0`.
- Production endpoint QA after restart:
  - live `/apply` on `pg60112.docx` returned 200, created DOCX/PDF/ZIP, and final eligible `keepNext` was `0` with `Heading 2: 6` preserved;
  - live `/apply` on `pg60115.docx` returned 200, created DOCX/PDF/ZIP, and final eligible `keepNext` was `0` with `Heading 2: 11` preserved.
- Verification:
  - rollback baseline before this work: `c1de9cc9e75a72911ee52f64a6f105a7755b4d34`;
  - `./gutenberg/bin/python -m py_compile gutendocx/core/whole.py gutendocx/web/server.py gutendocx/tests/test_body_style_normalization.py` passed;
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed with 36 tests;
  - extracted Web UI script passed `node --check -`;
  - `git diff --check` passed.
- Production restart verification passed: `gutendocx`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` active; bind stayed `127.0.0.1:8000`; local `/health` OK; public URL still redirects to Cloudflare Access.
- Runtime `config.yaml` remains user/platform state and must not be staged unless explicitly requested.

**2026-06-13:** Added cautious table, hyperlink, and TOC style repair.

Current iteration:

- Investigated client examples `pg61492.docx` and `pg61506.docx`.
  - `pg61492.docx` contains 4 tables and 173 table-cell paragraphs.
  - Both files contain many `w:hyperlink` runs and an existing TOC inside `w:sdt/w:sdtContent`.
- Implemented a narrow font-level repair:
  - body font/size/bold/italic now also reaches table-cell text and visible hyperlink runs;
  - final DOCX files get a post-LibreOffice table/hyperlink repair pass because LibreOffice can strip some run font attributes;
  - table geometry, borders, widths, cell margins, hyperlink relationships, field instructions, and TOC/PAGEREF field codes are not recreated or removed;
  - TOC styling supports `Same as Body`, `Same as Heading`, and `Custom` in the UI and is stored in `style_overrides.TOC`;
  - existing TOC blocks are preserved instead of deleted/reinserted, then TOC styles/result-runs are repaired before and after LibreOffice, including TOC paragraphs inside `sdtContent`.
- QA on attached examples:
  - baseline with target Body `Aptos 10` and TOC `Georgia 9`: `pg61492` had table `164/164` bad, hyperlink `41/41` bad, TOC `52/52` bad; `pg61506` had hyperlink `40/40` bad and TOC `46/46` bad;
  - after core body repair: table/hyperlink bad counts reached `0` on the same files;
  - existing-source TOC repair on copied attachments reduced TOC bad counts to `0` while preserving field instructions.
- Verification so far:
  - safety commit before this work: `9aae156` (`Fix cover roles and footer page number styling`), excluding runtime `config.yaml`;
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed with 30 tests;
  - extracted Web UI script passed `node --check -`.
- Production endpoint QA after restart:
  - `pg61492.docx` via live `/apply`: DOCX, PDF, and ZIP were created; table bad `0`, hyperlink bad `0`, TOC bad `0`, with 26 visible TOC runs and field instruction preserved;
  - `pg61506.docx` via live `/apply`: DOCX, PDF, and ZIP were created; hyperlink bad `0`, TOC bad `0`, with 24 visible TOC runs and field instruction preserved.
- Host-mode LibreOffice (`use_docker=false`) only performs `--convert-to docx` in this app path, so full PDF/ZIP/index-update acceptance was verified through the production Docker/UNO endpoint path after restart.
- Runtime `config.yaml` remains user/platform state and must not be staged unless explicitly requested.

**2026-06-12:** Fixed cover role and page-number style override regressions.

Current iteration:

- Investigated the client's 2026-06-09 apply jobs from `output/audit_events.jsonl` and `output/jobs/*.json`.
  - Candidate source batches: `batch_1780990060` (`pg1112`-`pg1124`), `batch_1780996526` (`pg1125`), and `batch_1780996834` (`pg1126`-`pg1137`).
  - All used cover/body/vision/TOC apply with `Title 24`, `Subtitle 18`, `Author 18`, and `Footer 11` style settings.
- Baseline QA on existing client outputs confirmed:
  - `pg1125`, `pg1128`, and `pg1133`-`pg1137` had `Cover Author` paragraphs with direct `24pt`/bold run formatting overriding the intended `Cover Author` style;
  - all 26 final DOCX files had PAGE fields in footers without explicit page-number font/size/bold/italic formatting.
- Fixed cover style application:
  - `Cover Title`, `Cover Subtitle`, and `Cover Author` now all clear direct run formatting by default when the role style is applied;
  - this prevents source direct formatting such as `24pt`/bold from winning over the configured cover style.
- Fixed page-number style durability:
  - PAGE fields are now created with explicitly styled field/result runs;
  - final DOCX files are repaired after LibreOffice round-trip so footer PAGE fields retain configured page-number styling before ZIP/download packaging;
  - the UI now sends explicit `bold: false` and `italic: false` for unchecked Page Number override flags and uses visible effective footer family/size values when override is enabled.
- Added focused regression tests for cover role direct-format cleanup and footer PAGE-field styling/repair.
- Verification:
  - baseline QA before change: `BASELINE_COVER_BAD_COUNT 7`, `BASELINE_FOOTER_BAD_COUNT 26 OF 26`, and deterministic `pg1125` author run retained `24.0`/bold;
  - after-QA on the same real files: deterministic cover bad count `0`, footer repair bad count `0 OF 26`;
  - `./gutenberg/bin/python -m py_compile gutendocx/core/cover.py gutendocx/core/layout.py gutendocx/web/server.py gutendocx/tests/test_cover_footer_style_regressions.py`;
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed: 25 tests;
  - extracted Web UI script syntax checked with `node --check -`.
- No production service restart was performed yet.
- Runtime `config.yaml` remains user/platform state and was not intentionally edited.

**2026-06-07:** Tightened audit logging signal and admin operational metrics.

Current iteration:

- Reduced polling noise in `output/audit_events.jsonl`:
  - `GET /jobs/{job_id}` now logs `job.checked` only on first poll, state/progress changes, or every `GUTENDOCX_POLL_AUDIT_EVERY` polls (default `10`);
  - `/events/client` now accepts every `client.apply_job_polled` event but only writes the first/state-change/sample events to JSONL.
- Added download confirmation analytics by linking `client.download_clicked` events to job/batch summaries.
- Extended `/admin/api/summary` with throughput:
  - average batch duration;
  - average seconds per file;
  - slowest jobs for the selected period.
- Added audit warning detection for completed cover+vision jobs with zero recorded AI cost, both as read-only admin summary warnings for existing jobs and as future best-effort `apply.audit_warning` events.
- Updated `/admin` with Downloads confirmed, Avg batch duration, Avg seconds/file, Audit warnings, Slowest Jobs, and Audit Warnings panels.
- This is logging/admin observability only; no DOCX/PDF processing, TOC, LibreOffice, AI prompts, model choice, or cleanup behavior was changed.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/web/server.py gutendocx/tests/test_admin_activity_summary.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed: 21 tests.
  - extracted admin script syntax checked with `node --check -`.
  - direct `_activity_summary(days=30)` on live logs completed in about 1.5 seconds and returned slowest jobs plus audit warnings.
- Production service was restarted after the required pre-checks.
- Post-restart verification:
  - `gutendocx.service`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - local `/admin/api/summary?days=30` returns throughput, 10 slowest jobs, 46 download confirmations, and 1 audit warning on current logs;
  - public URL still redirects to Cloudflare Access login.

**2026-06-07:** Extended parasite Word-mark cleanup with advisor/report UX.

Current iteration:

- Kept the manual `Clean parasite Word marks` workflow unchanged.
- Added a read-only `/word_cleanup/analyze` endpoint that structurally inspects body blank gaps and recommends high-confidence `^p` / `^l` cleanup patterns without sending document text to an external AI service.
- Added `Analyze cleanup` and `Apply recommended cleanup` controls under `Whole document -> Text styles`.
  - `Analyze cleanup` shows a concise report and fills the existing patterns textarea with recommended patterns.
  - The client can edit the textarea before applying, or run `Apply recommended cleanup` to enable the recommendation and launch the existing `Apply Styles` flow.
- Added a short cleanup report popup after successful Apply when cleanup is enabled, covering both manual and recommended cleanup:
  - patterns used;
  - gaps cleaned;
  - empty paragraphs removed;
  - manual line breaks removed.
- Added a source/status label under the cleanup `Patterns` textarea so the client can tell whether values came from saved config, the latest cleanup analysis, or manual editing.
- Limited the cleanup analysis report block height and enabled internal scrolling so long reports do not stretch the page.
- Added analyzer/API tests while keeping the prior manual cleanup and `Para1` manual-line-break behavior covered.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/word_cleanup.py gutendocx/core/whole.py gutendocx/web/server.py gutendocx/tests/test_word_cleanup.py gutendocx/tests/test_word_cleanup_api.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests/test_word_cleanup.py gutendocx/tests/test_word_cleanup_api.py gutendocx/tests/test_para1_manual_breaks.py -q` passed: 15 tests.
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed: 18 tests.
  - extracted Web UI script syntax checked with `node --check -`.
- Production service was restarted after the required pre-checks.
- Post-restart verification:
  - `gutendocx.service`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - local `/` serves cleanup analyzer controls and cleanup popup markup;
  - local `/word_cleanup/analyze` on `Simples/pg1014.docx` returns the expected patterns and `13`/`39`/`55` cleanup estimate;
  - public URL still redirects to Cloudflare Access login.

**2026-06-07:** Implemented managed cleanup for parasite Word marks in body text.

Current iteration:

- Added a UI-controlled `word_cleanup` setting for body processing, disabled by default.
- Added `Clean parasite Word marks` under `Whole document -> Text styles` with a textarea for `^p` / `^l` patterns and fixed replacement mode `^p`.
- Supported UI payload shape: `styles.word_cleanup = { enabled, patterns_text }`.
- Added config schema defaults:
  - `word_cleanup.enabled: false`
  - `word_cleanup.patterns: []`
  - `word_cleanup.replacement: "^p"`
- Added deterministic DOCX cleanup before body/headings/`Para1` style passes:
  - only body-zone cleanable blank or manual-line-break-only paragraphs are eligible;
  - normal text paragraph boundaries are not treated as removable `^p`;
  - headings, TOC/protected styles, page/section breaks, fields, and embedded objects are skipped.
- Added cleanup result metadata under `whole.word_cleanup` and audit completion summaries with counts only.
- Added parser and DOCX cleanup tests while preserving the previous `Para1=>left` behavior.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/word_cleanup.py gutendocx/core/whole.py gutendocx/web/server.py gutendocx/tests/test_word_cleanup.py gutendocx/tests/test_word_cleanup_api.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed: 16 tests.
  - extracted Web UI script syntax checked with `node --check -`.
- Production service was restarted after the required pre-checks.
- Post-restart verification:
  - `gutendocx.service`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - local `/` serves `Clean parasite Word marks`;
  - local `/config` returns `word_cleanup`;
  - public URL still redirects to Cloudflare Access login.
- First client test artifact:
  - processed `pg1014.docx` with cleanup enabled and no other intentional UI changes;
  - audit/job metadata showed `13` gaps modified, `39` empty paragraphs removed, and `55` manual line breaks removed;
  - resulting DOCX/PDF/ZIP were sent to the client for testing; wait for client feedback before changing cleanup semantics.
- Runtime `config.yaml` had a pre-existing user/runtime diff and was not intentionally edited.

**2026-05-26:** Improved logging analytics and admin observability without changing file processing.

Current iteration:

- Implemented read-only backend activity summaries over existing `output/jobs/*.json`, `output/audit_events.jsonl`, and `output/ai_costs.jsonl`.
- Extended `/admin/api/summary` with `activity` data: job/file totals, recent jobs, recent errors, option breakdowns, AI-cost context, and audit health.
- Updated `/admin` to show completed files, jobs, failed/cancelled files, files completed without AI-cost events, Recent Jobs, Recent Errors, and Audit Health while keeping the existing AI-cost/storage/model controls.
- Normalized new audit events with `schema_version`, `source`, `operation`, and `actor_email` when available.
- Added cost-context fields for new AI cost rows and best-effort cost logging for cover analyze/apply, debug vision, and learn cover/body endpoints when those endpoints already perform AI work.
- Added tests for activity summaries, audit event schema metadata, and AI cost context.
- Explicitly did not change DOCX/PDF processing, LibreOffice behavior, AI prompts, model governance, cleanup behavior, or the conditions that decide whether AI is called.
- Commits:
  - `6b42439 Add admin activity summary backend`
  - `cc36bef Show activity health in admin panel`
  - `9fa0c3e Normalize audit and AI cost logging`
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/web/server.py gutendocx/tests/test_admin_activity_summary.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` passed: 7 tests.
  - extracted admin script syntax checked with `node --check -`.
  - TestClient `/admin/api/summary?days=30` returned `activity` with `recent_jobs` and `audit_health`.
- Production service was restarted after the required pre-checks.
- Post-restart verification:
  - `gutendocx.service`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - local `/admin/api/summary?days=30` with admin header returned the new `activity` object;
  - public URL still redirects to Cloudflare Access login.

**2026-05-26:** Made two low-risk observability cleanup improvements after reviewing recent logs.

Current iteration:

- Created baseline checkpoint commit `c20203e` before making changes because the working tree only had runtime `config.yaml` state.
- Added a `/favicon.ico` 204 response to remove recurring browser 404 noise from audit logs.
- Added frontend `auditErrorData()` so client-side error audit events keep a bounded `error` string and include structured `error_summary` fields such as HTTP status and Cloudflare title/code when available.
- Did not change DOCX processing, Apply/job execution, AI model selection, cost calculation, retention cleanup, or production exposure.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/web/server.py`
  - extracted Web UI script syntax checked with `node --check -`
- Production service was restarted after the required pre-checks.
- Post-restart verification:
  - `gutendocx.service`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - local `/favicon.ico` returns 204;
  - public URL still redirects to Cloudflare Access login.

**2026-05-26:** Updated the confirmed `Para1` paragraph style rule for manual line breaks.

Current iteration:

- Client reported the workflow is working well and requested `Para1=>left`.
- Updated `gutendocx/core/whole.py` so non-heading body paragraphs with manual line breaks still get style `Para1`, but both the `Para1` style and matching paragraphs are now left-aligned.
- Updated focused pytest coverage in `gutendocx/tests/test_para1_manual_breaks.py` to expect left alignment while preserving the existing heading and learned-heading exclusions.
- Left `config.yaml` untouched as runtime/user-editable state.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/whole.py gutendocx/tests/test_para1_manual_breaks.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests/test_para1_manual_breaks.py -q` passed: 4 tests.
- Production service was restarted after the required pre-checks.
- Post-restart verification:
  - `gutendocx.service`, `cloudflared`, `server-firewall`, `tailscaled`, and `ssh` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - public URL still redirects to Cloudflare Access login.

**2026-05-19:** Implemented the confirmed `Para1` paragraph style rule for manual line breaks.

Current iteration:

- Client confirmed the previously proposed logic:
  - after Heading processing, check the remaining non-heading body paragraphs for manual line breaks (`^l` / `@L@` / Word line break);
  - paragraphs containing such a break get style `Para1` with centered alignment; superseded on 2026-05-26 by client request `Para1=>left`;
  - other non-heading paragraphs remain in the current normal/body style behavior.
- Analysis found and implementation kept this as a deterministic DOCX body-formatting change, not an AI/prompt change:
  - current whole-document body formatting lives in `gutendocx/core/whole.py`;
  - `_apply_body_style_overrides()` applies Body formatting to non-heading body paragraphs;
  - `_apply_headings_style_overrides()` protects/matches Heading roles using built-in Heading styles plus `detected_style_mapping`;
  - current `config.yaml` maps learned headings such as `Headings: Heading 2`, `Heading2: Heading 3`, `Heading3: Para 08`, and `Body: Normal`.
- Implemented in `gutendocx/core/whole.py`:
  - detect manual Word line breaks as `<w:br>` without `w:type="page"`/`column`, with `"\n"`, literal `@L@`, and literal `^l` fallbacks;
  - skip cover/protected styles, TOC styles, built-in Heading styles, and headings learned through `detected_style_mapping`;
  - create/update paragraph style `Para1` based on `Normal`;
  - set `Para1` and matching paragraphs to centered alignment;
  - run the `Para1` pass after Body and Heading overrides so centering wins for the targeted paragraphs.
- Added focused tests in `gutendocx/tests/test_para1_manual_breaks.py`, including learned heading mappings such as `Heading3: Para 08`.
- Added `pytest` to `requirements.txt` and installed it in the project venv.
- Verification:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/whole.py gutendocx/tests/test_para1_manual_breaks.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests/test_para1_manual_breaks.py -q` passed: 4 tests.
- Production service was restarted after the required pre-checks.
- Post-restart verification:
  - `gutendocx.service` active;
  - `127.0.0.1:8000` bind preserved;
  - local `/health` OK;
  - public URL still redirects to Cloudflare Access login.

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
- Added admin panel at `/admin`, protected by Cloudflare Access authenticated email and limited to `highmac@gmail.com`; admin APIs expose AI cost summaries and file cleanup controls.
- Added scheduled retention cleanup for uploaded/generated files older than 15 days while preserving audit/cost logs and active job state.
- Moved AI model selection under admin control: regular users see the configured model but cannot change it; backend ignores non-admin/user-supplied model overrides and uses the model saved in `config.yaml`.
- Optimized body-only batch Apply: when cover scope is off, the XLSX report no longer triggers AI cover dry-run just to fill title/subtitle/author metadata.
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
| Admin panel | `/admin`, app-level guarded by Cloudflare Access email; allowed admin email defaults to `highmac@gmail.com` via `GUTENDOCX_ADMIN_EMAILS` |
| AI model control | Admin-only via `/admin`; normal Apply/Analyze requests are forced to the configured `cover.vision.model` |

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
   - Include `gemini-2.5-flash-lite` as a future A/B benchmark candidate for vision/classification workloads. Do not implement Gemini support or change the default yet; first design a provider abstraction and compare quality/cost/latency on representative GutenDocx files.
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
   - Also evaluate whether Google `gemini-2.5-flash-lite` is worth supporting for cover/body vision classification, because it may be cheaper for image/text input than the current baseline while needing quality validation.
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
