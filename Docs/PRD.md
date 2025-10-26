# PRD: Word Style Normalizer & Layout Engine (Windows App, macOS-first Core)

**Status:** Draft v0.1 (2025‑10‑16)  
**Owner:** AI IA / Project: Word Documents Vitaly Mishin (Montreal)  
**Authors:** ChatGPT (GPT-5 Thinking), with user input  
**Target platform:** Windows (end users)  
**Primary dev environment:** macOS (core scripts), cross‑platform Python

---

## 1) Summary

We are building a **modular DOCX processing toolchain** that ingests Word documents (Project Gutenberg–style books and similar), performs a **Pre‑Scan**, **style normalization**, and **document layout** (title page, blank page with page numbering starting at 2, content from page 3+), and writes **DOCX → DOCX** (no PDF required).

The **core** is developed and tested on **macOS** using pure OpenXML manipulations (`python-docx` + `lxml`), ensuring platform neutrality. Final packaging and distribution are for **Windows**, producing a GUI app or CLI as needed. The approach intentionally **avoids MS Word automation** (COM/JXA) and **PDF conversion** to maintain portability and robustness.

---

## 2) Goals & Non‑Goals

### 2.1 Goals
- **Deterministic DOCX→DOCX pipeline** with no reliance on Word automation.
- **Pre-Scan** of styles and usage statistics.
- **Role mapping** (Title, Subtitle, Author, Body, Headings, Emphasis).
- **Style editing** via configuration (and later UI), applied at the **style definition** level (not per-paragraph hard formatting).
- **Section & pagination layout**:  
  1) Page 1 = title page (no page number).  
  2) Page 2 = blank, **page numbering starts at “2”**.  
  3) Page 3+ = content continues numbering.
- **Minimal footer control for page numbering** — insert `{ PAGE }` fields and allow
  basic customization such as font family, size, alignment, and spacing for the
  footer text containing the page number.
- **Normalization options**: style remap, remove direct formatting.
- **Config-driven** pipeline (YAML), with on-disk persistence and sane defaults embedded in code.
- **Batch-friendly** CLI with clear logs and reports.
- **Mac-first development**; zero code changes to run on Windows.
- **Global style remapping** — unify heterogeneous style names across documents by replacing them with canonical target styles defined in configuration, with a default fallback for any unmapped styles.
- **Automatic detection of Title/Subtitle/Author** — during Pre-Scan the app analyzes document structure (font size, position, capitalization) to suggest probable title, subtitle, and author lines. The detected values are presented to the user for confirmation or manual correction before processing.



### 2.2 Non‑Goals (for MVP)
- Advanced semantic restructuring (LLM‑based) — can be phase 2.  
- Full footnote/endnote editing; tracked changes resolving; equations.  
- Complex table design rewriting (beyond preserving styles).

---

## 3) Users & Use Cases

- **Primary user (Windows)**: Non-technical editor who wants consistent book formatting and pagination rules applied automatically to **one or many manuscripts at once**.  
  The editor can select a single file for scanning and preview, adjust style and layout settings,
  then apply the same configuration to an entire folder of DOCX files in one run.
- **Developer (macOS)**: Builds and tests the modular Python scripts; runs CLI; adjusts config; verifies outputs visually in Word for Mac, ensuring that batch processing works identically on both macOS and Windows.

**Use cases:**
1) Run **Pre‑Scan** to see all styles and their usage counts.
2) Map document styles to **roles**, set **style overrides** (font, size, spacing).
3) Apply **layout**: insert sections, set numbering from page 2, keep page 1 as title page and page 2 blank.
4) Normalize document (remove direct formatting, remap styles).
5) Batch process a folder of DOCX files with a shared config.
6) After scanning and configuring one sample file, run batch mode to apply the same configuration to a folder of multiple DOCX files, producing uniformly formatted outputs in the `out/` directory.


---

## 4) Functional Requirements

### 4.1 Ingestion (DOCX)
- Input: `.docx` file(s).  
- Output: `.docx` file(s) written to output directory.  
- The tool must not corrupt non‑text parts; tables/inline images must remain intact.

### 4.2 Pre‑Scan (Style Inventory)
- Enumerate **all styles** present (paragraph/character/table).  
- Count **usage** per style across paragraphs/runs/tables; collect **sample text**.  
- Detect **direct formatting** overrides at paragraph/run level.  
- Produce a **JSON/Markdown report** (optional).
- Detect probable Title, Subtitle, and Author blocks by analyzing text position,
  capitalization, and font differences in the first few paragraphs.
- Present detection results to the user (or log file in CLI) for review and confirmation.
- If confirmed, these values populate the `roles:` section of the configuration automatically.


### 4.3 Role Mapping
- Maintain a mapping from **roles** to **document styleIds**:  
  `Title, Subtitle, Author, Body (Normal), Heading1, Heading2, Heading3, Emphasis, …`
- Provide auto‑guesses (e.g., by common styleIds and position), but allow explicit override in config.

### 4.4 Style Editing (Style Definitions)
- Modify **style definitions** in `styles.xml` (not per‑paragraph), including:  
  - Font family, size (pt), bold/italic/underline.  
  - Paragraph alignment (left/center/right/justify).  
  - Spacing before/after (pt), line spacing (single/1.15/1.5/exact).  
  - Indentation (left/right/first line).  
  - Outline level for headings.  
- Preserve `basedOn` / `link` relations (e.g., Heading 1 ↔ Heading 1 Char).  
- **Remap document styles** — a core function that replaces or merges multiple
  source styles into canonical targets defined in configuration.  
  - For example: map all detected styles `["Body Text", "Text", "Paragraph"]` → `Normal`,  
    or `["Subhead", "Subheading"]` → `Heading 2`.  
  - Any styles not listed in the mapping are converted to a default fallback style
    (e.g., `Body` or `Normal`).
  - Remapping occurs before normalization, ensuring consistent structure across files.

### 4.5 Layout & Pagination (Sections)
Every document produced by the app must include:
1. A **generated title page (page 1)** — always present, built using the confirmed or manually
   specified Title, Subtitle, and Author information.
2. A **blank second page (page 2)** — always present, with page numbering starting at 2.
3. Content begins on **page 3** and continues numbering automatically.

Implement via OpenXML only:
- **Section A (page 1)**: `w:titlePg` = special first page; no page number in its header/footer.
- **Section break (next page)** to **Section B (page 2)**:  
  - `w:pgNumType @w:start="2"` (start numbering at 2).  
  - Insert `{ PAGE }` (and optionally `{ NUMPAGES }`) field in header/footer.  
  - Page 2 contains an empty paragraph (making it visually blank).  
  - Config option: show/hide page number on the blank page.
- **Section break (next page)** to **Section C (content)**: numbering continues (3+).  
- Preserve existing content and tables; don’t break them across unexpected sections.  
- If sections exist already, either integrate or rebuild based on config flag.

### 4.6 Normalization
- **Remap first, normalize second.** The remapping ensures all paragraphs use only the canonical style set defined in the configuration.
- Optionally remove **direct formatting** (runs/paragraph overrides) to keep styles authoritative.


### 4.7 Batch Processing
- Process individual files or entire directories.  
- Typical workflow: perform Pre-Scan and configuration on one representative file,
  then apply the same configuration to many documents in batch mode.
- Apply a single config (`config.yaml`) to multiple inputs; write outputs to a mirrored folder structure under `out/`.
- Preserve per-file logs and reports.


### 4.8 Reporting & Logs
- Human‑readable log per file (what changed, counts).  
- Machine‑readable JSON report for integration/testing.  
- Error diagnostics with actionable messages (missing styleId, malformed XML, etc.).

### 4.9 Configuration
- **Embedded defaults** in code.  
- On first run, write defaults to platform‑specific config path via `platformdirs`.  
- Load user config on subsequent runs; persist any UI changes back to the same YAML.  
- Support **per‑project override** by allowing a local `config.yaml` in the working directory.

### 4.10 CLI (MVP)
- `wordkit prescan <input.docx> --out report.json`  
- `wordkit apply-styles <input.docx> --config config.yaml --out out.docx [--remap yes] [--normalize yes]`  
- `wordkit layout <input.docx> --config config.yaml --out out.docx`  
- `wordkit all <input.docx> --config config.yaml --out out.docx`  
- Batch mode: `--input-dir`, `--glob`, `--out-dir`.

### 4.11 GUI (Phase 2, optional)
- Simple Windows UI (PySide6) to:  
  - Display style inventory, choose role mapping.  
  - Edit style overrides via dropdowns/spinboxes (font, size, spacing).  
  - Toggle layout options (start number at 2, show number on blank page).  
  - Run processing and show logs.  
- Auto‑save config changes.

---

## 5) Non‑Functional Requirements

### 5.1 Platform
- **Core** runs on macOS and Windows (Python 3.11+).  
- No MS Word automation required. Word is only a viewer/editor for humans.  
- No PDF generation.

### 5.2 Performance Targets
- Single 1–3 MB book: end‑to‑end in < 5s on modern hardware.  
- Batch of 100 files: completes without crashes; memory bounded (< 1 GB).

### 5.3 Reliability & Robustness
- Never corrupt binary parts (images), nor table structures.  
- Always produce a valid DOCX (zip consistency check).  
- Backup original files or write to a separate `out/` folder only.

### 5.4 Security & Privacy
- No outbound network calls.  
- Input files remain local.  
- Logs must not leak sensitive content unless explicitly enabled.

### 5.5 Internationalization
- Support documents with English/Russian styles and text.  
- Operate on styleId rather than localized display names.

---

## 6) Architecture & Modules

### 6.1 Tech Stack
- `python-docx` — document model access.  
- `lxml` — direct OpenXML manipulation (styles.xml, section props, headers/footers, fields).  
- `PyYAML` — config.  
- `platformdirs` — OS‑specific config path.  
- `rich`/`loguru` — optional pretty logs.

### 6.2 Module Responsibilities

- **core/loader.py**  
  Open/save DOCX, access package parts (`document.xml`, `styles.xml`, headers/footers, rels).

- **core/scan.py**  
  Build `StyleInventory` and attempt automatic detection of Title, Subtitle, and Author
  using visual heuristics (font size, capitalization, spacing).  
  Return suggested roles for confirmation before processing.

- **core/styles_xml.py**  
  Read/modify style definitions in `styles.xml`.  
  Apply overrides (font, size, spacing, alignment, outline level).  
  Preserve `basedOn` / `link` relations.  
  Implement **style remap** logic and support merging of redundant or legacy styles.

- **core/sections_xml.py**  
  Always ensure existence of **Title page (page 1)** and **blank page (page 2)**.  
  Prompt the user (via CLI or UI) if conflicting sections already exist before rebuilding layout.  
  Create sections A/B/C, set `w:titlePg`, `w:pgNumType @w:start="2"` for Section B,  
  add header/footer parts, insert `{ PAGE }` (and optional `{ NUMPAGES }`),  
  manage relationships, and insert correct section breaks without breaking content.

- **core/mapping.py**  
  Maintain and apply full style remapping rules based on configuration:  
  - Resolve role↔style mapping (e.g., Title, Heading1, Body).  
  - Execute global style remap pass: replace paragraph styles with canonical ones;  
    fallback any unlisted styles to default (Normal/Body).  
  - Provide auto-guess and validation utilities for Pre-Scan output.

- **core/normalize.py**  
  Remove direct formatting overrides, optionally per style or globally.

- **core/config.py**  
  Provide embedded defaults; read/write YAML at platform path;  
  merge with project-local config if present.

- **core/report.py**  
  Generate JSON/Markdown reports: style inventory, changes applied, warnings, and summary stats.

- **app/cli.py**  
  Parse command-line arguments and route to modules for  
  `prescan`, `apply-styles`, `layout`, and `all` commands.

### 6.3 Data Models

- **StyleInventory (JSON):**
  ```json
  {
    "paragraph": { "Heading1": { "name": "Heading 1", "count": 128, "has_direct_overrides": true, "samples": ["..."] } },
    "character": { },
    "table": { }
  }
  ```
- **DocumentHints:**
  ```json
  {
    "likely_roles": { "Title": ["Title", "Заголовок"], "Author": ["Author", "Автор"] },
    "headings_guess": ["Heading 1", "Heading 2"]
  }
  ```

### 6.4 Config Schema (YAML)

```yaml
layout:
  numbering:
    start_on_blank_page: 2         # numbering start
    show_on_blank_page: true       # show page number on page 2
  headers:
    show_numpages: false           # include NUMPAGES (e.g., “2 of 120”)

roles:
  Title: "Title"
  Subtitle: "Subtitle"
  Author: "Author"
  Body: "Normal"
  Heading1: "Heading 1"
  Heading2: "Heading 2"
  Emphasis: "Emphasis"

style_overrides:
  Title:
    font: "Times New Roman"
    size_pt: 24
    bold: true
    align: "center"
    spacing_after_pt: 12
  Body:
    font: "Times New Roman"
    size_pt: 12
    align: "justify"
    line_spacing: 1.15

remap_rules:
  Body:
    - "Body Text"
    - "Text"
    - "Paragraph"
  Heading1:
    - "Chapter"
    - "Main Heading"
  Heading2:
    - "Subhead"
    - "Subheading"
  default_fallback: "Body"     # any unlisted style will be converted to this

options:
  remap_styles: false
  normalize_direct_formatting: false
  backup_originals: false
```

### 6.5 Folder Structure

```
wordkit/
  core/
    loader.py
    scan.py
    styles_xml.py
    sections_xml.py
    mapping.py
    normalize.py
    config.py
    report.py
  app/
    cli.py
  tests/
    data/
      pg69789.docx
      pg69904.docx
    snapshots/
      styles_xml/
      sections_xml/
  out/                   # generated artifacts (git‑ignored)
  configs/
    default_config.yaml
README.md
```

---

## 7) Cross‑Platform Strategy & Pitfalls (macOS dev → Windows deploy)

### 7.1 Strategy
- Use only `python-docx` and `lxml` against OpenXML parts.  
- Avoid Word automation and PDF paths entirely.  
- Verify outputs visually in Word for Mac during dev; outputs must render identically (or acceptably) on Word for Windows.

### 7.2 Known Pitfalls & Mitigations
- **Fonts availability:**  
  - Times New Roman et al. may differ. Provide font fallback in style definitions or document guidance.  
  - Allow font names to be configured per environment if needed.
- **Locale & style display names:**  
  - Operate on `styleId` (stable), not localized names.  
- **Line ending / path separators:**  
  - Use `pathlib` and avoid hardcoded separators.  
- **File locking (Windows):**  
  - Write to new files in `out/`; don’t overwrite open files.  
- **Existing sections/headers/footers:**  
  - When detected, either “respect & extend” or “rebuild” based on `layout.reset` flag.  
- **DOC old format:**  
  - Not supported; require pre‑conversion to DOCX (user responsibility).

---

## 8) Testing & QA

### 8.1 Unit & Integration
- Unit tests per module (`scan`, `styles_xml`, `sections_xml`, etc.).  
- Integration tests run `all` on supplied fixtures.

### 8.2 Snapshot Testing
- Store **XML snapshots** (normalized) of `document.xml`, `styles.xml`, and header/footer parts to detect regressions.

### 8.3 Visual Checks
- Open outputs in Word on both macOS and Windows; verify:  
  - Page 1 has no number, shows Title/Subtitle/Author only.  
  - Page 2 is blank but shows page number “2” if configured.  
  - Page 3+ content continues numbering.  
  - Headings and body styles match configured overrides.

### 8.4 Performance
- Time runs and assert upper bounds for typical inputs.

---

## 9) Logging & Reporting

- Per‑file log: operations applied, counts, warnings.  
- Optional Markdown/HTML report for style inventory and deltas.  
- Verbosity flags (`--quiet`, `--verbose`).

---

## 10) Packaging & Distribution (Windows)

- Python 3.11+; dependencies pinned via `requirements.txt` / `poetry.lock`.  
- Build with **PyInstaller** or **Nuitka** (decision later; Nuitka yields smaller/faster binaries but longer builds).  
- Output: single‑folder or single‑file executable; include default `config.yaml` on first run.  
- Optional code signing (out of scope for MVP).

---

## 11) Backward/Forward Compatibility

- Config migrations: support versioned YAML (`config_version`) and migration routines.  
- Be tolerant to extra keys; warn on unknowns.

---

## 12) Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Word rendering differences Mac vs Win | Medium | Keep layout strictly via OpenXML; test both; avoid exotic features. |
| Fonts differ / missing | Medium | Configurable fonts; provide fallbacks; documentation. |
| Complex existing sections | Medium | `layout.reset` option; robust detection & rebuild. |
| Direct formatting persists | Low | Provide normalize toggle; report where present. |
| Corrupt DOCX on failure | Low | Always write to `out/`; validate zip; keep originals intact. |

---

## 13) Roadmap

### MVP (v0.1)
- CLI: `prescan`, `apply-styles`, `layout`, `all`.  
- YAML config with roles, style overrides, layout options.  
- Pure OpenXML sectioning & headers/footers with `{ PAGE }`.  
- Reports & logs; tests with sample books.

### v0.2
- Windows GUI (PySide6) with live style inventory and editors.  
- Batch UI; drag‑drop; progress bars.

### v0.3 (Optional Enhancements)
- TOC generation based on Heading levels.  
- Local/offline LLM for fuzzy role detection (e.g., classify ambiguous headings).  
- Template import (sync styles from `styles.dotx`).

---

## 14) Acceptance Criteria (MVP)

- Given an input DOCX, running `wordkit all` with defaults produces an output DOCX where:  
  - Page 1 has only Title/Subtitle/Author (as mapped), no page number.  
  - Page 2 is blank and shows page number “2” (if configured to show).  
  - Page 3+ contains the rest of the document, numbering continues from “3”.  
  - Body and headings reflect configured fonts, sizes, spacing, alignment.  
  - No images/tables are lost; DOCX validates and opens in Word (Mac/Windows).

---

## 15) Example CLI & Config

```bash
# Pre-scan a single file
wordkit prescan input/pg69904.docx --out reports/pg69904.json

# Apply style overrides and remap styles according to config
wordkit apply-styles input/pg69904.docx --config configs/project.yaml --out out/pg69904.styled.docx --remap yes --normalize yes

# Apply layout (sections + numbering from page 2)
wordkit layout out/pg69904.styled.docx --config configs/project.yaml --out out/pg69904.final.docx

# Apply styles and layout to all DOCX files in a folder
wordkit all --input-dir input/books --config configs/project.yaml --out-dir out/books

# Full pipeline for a single file
wordkit all input/pg69789.docx --config configs/project.yaml --out out/pg69789.final.docx
```

**Config snippet (`configs/project.yaml`):**
```yaml
layout:
  numbering:
    start_on_blank_page: 2
    show_on_blank_page: true
  headers:
    show_numpages: false

roles:
  Title: "Title"
  Subtitle: "Subtitle"
  Author: "Author"
  Body: "Normal"
  Heading1: "Heading 1"
  Heading2: "Heading 2"
  Emphasis: "Emphasis"

# Rules for unifying inconsistent style names across documents
remap_rules:
  Body:
    - "Body Text"
    - "Text"
    - "Paragraph"
  Heading1:
    - "CHAPTER"
    - "Heading Level 1"
  default_fallback: "Body"   # all unlisted styles will be converted to this style

style_overrides:
  Title: { font: "Times New Roman", size_pt: 24, bold: true, align: center, spacing_after_pt: 12 }
  Body:  { font: "Times New Roman", size_pt: 12, align: justify, line_spacing: 1.15 }

options:
  remap_styles: true
  normalize_direct_formatting: true
  backup_originals: true
```

---

## 16) Design Decisions
- **Automatic Title/Subtitle/Author detection:**  
  Implement heuristic detection during Pre-Scan based on visual cues
  (font size, capitalization, spacing).  
  Present suggested values to the user for confirmation or manual override
  before document processing.

- **Always generate a title page and a blank second page:**  
  Regardless of input structure, every output document must include:
  - Page 1 — Title page (auto-generated if missing, using confirmed Title/Author/Subtitle).
  - Page 2 — Blank, with page numbering starting at “2”.
  - Page 3+ — Main content.

- **Handling existing sections:**  
  When an input document already contains section breaks that conflict
  with the target layout, the app should **warn the user** and offer options:
  - [Rebuild layout] — recreate all sections from scratch (recommended).
  - [Keep existing] — skip layout rebuild and continue.
  The decision can be saved in the configuration for batch consistency.

---

## 17) Dependencies

- python-docx  
- lxml  
- PyYAML  
- platformdirs  
- (optional) rich / loguru for enhanced logging

---

## 18) Appendix: OpenXML Notes

- `w:sectPr` with `w:titlePg` for special first page.  
- Section B `w:pgNumType @w:start="2"`.  
- Header/footer parts linked via `w:headerReference` / `w:footerReference` (type=default/first/ even if needed).  
- `{ PAGE }` via `w:fldSimple w:instr=" PAGE "` is sufficient for Word to render current page.  
- Preserve `basedOn` and `link` in style definitions to keep Word behaviors consistent.
