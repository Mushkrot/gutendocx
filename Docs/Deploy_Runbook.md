# GutenDocx Deploy Runbook

**Last updated:** 2026-05-13
**Environment:** Linux server `ai`, systemd, Cloudflare Tunnel, Cloudflare Access

## Ownership Boundary

This repo owns the GutenDocx app:

- FastAPI app code.
- Static web UI.
- App config and documentation.
- LibreOffice/DOCX processing pipeline.

`/ai/SECURITY` owns the server-wide operational layer:

- SSH, firewall, Tailscale, Docker exposure, Cloudflare Tunnel, Cloudflare Access/DNS/WAF, monitoring, alerting, backups, and `/ai/PORTS.yaml`.

If an app change needs a new public hostname, port, Cloudflare Access/WAF behavior, service bind, or monitoring rule, update `/ai/SECURITY` as part of the operational work.

## Production Baseline

- Public URL: `https://gutendocx.unicloud.ca`.
- Public access: Cloudflare Access protected.
- Tunnel: Cloudflare Tunnel `mainserver`.
- Local target: `http://localhost:8000`.
- systemd service: `gutendocx.service`.
- Working directory: `/ai/gutendocx`.
- Runtime command: `/ai/gutendocx/gutenberg/bin/uvicorn gutendocx.web.server:app --host 127.0.0.1 --port 8000`.
- Runtime user: `root`, retained for legacy compatibility.

## Do Not Break

- Do not remove Cloudflare Access from `gutendocx.unicloud.ca` without explicit approval.
- Do not bind production to `0.0.0.0`.
- Do not use `dev.sh` as the production launcher.
- Do not print or commit client files from `Uploads/` or `output/`.
- Do not start a root-to-user migration unless explicitly requested.

## Routine Checks

```bash
systemctl is-active gutendocx cloudflared server-firewall tailscaled ssh
systemctl status gutendocx --no-pager --lines=80
systemctl cat gutendocx
ss -lntup | rg ':8000'
curl -fsS http://127.0.0.1:8000/health
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://gutendocx.unicloud.ca/
```

Expected:

- Services are active.
- `8000` is bound to `127.0.0.1`.
- Local `/health` returns OK.
- Public unauthenticated request redirects to Cloudflare Access login.

## Diagnostic Audit Log

GutenDocx writes structured diagnostic events to:

```text
output/audit_events.jsonl
```

This log is intended to reconstruct what happened when a client reports a problem:

- uploaded file names, relative paths, sizes, and batch ids;
- selected UI options and style controls;
- button/action events such as upload, Apply, Apply TOC, Learn Cover/Body, Reset, and Download;
- API endpoint start/completion/error events with durations;
- output/download paths and AI cost summaries.

Privacy rule: audit logs may contain client file names and operational paths, but must not contain DOCX text/content or credential headers. Treat the log as sensitive operational data.

Useful inspection command:

```bash
tail -n 200 output/audit_events.jsonl
```

## Admin Panel

The admin panel is available at:

```text
https://gutendocx.unicloud.ca/admin
```

Access is enforced inside the FastAPI app using the Cloudflare Access authenticated email header:

```text
Cf-Access-Authenticated-User-Email
```

Only `highmac@gmail.com` is allowed by default. To change the list, set:

```bash
GUTENDOCX_ADMIN_EMAILS=highmac@gmail.com,other@example.com
```

Admin APIs are under `/admin/api/*` and use the same guard. Direct access to `/static/admin.html` is also blocked unless the same admin email is present.

The panel currently shows:

- AI cost totals and recent AI usage from `output/ai_costs.jsonl`;
- current AI model and an admin-only model selector;
- storage totals for `Uploads/` and `output/`;
- dry-run and real cleanup controls for old uploaded/generated files.

AI model selection is admin-only. The regular user UI fetches the current model from:

```bash
GET /settings/model
```

The admin panel saves model changes through:

```bash
POST /admin/api/model
```

Backend Apply/Analyze/job paths do not trust a user-supplied `model` field; they force requests to the model saved in `config.yaml` under `cover.vision.model`.

## Batch Timeout Recovery

Batch Apply now uses background jobs so the browser does not keep a single long `/apply` request open through Cloudflare.

Main endpoints:

```bash
POST /jobs/apply
GET /jobs/<job_id>
```

Job state is persisted as JSON under:

```text
output/jobs/
```

The UI polls `GET /jobs/<job_id>` until the job reaches `completed`, then uses the returned download metadata. Duplicate protection reuses an existing queued/running job when the same batch/options signature is submitted again.

Job JSON includes per-file status records:

- `queued`
- `running`
- `completed`
- `failed`

Batch jobs support partial success: if one file fails, the job can still complete and return a ZIP for successful files plus an XLSX report with `Status` and `Error` columns.

## Job Cleanup

Old completed/failed/interrupted job records and related outputs can be cleaned through:

```bash
curl -fsS -X POST http://127.0.0.1:8000/jobs/cleanup \
  -H 'Content-Type: application/json' \
  -d '{"older_than_days":30,"dry_run":true,"include_outputs":true,"include_uploads":false}'
```

Default is `dry_run: true`. Review the returned `items` before running with `dry_run: false`.

Cleanup only considers finished jobs and only removes paths under `output/` and, when explicitly enabled, `Uploads/`.

## Scheduled Retention Cleanup

The app starts a daemon cleanup loop on service startup. By default it removes uploaded/generated files older than 15 days:

```bash
GUTENDOCX_RETENTION_DAYS=15
GUTENDOCX_SCHEDULED_CLEANUP=1
GUTENDOCX_CLEANUP_INTERVAL_SECONDS=86400
GUTENDOCX_CLEANUP_INITIAL_DELAY_SECONDS=60
```

The cleanup excludes `output/audit_events.jsonl`, `output/ai_costs.jsonl`, and active job state under `output/jobs/`. Finished old job records are cleaned through the job cleanup path.

## Cancel And Retry

Running/queued jobs can be cancelled:

```bash
curl -fsS -X POST http://127.0.0.1:8000/jobs/<job_id>/cancel
```

Cancellation is cooperative: the current file may finish first, then remaining queued files are marked `cancelled`.

Failed files can be retried as a new job:

```bash
curl -fsS -X POST http://127.0.0.1:8000/jobs/<job_id>/retry_failed
```

The retry job uses the same Apply options but only the files with `failed` status, and writes to a retry batch id.

## Restart Resume

Queued/running jobs are persisted under `output/jobs/`. On service startup, any job that was still `queued` or `running` is requeued automatically.

Resume is best-effort and file-level:

- Files already marked `completed` are reused when their generated output still exists.
- A file that was `running` during restart is moved back to `queued` and processed again.
- Remaining queued files continue normally.

This avoids throwing away a large batch after a restart and reduces duplicate AI processing for files that had already completed.

Legacy recovery remains available for older synchronous `/apply` flows. Large synchronous batch Apply requests can exceed Cloudflare's request timeout even when the server continues processing and eventually writes the ZIP. The legacy UI recovery endpoint is:

```bash
curl -fsS http://127.0.0.1:8000/batch/status/<batch_id>
```

When `ready` is true, the response includes `download` metadata for the ZIP.

## Restart Procedure

Use this only after a code/config change that requires a restart.

```bash
systemctl restart gutendocx
systemctl is-active gutendocx
curl -fsS http://127.0.0.1:8000/health
ss -lntup | rg ':8000'
```

After restart, confirm:

- `gutendocx.service` is active.
- `127.0.0.1:8000` is still the bind.
- Public unauthenticated access still redirects to Cloudflare Access.

## Static Web UI Changes

The Web UI is served directly from `gutendocx/web/static/index.html` by the running FastAPI app. Simple HTML/JS/CSS edits generally do not require a service restart or Docker rebuild.

After a static UI edit:

```bash
curl -fsS http://127.0.0.1:8000/ | rg 'expected-ui-marker'
```

Ask users to hard-refresh their browser if they may have cached the old page:

- Windows Chrome/Edge: `Ctrl+F5` or `Ctrl+Shift+R`.
- macOS Chrome/Safari: reload with cache bypass as appropriate for the browser.

## Development Launcher Warning

`dev.sh` is for development only. It uses:

```bash
python -m uvicorn gutendocx.web.server:app --reload --host 0.0.0.0 --port 8000
```

Do not use this as production runtime on the server.

## Future Hardening Plan

Keep root runtime for now. A safer next step is a tested systemd hardening drop-in around the existing root runtime:

- `NoNewPrivileges=true`
- `PrivateTmp=true`
- constrained write paths for:
  - `/ai/gutendocx/Uploads`
  - `/ai/gutendocx/output`
  - `/ai/gutendocx/reports`
  - `/ai/gutendocx/config.yaml`
  - LibreOffice/Docker working paths if needed

Do not apply these blindly. GutenDocx uses Docker/LibreOffice and writes project-local artifacts, so each restriction needs a test and rollback path.

## Data Retention

`Uploads/` and `output/` may contain client documents and generated outputs. Current retention is manual. A future cleanup policy should define:

- how long uploaded manuscripts are kept;
- how long generated DOCX/PDF/ZIP files are kept;
- whether `output/ai_costs.jsonl` should be retained or rotated;
- whether cleanup should be manual, cron-based, or app-driven.
