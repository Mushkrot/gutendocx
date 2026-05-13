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
