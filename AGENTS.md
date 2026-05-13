# Agent Workflow for `/ai/gutendocx`

## Active Agent Mode

- Current default agent: **Codex**.
- This is an older standalone project. Expect documentation and project structure to be simpler than newer `/ai` projects.
- Keep the project compatible with future AI agents, but do not maintain dormant-agent private memory mirrors unless the user explicitly asks.
- Source-of-truth project memory lives in:
  - `PROJECT_LOG.md`
  - `AGENTS.md`
  - `.cursor/SESSION_HANDOFF.md`
  - `Docs/Implementation_Status_2026-05-12.md`
  - `Docs/Deploy_Runbook.md`
  - `Docs/README.md`

## Cold Start Order

At the start of a new Codex chat with no reliable prior context, read:

1. `PROJECT_LOG.md`
2. `AGENTS.md`
3. `.cursor/SESSION_HANDOFF.md`
4. `Docs/Implementation_Status_2026-05-12.md`
5. `Docs/Deploy_Runbook.md`
6. `Docs/README.md`

Read only current/resume sections first. Open deeper historical docs only when needed.

## Instruction Scope

- Read-only requests such as **look / review / check / verify / analyze / explain** must not change files, services, Cloudflare, or server state.
- Implementation requests such as **implement / add / fix / change / update / do it** allow scoped edits, but keep service changes small and reversible.
- If the user asks to work step by step or says not to continue without confirmation, keep that mode active for the rest of the thread.
- Screenshots, quoted requirements, or numbered lists are context, not permission to execute unrelated changes.

## Project Scope

This repo owns the GutenDocx application:

- FastAPI app code under `gutendocx/`.
- Static web UI under `gutendocx/web/static/`.
- Project configuration in `config.yaml`.
- Local development scripts and project documentation.
- LibreOffice/DOCX pipeline code and Docker image build files.

Server-wide operations are owned by `/ai/SECURITY`:

- SSH, firewall, Tailscale, Docker exposure, Cloudflare Tunnel, Cloudflare Access/DNS/WAF, monitoring, alerting, backups, and `/ai/PORTS.yaml`.
- If an app change needs a new public hostname, port, tunnel route, service bind, Cloudflare Access/WAF change, or monitoring rule, update `/ai/SECURITY` as part of the operational work.

## Current Production Model

- Public URL: `https://gutendocx.unicloud.ca`.
- Public ingress: Cloudflare Tunnel `mainserver`.
- Access control: Cloudflare Access protects the site. This is intentional because the app is for one client plus the developer, not for search indexing or public discovery.
- Local service: `gutendocx.service`.
- Bind: `127.0.0.1:8000`; do not expose the FastAPI app directly on `0.0.0.0`.
- Runtime user: currently `root`. This is a known legacy constraint shared with other older server projects. Do not migrate to a non-root user unless the user explicitly starts that project.

## Safety Rules

1. Do not remove or bypass Cloudflare Access for `gutendocx.unicloud.ca` without explicit approval.
2. Do not change the production bind from `127.0.0.1:8000` to `0.0.0.0`.
3. Do not use `dev.sh` as a production launcher on the server; it runs `--reload --host 0.0.0.0`.
4. Do not print or commit secrets from `.env*`, `/opt/secure-configs/.env`, Cloudflare credentials, or other credential files.
5. Be careful with `Uploads/` and `output/`; they may contain client documents and generated files.
6. Before restarting production, inspect `systemctl status gutendocx`, confirm the app is localhost-bound, and verify locally with `curl http://127.0.0.1:8000/health`.
7. The app has no built-in login. Its security boundary depends on Cloudflare Access plus localhost binding and the host firewall.

## Risky Change QA Rule

For important behavior changes that may improve one workflow but risk breaking or degrading another workflow, use a cautious before/after QA loop:

1. Commit the current working state first, excluding incidental runtime `config.yaml` changes.
2. Define several concrete tests that directly cover the intended change and key existing behavior that must not regress.
3. Run the tests before the change and record the baseline result.
4. Make the smallest scoped change.
5. Run the same tests again and compare against the baseline.
6. Keep the change only if it improves or preserves the target behavior without breaking existing behavior or dependencies.
7. Revert or redesign the change if the comparison shows quality loss, new risk, or unclear benefit.

For AI prompts/model behavior, do not change production prompts or defaults without first discussing the proposed change and the before/after test plan with the user.

## Documentation Rules

After non-trivial project work, update the relevant files:

- `PROJECT_LOG.md`: lean current state, what changed, what is next.
- `.cursor/SESSION_HANDOFF.md`: concise next-chat handoff.
- `Docs/Implementation_Status_2026-05-12.md`: current implementation snapshot when app behavior, security model, or production state changes.
- `Docs/Deploy_Runbook.md`: production/restart/check changes.
- `/ai/SECURITY` and `/ai/PORTS.yaml`: only when server exposure, Cloudflare Access/Tunnel/DNS/WAF, firewall, monitoring, service bind, or port inventory changes.

Do not update `.windsurf/`, Claude memory, or other dormant-agent mirrors unless the user explicitly asks.

## Runtime Configuration State

`config.yaml` is intentionally edited by the running platform during normal use when users learn/apply/update settings through the Web UI.

- A local `config.yaml` diff is not automatically a problem and does not necessarily mean a developer changed code.
- Before committing, inspect whether the `config.yaml` change is part of the requested work.
- Do not include incidental user/runtime `config.yaml` changes in technical commits unless they are explicitly intended.
- Do not automatically revert `config.yaml`; it may contain current user preferences.

## Verification Commands

```bash
systemctl is-active gutendocx cloudflared server-firewall tailscaled ssh
ss -lntup | rg ':8000'
curl -fsS http://127.0.0.1:8000/health
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://gutendocx.unicloud.ca/
```

Expected:

- `gutendocx` and infrastructure services are active.
- Port `8000` is bound to `127.0.0.1`.
- Local `/health` returns OK.
- Public URL redirects to Cloudflare Access login unless the request has a valid Access session.
