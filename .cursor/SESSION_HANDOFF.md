# GutenDocx Session Handoff

Last updated: 2026-06-27 UTC

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

2026-06-27 `pg1868.docx` single trailing-break body boundary:

- Client example:
  - `pg1868.docx` has one explicit page/section break in the final paragraph.
  - Before this fix, `_compute_body_start_index()` returned the end of the document, so whole-document body analysis saw zero body paragraphs and no body styles.
- Implemented:
  - a lone final explicit break is treated as trailing noise and no longer becomes the body boundary;
  - one non-final break and normal two-break cover/blank/body documents keep their previous body-start behavior;
  - TOC, heading, detected-heading, field, protected-style, and `Para1` exclusion logic was not loosened.
- Page-count guard:
  - real-file PDF QA showed `style_overrides.Body.line_spacing: 1.08` became active after the boundary fix and increased `pg1868` from 64 to 66 pages;
  - direct `Body.line_spacing` is now skipped only when body starts at `0` because one final explicit break was ignored;
  - other Body overrides still apply, including font, size, bold/italic, and justify alignment.
- QA:
  - `pg1868` analyze: `body_start_index=0`, `528` body paragraphs;
  - local apply: `Para1` on `26` manual-line-break paragraphs;
  - TOC SDT field/instruction structure preserved;
  - LibreOffice page count stayed `64 -> 64`;
  - `pg60112`/`pg60115` keepNext regressions still clear to `0` with heading counts preserved;
  - `pg61492`/`pg61506` structural TOC/table/hyperlink checks remain present;
  - full pytest passes with `42` tests and `git diff --check` passes.
- Commit/deploy:
  - commit `20e623d` (`Fix trailing final break body detection`) was pushed to `origin/exp/libreoffice-toc`;
  - production was restarted with `systemctl restart gutendocx`;
  - post-deploy smoke passed: app and infrastructure services active, port `8000` bound to `127.0.0.1`, local `/health` OK, public URL redirects to Cloudflare Access;
  - live `/apply` on a `/tmp` copy of `pg1868.docx` returned 200, produced DOCX/PDF/ZIP, reported `body_start_index=0`, skipped Body line spacing for `503` recovered-body paragraphs, applied `Para1` before LibreOffice/TOC round-trip, and final PDF page count was `64`;
  - final DOCX structural check found real manual-line-break body paragraphs are `Para1`; only cover title/subtitle and the final service break paragraph were non-`Para1`.
- `config.yaml` remains runtime/user state and must remain unstaged unless explicitly requested.

2026-06-17 safe body paragraph style normalization:

- Client examples:
  - `pg60115.docx`: source `Normal` has style-level `keepNext=True`; baseline showed 758 eligible body paragraphs effectively inheriting `keep with next`;
  - `pg60112.docx`: body text mostly uses source `Para 01` / `Para 02` / `Para 14`; baseline showed one eligible body paragraph effectively inheriting `keep with next`.
- Implemented:
  - ordinary post-cover body paragraphs are moved to a safe body style (`GD Body` when configured Body is `Normal`/`Обычный`);
  - global Word `Normal` is not modified;
  - safe body style and normalized paragraphs set `keep_with_next=False`;
  - headings, detected heading mappings, `Para1`, TOC, field paragraphs, cover/header/footer styles, table geometry, hyperlink relationships, spacing/alignment/indents/numbering are excluded from intentional changes;
  - UI/config exposes `body_style_normalization.enabled` as `Normalize body paragraph styles` under `Whole document -> Text styles -> Body Text`.
- Client-facing workflow:
  - no new required client action; normal `Apply Styles` usage stays the same because the setting is enabled by default;
  - mention the checkbox only as a fallback/off-switch for rare source files where preserving original body paragraph styles is desired.
- QA:
  - real-file before/after: `pg60112` eligible `keepNext` `1 -> 0`; `pg60115` eligible `keepNext` `758 -> 0`;
  - heading counts preserved (`pg60112` `Heading 2: 6`, `pg60115` `Heading 2: 11`);
  - `Para1` still applies for manual-line-break paragraphs; Word displays style id `Para1` as `Para 1`;
  - previous regression samples stayed green: `pg61492` table bad `0/164`, non-TOC hyperlink bad `0/41`; `pg61506` non-TOC hyperlink bad `0/40`;
  - Docker/LibreOffice smoke created DOCX/PDF for both new files and post-LO eligible `keepNext` stayed `0`.
- Production endpoint QA after restart:
  - live `/apply` on `pg60112.docx` returned 200, created DOCX/PDF/ZIP, and final eligible `keepNext` was `0` with `Heading 2: 6` preserved;
  - live `/apply` on `pg60115.docx` returned 200, created DOCX/PDF/ZIP, and final eligible `keepNext` was `0` with `Heading 2: 11` preserved;
  - standard smoke passed: services active, bind `127.0.0.1:8000`, local `/health` OK, public Cloudflare Access redirect preserved.
- Verification:
  - rollback baseline before work: `c1de9cc9e75a72911ee52f64a6f105a7755b4d34`;
  - py_compile for changed Python files passed;
  - full pytest currently passes with 36 tests;
  - extracted Web UI JS passes `node --check -`;
  - `git diff --check` passes.
- `config.yaml` remains runtime/user state and must remain unstaged unless explicitly requested.

2026-06-13 table/hyperlink/TOC style repair:

- Client examples:
  - `pg61492.docx`: 4 tables, 173 table-cell paragraphs, hyperlinks, and existing TOC in `w:sdt/w:sdtContent`;
  - `pg61506.docx`: hyperlinks and existing TOC in `w:sdt/w:sdtContent`.
- Implemented:
  - body font-level overrides now reach table-cell text and visible `w:hyperlink` runs;
  - final DOCX files get a post-LibreOffice table/hyperlink repair pass;
  - TOC style UI now supports `Same as Body`, `Same as Heading`, and `Custom`;
  - `style_overrides.TOC` drives pre-LibreOffice TOC styles and post-LibreOffice TOC result-run repair;
  - existing TOC blocks are preserved rather than deleted/reinserted, and nested `sdtContent` TOC blocks are detected/styled.
- Safety/QA:
  - safety commit before this repair: `9aae156`, excluding runtime `config.yaml`;
  - baseline on the attached files with target Body `Aptos 10` and TOC `Georgia 9`: `pg61492` table `164/164` bad, hyperlink `41/41` bad, TOC `52/52` bad; `pg61506` hyperlink `40/40` bad, TOC `46/46` bad;
  - after core repair, table/hyperlink bad counts are `0`;
  - existing-source TOC repair on copied attachments reduces TOC bad counts to `0` and preserves field instructions;
  - production endpoint QA after restart passed on both attached files: live `/apply` created DOCX/PDF/ZIP, `pg61492` table/hyperlink/TOC bad counts were `0`, and `pg61506` hyperlink/TOC bad counts were `0`;
  - full pytest currently passes with 30 tests, and extracted Web UI JS passes `node --check -`.
- Caveat:
  - host-mode LibreOffice in this app uses `--convert-to docx`; final PDF/ZIP and real TOC index-update acceptance was verified via the production Docker/UNO endpoint path after service restart.
- `config.yaml` is still runtime/user state and must remain unstaged unless explicitly requested.

2026-06-12 cover/page-number style override regressions:

- Client-reported style issue was traced to 2026-06-09 apply jobs:
  - `batch_1780990060`: `pg1112.docx`-`pg1124.docx`;
  - `batch_1780996526`: `pg1125.docx`;
  - `batch_1780996834`: `pg1126.docx`-`pg1137.docx`.
- Baseline QA on saved client outputs confirmed:
  - `Cover Author` direct `24pt`/bold formatting survived over the configured `Cover Author` style in `pg1125`, `pg1128`, and `pg1133`-`pg1137`;
  - all 26 final DOCX files had footer PAGE fields without explicit page-number style run properties.
- Implemented fixes:
  - cover role application now clears direct run formatting by default for Title, Subtitle, and Author;
  - PAGE fields now include styled field/result runs, and final DOCX files are repaired after LibreOffice round-trip before ZIP/download packaging;
  - Page Number UI override now sends explicit unchecked `bold:false`/`italic:false` and effective visible family/size values.
- Added regression tests in `gutendocx/tests/test_cover_footer_style_regressions.py`.
- Verification passed:
  - before QA: `BASELINE_COVER_BAD_COUNT 7`, `BASELINE_FOOTER_BAD_COUNT 26 OF 26`;
  - after QA on the same real files: deterministic cover bad count `0`, footer repair bad count `0 OF 26`;
  - py_compile for changed Python files;
  - full `./gutenberg/bin/python -m pytest gutendocx/tests -q` with 25 tests;
  - extracted Web UI script `node --check -`.
- Production was not restarted in this session. Restart/deploy still needs the standard pre-checks, localhost bind verification, local `/health`, and Cloudflare Access redirect check if the user asks to deploy.
- `config.yaml` remains runtime/user state and should not be staged unless explicitly requested.

2026-06-07 polling/throughput/download observability:

- Reduced audit-log noise from polling:
  - server `job.checked` is now logged only on first poll, status/progress changes, or every `GUTENDOCX_POLL_AUDIT_EVERY` polls (`10` by default);
  - client `apply_job_polled` events are still accepted, but unchanged intermediate polls return `logged: false` and are not written to JSONL.
- Admin summary now links `client.download_clicked` events to jobs/batches and reports download confirmation.
- Admin summary now reports throughput: average batch duration, average seconds per file, and slowest jobs for the selected period.
- Admin summary and future audit events now flag cover+vision jobs with zero AI usage/cost as `cover_without_ai_cost` warnings.
- `/admin` now shows Downloads confirmed, Avg batch duration, Avg seconds/file, Audit warnings, Slowest Jobs, and Audit Warnings.
- No file-processing behavior was changed: DOCX/PDF output, TOC, LibreOffice, AI prompts, model governance, cleanup behavior, and AI-call conditions are untouched.
- Verification passed:
  - py_compile for `server.py` and admin activity tests;
  - full `./gutenberg/bin/python -m pytest gutendocx/tests -q` with 21 tests;
  - admin JS `node --check`;
  - direct `_activity_summary(days=30)` on live logs completed in about 1.5 seconds.
- Production was restarted and verified: required services active, port `8000` still localhost-bound, local `/health` OK, local `/admin/api/summary?days=30` returns throughput, 10 slowest jobs, 46 download confirmations, and 1 audit warning on current logs, and public URL still redirects to Cloudflare Access.
- `config.yaml` remains runtime/user state and should not be staged unless explicitly needed.

2026-06-07 Word cleanup advisor/report UX:

- Manual `Clean parasite Word marks` remains available under `Whole document -> Text styles`.
- Added read-only `/word_cleanup/analyze` for structural advisor recommendations. It inspects body blank gaps and returns recommended `^p` / `^l` patterns, candidate summaries, and count-only estimates without sending document text to an external AI service.
- Web UI now has `Analyze cleanup` and `Apply recommended cleanup` next to the cleanup textarea.
  - `Analyze cleanup` fills the same editable patterns textarea and shows a concise report below it.
  - `Apply recommended cleanup` enables cleanup, keeps Body scope on, and launches the existing `Apply Styles` flow.
  - If the client wants to adjust the recommendation, they edit the textarea manually and press `Apply Styles`.
- The cleanup textarea has a source/status label that distinguishes saved config patterns, latest analysis recommendations, and manual edits.
- The cleanup analysis report block has a fixed max height with internal scrolling for long output.
- Successful Apply now shows a short cleanup popup when cleanup is enabled, for both manual and recommended runs: patterns used, gaps cleaned, empty paragraphs removed, and manual line breaks removed.
- Verification passed:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/word_cleanup.py gutendocx/core/whole.py gutendocx/web/server.py gutendocx/tests/test_word_cleanup.py gutendocx/tests/test_word_cleanup_api.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests/test_word_cleanup.py gutendocx/tests/test_word_cleanup_api.py gutendocx/tests/test_para1_manual_breaks.py -q` with 15 tests.
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` with 18 tests.
  - extracted Web UI script syntax checked with `node --check -`.
- Production was restarted and verified: required services active, port `8000` still localhost-bound, local `/health` OK, local `/` serves cleanup analyzer controls plus cleanup popup markup, local `/word_cleanup/analyze` returns expected `pg1014.docx` recommendations, and public URL still redirects to Cloudflare Access.
- `config.yaml` remains runtime/user state and should not be staged unless explicitly needed.

2026-06-07 managed Word mark cleanup:

- Added a UI-controlled body cleanup for parasite Word marks, disabled by default.
- The main UI now has `Clean parasite Word marks` under `Whole document -> Text styles`, next to the detected body-style inventory.
- Users can enter `^p` / `^l` patterns such as `^p^p` or `^p^l^l^l^l`; separators are whitespace, comma, or semicolon.
- The backend stores settings under `word_cleanup` with fixed replacement `^p` and validates that enabled patterns only use `^p` and `^l`.
- The DOCX pipeline runs cleanup after body start detection and before body/headings/`Para1` style passes.
- Cleanup only removes eligible blank/manual-line-break-only body paragraphs in matching blank gaps. It does not treat normal text paragraph endings as removable `^p`.
- Headings, TOC/protected styles, page/section breaks, fields, embedded objects, and non-empty paragraphs are skipped.
- Apply results now include `whole.word_cleanup`, and apply audit completion events include count-only cleanup summaries.
- Verification passed:
  - `./gutenberg/bin/python -m py_compile gutendocx/core/word_cleanup.py gutendocx/core/whole.py gutendocx/web/server.py gutendocx/tests/test_word_cleanup.py gutendocx/tests/test_word_cleanup_api.py`
  - `./gutenberg/bin/python -m pytest gutendocx/tests -q` with 16 tests.
  - extracted Web UI script syntax checked with `node --check -`.
- Production was restarted and verified: required services active, port `8000` still localhost-bound, local `/health` OK, local `/` serves `Clean parasite Word marks`, local `/config` returns `word_cleanup`, and public URL still redirects to Cloudflare Access.
- First client test artifact was generated from `pg1014.docx` with cleanup enabled and no other intentional UI changes. Metadata showed `13` gaps modified, `39` empty paragraphs removed, and `55` manual line breaks removed. The result was sent to the client for testing; wait for feedback before changing cleanup semantics.
- Pre-existing runtime `config.yaml` diff remains user/runtime state and was not intentionally changed.

2026-05-26 logging analytics/admin observability:

- Added read-only backend activity summary helpers over existing `output/jobs/*.json`, `output/audit_events.jsonl`, and `output/ai_costs.jsonl`.
- `/admin/api/summary` now includes `activity`: totals for jobs/files/errors, recent jobs, recent errors, option breakdowns, AI cost context, and audit health.
- `/admin` now shows activity cards, Recent Jobs, Recent Errors, and Audit Health alongside existing AI cost, model, and storage cleanup controls.
- New audit events include `schema_version`, `source`, `operation`, and `actor_email` when available.
- New AI cost events include better context such as operation/status/job/batch/input where available.
- Added best-effort audit/cost logging around cover analyze/apply, debug vision, and learn cover/body endpoints. These additions only record metadata after existing actions; they do not change DOCX/PDF processing, LibreOffice, AI prompts, model selection, cleanup, or the conditions that decide whether AI runs.
- Commits: `6b42439`, `cc36bef`, `9fa0c3e`.
- Verification passed: py_compile, full `./gutenberg/bin/python -m pytest gutendocx/tests -q` with 7 tests, admin JS `node --check`, TestClient admin summary, production restart QA.
- Production restart QA: infrastructure services active, port `8000` still localhost-bound, local `/health` OK, local admin summary returns `activity`, and public URL still redirects to Cloudflare Access.

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
