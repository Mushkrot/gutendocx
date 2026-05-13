# GutenDocx

GutenDocx is a modular DOCX normalization engine and WebApp built for a private publishing workflow.

The system processes Microsoft Word manuscripts (`.docx`), applies a consistent layout, normalizes styles, rebuilds page numbering, inserts a Table of Contents, and produces an aligned PDF using LibreOffice (Docker + PyUNO).  
This repository is shared **only** for portfolio and demonstration purposes.

---

## Codex / Agent Context

When opening a new Codex session in this project, read:

1. `PROJECT_LOG.md`
2. `AGENTS.md`
3. `.cursor/SESSION_HANDOFF.md`
4. `Docs/Implementation_Status_2026-05-12.md`
5. `Docs/Deploy_Runbook.md`
6. `Docs/README.md`

These files are the active project memory. Older Windsurf/Claude-specific files are dormant and should not be updated unless explicitly requested.

---

## Key Features

### DOCX → DOCX Pipeline

- Style inventory and mapping to logical roles (Body, Heading1/2/3, Title, Subtitle, Author, Footer)
- Style overrides (font family, size, spacing, caps, alignment)
- Standardized layout pattern:
  - **Section A – Cover page**
  - **Section B – Optional blank page**
  - **Section C – Main body** with unified page numbering
- Footer normalization and page-number formatting
- TOC field insertion and update

### LibreOffice Integration

- Headless LibreOffice execution inside Docker
- PyUNO script to:
  - recalculate TOC and other fields,
  - export updated DOCX,
  - produce final PDF
- Custom Docker image with additional fonts and font-cache preloading

### Web Application

- FastAPI backend
- Static single-page Web UI (HTML/JS)
- Upload one or many DOCX files
- Interactive configuration of:
  - cover styles,
  - body text styles,
  - headings,
  - footer / page-number style
- YAML configuration (`config.yaml`) synchronized with the UI
- Download results as DOCX or ZIP bundle (DOCX + PDF)

---

## Architecture Overview

```text
gutendocx/
  core/                     # OpenXML logic: styles, layout, TOC, LO orchestration
  web/
    server.py               # FastAPI backend
    static/index.html       # Single-page web app
  scripts/
    lo_convert.py           # PyUNO script executed inside LibreOffice container
  docker/libreoffice/       # Custom LibreOffice image with fonts
  configs/
    default_config.yaml
    config.yaml
  Docs/                     # PRD, integration reports, developer documentation
  fonts/                    # User-provided fonts packaged for LO
  output/                   # Generated output (git-ignored)
```

---

## Running Locally (development)

> These commands are indicative; adjust to your environment.

1. Create and activate a virtualenv, install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the web server:

```bash
uvicorn gutendocx.web.server:app --reload --port 8080
```

3. Open the web UI in a browser:

```text
http://localhost:8080
```

LibreOffice Docker image and fonts configuration are described in the docs under `Docs/`.

---

## Production Operations

Server-wide operations for this app are tracked in `/ai/SECURITY`.

Current production model as of 2026-05-12:

- Public URL: `https://gutendocx.unicloud.ca`.
- Public ingress: Cloudflare Tunnel `mainserver` routes to `http://localhost:8000`.
- Access control: Cloudflare Access protects the public hostname. This is intentional: GutenDocx is for one client plus the developer, not for public search or anonymous use.
- Runtime service: `gutendocx.service`.
- Runtime bind: `127.0.0.1:8000`; do not expose the FastAPI server directly on `0.0.0.0`.
- Runtime user: currently `root`. This is a known legacy constraint on the server and should not be changed without a separate migration project.
- Generated files: `Uploads/` and `output/` can contain client documents and should be treated as sensitive operational data.

Production checks:

```bash
systemctl is-active gutendocx cloudflared server-firewall tailscaled ssh
ss -lntup | rg ':8000'
curl -fsS http://127.0.0.1:8000/health
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' https://gutendocx.unicloud.ca/
```

Expected behavior:

- The app listens only on `127.0.0.1:8000`.
- Local `/health` returns OK.
- Public requests without a valid Access session redirect to Cloudflare Access login.

Do not use `dev.sh` as a production launcher on the server. It is a development helper and runs with `--reload --host 0.0.0.0`.

---

## Legal Notice

This project was originally developed as a custom paid solution for a private client.

- The source code is published here **only** as part of the author's engineering portfolio and for backup.
- It is **not** open-source.
- **No rights** are granted to use, copy, modify, or redistribute this code or any part of it in any product or service without explicit written consent from the author.

If you are interested in similar functionality or in using parts of this project, please contact the author directly.
