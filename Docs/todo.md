# TODO — Word Style Normalizer & Layout Engine (MVP v0.1 → v0.3)

_This list is derived from the PRD “Word Style Normalizer & Layout Engine (Windows App, macOS‑first Core)” (Draft v0.1, 2025‑10‑16). Tasks are grouped by feature. Each task shows **Dependencies** (IDs) and **AI difficulty** (for AI-assisted implementation: easy/medium/hard)._

---

## Legend

- **ID format:** `AREA-N` (e.g., `ING-1` for Ingestion task 1).
- **AI difficulty:** estimation of complexity for AI-assisted coding or design.
- **Phase:** MVP unless noted otherwise (v0.2 GUI, v0.3 Enhancements).

---

## 4.1 Ingestion (DOCX) — ID prefix `ING`

- [ ] **ING-1** Load/save DOCX with safe temp paths; never overwrite source. **Dependencies:** none. **AI:** easy
- [ ] **ING-2** Preserve non-text parts (images, tables) during round‑trip. **Dependencies:** ING-1. **AI:** medium
- [ ] **ING-3** Zip consistency + validity check on output. **Dependencies:** ING-1. **AI:** easy
- [ ] **ING-4** Mirror source folder structure to `out/` in batch mode. **Dependencies:** ING-1. **AI:** easy

---

## 4.2 Pre‑Scan (Style Inventory) — `SCAN`

- [ ] **SCAN-1** Enumerate paragraph/character/table styles and counts. **Dependencies:** ING-1. **AI:** easy
- [ ] **SCAN-2** Detect direct formatting overrides (para/run level). **Dependencies:** SCAN-1. **AI:** medium
- [ ] **SCAN-3** Collect sample text per style (first ~3 snippets). **Dependencies:** SCAN-1. **AI:** easy
- [ ] **SCAN-4** Heuristic detection of Title/Subtitle/Author in first page region (font size, capitalization, spacing, position). **Dependencies:** SCAN-1. **AI:** medium
- [ ] **SCAN-5** Emit JSON + optional Markdown report. **Dependencies:** SCAN-1. **AI:** easy
- [ ] **SCAN-6** CLI confirmation path to accept/override detected roles. **Dependencies:** CLI-1, SCAN-4. **AI:** easy

---

## 4.3 Role Mapping — `MAP`

- [ ] **MAP-1** Maintain mapping roles→styleIds; validate style existence. **Dependencies:** SCAN-1, CFG-1. **AI:** easy
- [ ] **MAP-2** Auto‑guess mapping by common styleIds + positions. **Dependencies:** SCAN-1. **AI:** medium
- [ ] **MAP-3** Fallback for unmapped styles to default (e.g., Body/Normal). **Dependencies:** MAP-1. **AI:** easy

---

## 4.4 Style Editing (definitions, not hard formatting) — `STY`

- [ ] **STY-1** Read/modify `styles.xml` (fonts, size, spacing, alignment). **Dependencies:** ING-1. **AI:** medium
- [ ] **STY-2** Preserve `basedOn` / `link` relations (Heading ↔ Char). **Dependencies:** STY-1. **AI:** medium
- [ ] **STY-3** Apply config-driven overrides by role. **Dependencies:** MAP-1, CFG-1, STY-1. **AI:** medium
- [ ] **STY-4** Global style remap pass (merge legacy styles into canonical). **Dependencies:** MAP-1/2/3. **AI:** medium

---

## 4.5 Layout & Pagination (Sections) — `LAY`

- [ ] **LAY-1** Create Section A (Title page) with `w:titlePg` (no page number). **Dependencies:** ING-1. **AI:** medium
- [ ] **LAY-2** Create Section B (blank page, numbering start at 2 via `w:pgNumType @w:start="2"`). **Dependencies:** LAY-1. **AI:** medium
- [ ] **LAY-3** Insert `{ PAGE }` field in header/footer; opt `{ NUMPAGES }`. **Dependencies:** LAY-2. **AI:** medium
- [ ] **LAY-4** Create Section C (content); continue numbering (3+). **Dependencies:** LAY-2. **AI:** medium
- [ ] **LAY-5** Safely integrate or rebuild if conflicting sections exist (config flag). **Dependencies:** CFG-2, ING-1. **AI:** hard
- [ ] **LAY-6** Option to show/hide page number on blank page (B). **Dependencies:** LAY-3, CFG-2. **AI:** easy
- [ ] **LAY-7** Title page generator from confirmed Title/Subtitle/Author. **Dependencies:** SCAN-6, CFG-2. **AI:** medium

---

## 4.6 Normalization — `NORM`

- [ ] **NORM-1** Remove direct formatting overrides post‑remap (runs/paras). **Dependencies:** STY-4. **AI:** medium
- [ ] **NORM-2** Toggle per style or global via config. **Dependencies:** CFG-2. **AI:** easy

---

## 4.7 Batch Processing — `BATCH`

- [ ] **BATCH-1** Process `--input-dir` with `--glob` and `--out-dir`. **Dependencies:** CLI-1, ING-4. **AI:** easy
- [ ] **BATCH-2** Per-file logs & reports with mirrored structure. **Dependencies:** LOG-1, REP-1. **AI:** easy

---

## 4.8 Reporting & Logs — `REP` / `LOG`

- [ ] **REP-1** JSON report: inventory, changes, warnings, stats. **Dependencies:** SCAN-1/2/5, MAP-1, STY-3/4, NORM-1, LAY-1..4. **AI:** medium
- [ ] **LOG-1** Human-readable log per file; verbosity flags. **Dependencies:** CLI-1. **AI:** easy
- [ ] **LOG-2** Redact sensitive content unless explicitly enabled. **Dependencies:** CFG-2. **AI:** easy

---

## 4.9 Configuration — `CFG`

- [ ] **CFG-1** Embedded defaults; write to OS config path (`platformdirs`). **Dependencies:** none. **AI:** easy
- [ ] **CFG-2** Load/merge with project-local `config.yaml`; persist UI/CLI changes. **Dependencies:** CFG-1. **AI:** medium
- [ ] **CFG-3** Schema validation; warn on unknown keys; support migrations. **Dependencies:** CFG-2. **AI:** medium

---

## 4.10 CLI (MVP) — `CLI`

- [ ] **CLI-1** Implement `prescan`, `apply-styles`, `layout`, `all`. **Dependencies:** SCAN-1..5, STY-1..4, LAY-1..4, NORM-1. **AI:** medium
- [ ] **CLI-2** Batch flags: `--input-dir`, `--glob`, `--out-dir`. **Dependencies:** BATCH-1. **AI:** easy
- [ ] **CLI-3** User prompts for conflicts (layout reset vs keep). **Dependencies:** LAY-5. **AI:** easy

---

## 4.11 GUI (Phase 2, optional) — `GUI`

- [ ] **GUI-1** PySide6 shell: file picker + style inventory table. **Dependencies:** SCAN-1/5, CFG-1/2. **AI:** medium
- [ ] **GUI-2** Role mapping editor + preview. **Dependencies:** MAP-1/2, STY-3. **AI:** medium
- [ ] **GUI-3** Style overrides editors (font/size/spacing). **Dependencies:** STY-1/3. **AI:** medium
- [ ] **GUI-4** Layout toggles (start at 2, show on blank page). **Dependencies:** LAY-2/3/6. **AI:** easy
- [ ] **GUI-5** Batch run with progress. **Dependencies:** BATCH-1/2. **AI:** medium

---

## 5.x / 7.x Cross‑Platform & Non‑Functional — `PLAT` / `NFR`

- [ ] **PLAT-1** Path handling via `pathlib`; no hardcoded separators. **Dependencies:** ING-1. **AI:** easy
- [ ] **PLAT-2** Document locale safety: operate on `styleId` not display names. **Dependencies:** MAP-1. **AI:** easy
- [ ] **PLAT-3** Windows file locking: always write to `out/` new names. **Dependencies:** ING-1. **AI:** easy
- [ ] **NFR-1** Performance target: 1–3 MB book < 5s. Add timers. **Dependencies:** CLI-1. **AI:** easy
- [ ] **NFR-2** Memory bound < 1 GB for batch of 100. **Dependencies:** BATCH-1. **AI:** medium
- [ ] **NFR-3** Security: zero network calls; ensure no outbound. **Dependencies:** none. **AI:** easy

---

## 6.2 Architecture & Modules — `CORE`

- [ ] **CORE-LOADER** `core/loader.py`: open/save DOCX; access parts & rels. **Dependencies:** ING-1. **AI:** medium
- [ ] **CORE-SCAN** `core/scan.py`: inventory + role detection heuristics. **Dependencies:** CORE-LOADER. **AI:** medium
- [ ] **CORE-STY** `core/styles_xml.py`: overrides + remap; preserve relations. **Dependencies:** CORE-LOADER. **AI:** hard
- [ ] **CORE-SECT** `core/sections_xml.py`: sections A/B/C; headers/footers; fields. **Dependencies:** CORE-LOADER. **AI:** hard
- [ ] **CORE-MAP** `core/mapping.py`: roles ↔ styleIds; global remap pass. **Dependencies:** CORE-SCAN, CORE-STY. **AI:** medium
- [ ] **CORE-NORM** `core/normalize.py`: remove direct formatting. **Dependencies:** CORE-STY. **AI:** easy
- [ ] **CORE-CONFIG** `core/config.py`: defaults, merge, persistence. **Dependencies:** none. **AI:** medium
- [ ] **CORE-REPORT** `core/report.py`: JSON/Markdown reports. **Dependencies:** CORE-SCAN/MAP/STY/NORM/SECT. **AI:** medium
- [ ] **APP-CLI** `app/cli.py`: wire commands + flags. **Dependencies:** all CORE modules. **AI:** medium

---

## 8) Testing & QA — `TEST`

- [ ] **TEST-1** Unit tests per module (scan/styles/sections/etc.). **Dependencies:** CORE modules. **AI:** medium
- [ ] **TEST-2** Integration tests: `gutendocx all` over fixtures. **Dependencies:** APP-CLI. **AI:** medium
- [ ] **TEST-3** Snapshot XML tests (document, styles, headers/footers). **Dependencies:** CORE-STY/SECT. **AI:** medium
- [ ] **TEST-4** Visual checks plan for Mac/Windows (manual checklist). **Dependencies:** LAY-1..4. **AI:** easy
- [ ] **TEST-5** Performance assertions (time upper bounds). **Dependencies:** NFR-1/2. **AI:** easy

---

## 9) Logging & Reporting (privacy) — `PRIV`

- [ ] **PRIV-1** Ensure logs avoid content leakage by default. **Dependencies:** LOG-1. **AI:** easy
- [ ] **PRIV-2** Redaction toggles in config with clear warnings. **Dependencies:** CFG-2. **AI:** easy

---

## 10) Packaging & Distribution (Windows) — `PKG`

- [ ] **PKG-1** Pin dependencies; `requirements.txt` / `poetry.lock`. **Dependencies:** none. **AI:** easy
- [ ] **PKG-2** Build via PyInstaller/Nuitka (choose, document tradeoffs). **Dependencies:** APP-CLI. **AI:** medium
- [ ] **PKG-3** First-run default `config.yaml` writer. **Dependencies:** CFG-1. **AI:** easy
- [ ] **PKG-4** Optional code signing (out of scope MVP) — placeholder doc. **Dependencies:** none. **AI:** easy

---

## 12) Risks & Mitigations — `RISK`

- [ ] **RISK-1** Font availability differences → config fallbacks. **Dependencies:** STY-3, CFG-2. **AI:** easy
- [ ] **RISK-2** Existing complex sections → robust detect/rebuild (LAY-5). **Dependencies:** LAY-5. **AI:** hard
- [ ] **RISK-3** Direct formatting persistence → normalization pass. **Dependencies:** NORM-1. **AI:** easy

---

## 13) Roadmap Gates — `GATE`

- [ ] **GATE-MVP** Ship CLI + core pipeline; passes Acceptance Criteria. **Dependencies:** CLI-1, CORE-*, LAY-*, STY-*, NORM-*, REP-1. **AI:** medium
- [ ] **GATE-v0.2** Windows GUI minimal (inventory, mapping, run). **Dependencies:** GUI-*. **AI:** medium
- [ ] **GATE-v0.3** Optional enhancements (TOC; LLM aid for fuzzy roles). **Dependencies:** ENH-1/2. **AI:** medium

---

## 14) Acceptance Criteria Verification — `AC`

- [ ] **AC-1** Title page has no page number; shows Title/Subtitle/Author only. **Dependencies:** LAY-1, LAY-7. **AI:** easy
- [ ] **AC-2** Page 2 blank; page number “2” shown if configured. **Dependencies:** LAY-2/3/6. **AI:** easy
- [ ] **AC-3** Page 3+ continue numbering; content intact incl. tables/images. **Dependencies:** LAY-4, ING-2. **AI:** medium
- [ ] **AC-4** Body/headings match configured fonts/sizes/spacing. **Dependencies:** STY-3/4. **AI:** medium
- [ ] **AC-5** DOCX opens in Word (Mac/Win) without errors. **Dependencies:** ING-3, TEST-4. **AI:** easy

---

## 15) Enhancements (v0.3, optional) — `ENH`

- [ ] **ENH-1** TOC generation from Heading levels. **Dependencies:** STY-1/3. **AI:** medium
- [ ] **ENH-2** Local/offline LLM to improve role detection for ambiguous cases. **Dependencies:** SCAN-4, CFG-2. **AI:** hard
- [ ] **ENH-3** Template import from `.dotx` (style sync). **Dependencies:** STY-1/3. **AI:** medium

---

## Quick Dependency Ordering (High‑level)

1. ING → CORE-LOADER → SCAN/MAP/STY → SECT (LAY) → NORM → REPORT/LOG → CLI → TEST → PKG
2. CFG threads into SCAN/MAP/STY/LAY/NORM/LOG early.
3. Batch mode (BATCH) sits atop CLI + ING.
4. GUI waits for stable CORE + CLI (v0.2).
