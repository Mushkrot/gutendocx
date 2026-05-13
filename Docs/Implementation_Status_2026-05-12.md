# GutenDocx - Implementation Status

**Last updated:** 2026-05-13
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
  - `output/audit_events.jsonl` for structured diagnostic audit events.
- Upload UX: the primary "Upload files" control is a normal multi-file `.docx` picker. Do not attach `webkitdirectory` to that control unless adding a separate, explicitly labeled folder-upload feature.

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
- `/output` is statically mounted by the app. This is acceptable only because Cloudflare Access protects the hostname. Treat generated files as sensitive.
- `Uploads/` and `output/` can contain client manuscripts and generated files. Do not print, commit, or casually summarize their contents.
- `output/audit_events.jsonl` should log user-action metadata, selected options, file names/sizes, timings, outputs, and errors, but not document text/content or credential headers.
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
2. `Uploads/` and `output/` do not currently have a documented retention policy.
3. Request path/config handling assumes trusted users behind Cloudflare Access. Do not remove Access without first hardening app-level auth and path validation.
4. Built-in users/roles are a future roadmap item and would change the current Cloudflare Access-only app security model.
5. `config.yaml` changes during normal use. Do not automatically commit or revert it without confirming the diff belongs to the requested work.
6. Local docs are older and some historical files describe superseded LibreOffice macro approaches. Prefer `Docs/Integration_report 02.md` for the current LibreOffice/PyUNO architecture.

## Future Roadmap

These items are captured for future planning and should not be implemented without a separate explicit request:

1. Review newly available OpenAI/ChatGPT models up to ChatGPT 5.5, add suitable options to the UI, update token pricing, and test/benchmark which model is optimal for GutenDocx.
2. Build an administrative AI cost dashboard by reviewing the user's existing dashboard from another project and adapting the useful principles to GutenDocx.
3. Evaluate a possible full UI redesign based on another existing project design the user will provide.
4. Add users and roles: admin and normal user permissions, separate dashboards, and the required app-auth/security model around them.

## Recent Changes

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
