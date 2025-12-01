# GutenDocx

GutenDocx is a modular DOCX normalization engine and WebApp built for a private publishing workflow.

The system processes Microsoft Word manuscripts (`.docx`), applies a consistent layout, normalizes styles, rebuilds page numbering, inserts a Table of Contents, and produces an aligned PDF using LibreOffice (Docker + PyUNO).  
This repository is shared **only** for portfolio and demonstration purposes.

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

## Legal Notice

This project was originally developed as a custom paid solution for a private client.

- The source code is published here **only** as part of the author's engineering portfolio and for backup.
- It is **not** open-source.
- **No rights** are granted to use, copy, modify, or redistribute this code or any part of it in any product or service without explicit written consent from the author.

If you are interested in similar functionality or in using parts of this project, please contact the author directly.
