from __future__ import annotations

from typing import Any, Dict, List
import os
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .loader import Loader
from .cover import _ensure_output_path


def find_toc_paragraph_indices(doc: Document) -> List[int]:
    indices: List[int] = []
    for i, p in enumerate(doc.paragraphs):
        try:
            style = getattr(getattr(p, "style", None), "name", None)
        except Exception:
            style = None
        xml = p._p.xml
        style_s = str(style or "").lower()
        if style_s.startswith("toc") or " TOC " in xml or "TOC \\o" in xml or "TOC\\o" in xml:
            indices.append(i)
    return indices


def remove_existing_toc(doc: Document) -> Dict[str, Any]:
    idxs = find_toc_paragraph_indices(doc)
    for i in reversed(idxs):
        try:
            p = doc.paragraphs[i]
            p._element.getparent().remove(p._element)
        except Exception:
            continue
    return {"removed": len(idxs), "indices": idxs}


def insert_word_toc(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    toc_cfg = (config or {}).get("toc", {}) or {}
    levels = str(toc_cfg.get("levels") or "1-2")
    field_code = f" TOC \\o \"{levels}\" \\h \\z \\u "

    p = doc.add_paragraph()

    # Begin field
    r_begin = p.add_run()
    fld_char_begin = OxmlElement("w:fldChar")
    fld_char_begin.set(qn("w:fldCharType"), "begin")
    r_begin._r.append(fld_char_begin)

    # Field instructions
    r_instr = p.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = field_code
    r_instr._r.append(instr)

    # Separate
    r_sep = p.add_run()
    fld_char_sep = OxmlElement("w:fldChar")
    fld_char_sep.set(qn("w:fldCharType"), "separate")
    r_sep._r.append(fld_char_sep)

    # End
    r_end = p.add_run()
    fld_char_end = OxmlElement("w:fldChar")
    fld_char_end.set(qn("w:fldCharType"), "end")
    r_end._r.append(fld_char_end)

    return {"inserted_at_end": True, "levels": levels}


def _count_existing_headings(doc: Document) -> int:
    """Count paragraphs that already use Heading styles (Heading 1, Heading 2, ...)."""

    count = 0
    for p in getattr(doc, "paragraphs", []) or []:
        try:
            st = getattr(p, "style", None)
            name = getattr(st, "name", None) if st is not None else None
        except Exception:
            name = None
        if isinstance(name, str) and name.startswith("Heading "):
            count += 1
    return count


_CHAPTER_MARKERS = {
    "CHAPTER": "en",
    "ГЛАВА": "ru",
    "KAPITEL": "de",
    "CHAPITRE": "fr",
}


_CHAPTER_RE = re.compile(
    r"^(CHAPTER|ГЛАВА|KAPITEL|CHAPITRE)\s+([0-9IVXLCDM]+)\b",
    re.IGNORECASE,
)


def _apply_heuristic_headings(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    """Assign Heading styles based on chapter-like patterns in multiple languages.

    Supported markers (case-insensitive):
      - EN: "Chapter N"
      - RU: "Глава N"
      - DE: "Kapitel N"
      - FR: "Chapitre N"

    Only paragraphs that do NOT already use a Heading style are modified.
    """

    try:
        h1 = doc.styles["Heading 1"]
    except Exception:
        h1 = None
    try:
        h2 = doc.styles["Heading 2"]
    except Exception:
        h2 = None

    if h1 is None and h2 is None:
        return {
            "assigned": [],
            "existing_headings_before": _count_existing_headings(doc),
            "skipped": "no_heading_styles",
        }

    assigned: List[Dict[str, Any]] = []
    existing_before = 0

    for idx, p in enumerate(getattr(doc, "paragraphs", []) or []):
        try:
            st = getattr(p, "style", None)
            name = getattr(st, "name", None) if st is not None else None
        except Exception:
            name = None
        if isinstance(name, str) and name.startswith("Heading "):
            existing_before += 1
            continue

        text = (getattr(p, "text", "") or "").strip()
        if not text:
            continue

        m = _CHAPTER_RE.match(text.strip())
        if not m:
            # Try matching against upper-cased text to be more robust for non-ASCII.
            m = _CHAPTER_RE.match(text.strip().upper())
            if not m:
                continue

        marker_raw = m.group(1) or ""
        marker = marker_raw.upper()
        number = m.group(2) or ""
        lang = _CHAPTER_MARKERS.get(marker)

        target_style = h1 or h2
        try:
            p.style = target_style
        except Exception:
            continue

        assigned.append(
            {
                "index": idx,
                "text": text[:120],
                "style": getattr(target_style, "name", ""),
                "marker": marker_raw,
                "number": number,
                "language": lang,
            }
        )

    return {
        "assigned": assigned,
        "existing_headings_before": existing_before,
    }


def build_toc(input_path: str, config: Dict[str, Any], mode: str = "structured") -> Dict[str, Any]:
    """High-level API to (re)build TOC for a DOCX file.

    Current implementation only supports the "structured" mode, which assumes
    that Heading styles are already correctly applied in the document and
    simply inserts a Word TOC field that will be populated by Word/LibreOffice.
    """

    loader = Loader()
    doc = loader.open(input_path)

    normalized_mode = (mode or "structured").strip().lower()
    if normalized_mode not in {"structured", "auto", "heuristic"}:
        normalized_mode = "structured"

    existing_before = _count_existing_headings(doc)
    heuristic_info: Dict[str, Any] | None = None

    if normalized_mode == "heuristic":
        heuristic_info = _apply_heuristic_headings(doc, config)
    elif normalized_mode == "auto":
        toc_cfg = (config or {}).get("toc", {}) or {}
        min_existing = int(toc_cfg.get("min_existing_headings", 5))
        if existing_before < min_existing:
            heuristic_info = _apply_heuristic_headings(doc, config)
        else:
            heuristic_info = {
                "assigned": [],
                "existing_headings_before": existing_before,
                "skipped": "enough_existing_headings",
                "threshold": min_existing,
            }

    removed = remove_existing_toc(doc)
    inserted = insert_word_toc(doc, config)

    out_cfg = (config or {}).get("output", {}) or {}
    out_dir = out_cfg.get("dir", "output")

    os.makedirs(out_dir, exist_ok=True)
    versioning = bool(out_cfg.get("versioning", False))
    output_path = _ensure_output_path(out_dir, input_path, versioning=versioning)
    saved_path = loader.save(doc, output_path)

    return {
        "toc": {
            "mode": normalized_mode,
            "existing_headings_before": existing_before,
            "removed": removed,
            "inserted": inserted,
            "heuristic": heuristic_info,
        },
        "output_path": saved_path,
    }
