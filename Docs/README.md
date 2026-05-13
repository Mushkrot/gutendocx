# GutenDocx Documentation Index

**Start here:** [Implementation Status (2026-05-12)](./Implementation_Status_2026-05-12.md)

**Agent startup:** root [`AGENTS.md`](../AGENTS.md), root [`PROJECT_LOG.md`](../PROJECT_LOG.md), and [`.cursor/SESSION_HANDOFF.md`](../.cursor/SESSION_HANDOFF.md).

## Active Documents

| Document | Role |
| --- | --- |
| [Implementation_Status_2026-05-12.md](./Implementation_Status_2026-05-12.md) | Current project snapshot |
| [Deploy_Runbook.md](./Deploy_Runbook.md) | Production checks, restart rules, security baseline |
| [AI_Prompting_and_Usage_Analysis_2026-05-13.md](./AI_Prompting_and_Usage_Analysis_2026-05-13.md) | AI prompt/model usage analysis and QA rule for prompt/model changes |
| [Project_overview.md](./Project_overview.md) | Architecture overview and current LibreOffice/PyUNO design |
| [PRD.md](./PRD.md) | Historical product requirements |
| [Integration_report 02.md](./Integration_report%2002.md) | Current LibreOffice/PyUNO integration report |
| [Integration_report 01.md](./Integration_report%2001.md) | Historical LibreOffice Basic macro experiment |
| [todo.md](./todo.md) | Older task backlog |
| [Commands for testing.md](./Commands%20for%20testing.md) | Older testing command notes |

## Operational Notes

- Server/security operations live in `/ai/SECURITY`.
- `/ai/PORTS.yaml` is the server-wide port inventory.
- Production URL `https://gutendocx.unicloud.ca` is protected by Cloudflare Access.
- GutenDocx has no built-in login and should not be exposed anonymously without a separate app-auth/security project.
- Admin panel lives at `/admin` and is additionally gated by Cloudflare Access email; only `highmac@gmail.com` is allowed by default.
- AI model selection is admin-only; normal users cannot change the model, and backend requests are forced to the configured model.
- Runtime remains `root` for legacy compatibility until the owner explicitly starts a migration/hardening project.
- `Uploads/` and `output/` are operational data directories and may contain client files.
- Batch Apply uses background jobs persisted under `output/jobs/`; inspect `/jobs/<job_id>` state when diagnosing long-running batch processing.
- The primary Web UI upload control should remain a normal multi-file `.docx` picker for Windows compatibility. Use a separate clearly labeled control if folder upload is reintroduced.
- `config.yaml` is operational/user-editable state and may be changed by the platform during normal use. Inspect diffs before committing, and do not revert it automatically.
- Diagnostic audit events live in `output/audit_events.jsonl`; use them to reconstruct user actions/options/errors while treating them as sensitive operational metadata.
- Scheduled retention cleanup removes uploaded/generated files older than 15 days while preserving audit/cost logs and active job state.
- Official OpenAI prompt/model guide snapshots live in `Docs/OpenAI_Guides/`; refresh them before major prompt/model migration work.

## Future Planning Topics

- Refresh AI model choices and pricing, including newer OpenAI/ChatGPT models up to ChatGPT 5.5, then benchmark for the best quality/cost/latency tradeoff.
- Add an administrative AI cost dashboard based on the user's existing dashboard from another project.
- Evaluate a possible full UI redesign using the user's existing design from another project.
- Add admin/user roles with distinct permissions and dashboards after designing the app-auth/security changes.

## Historical / Local Assets

- `Model API Prices.xlsx` and `Техническое задание.xlsx` are historical/local reference files.
- `macro.bas` relates to the older Basic macro experiment and is not the preferred current architecture.
- Prefer `Integration_report 02.md` for the current LibreOffice/PyUNO design.
