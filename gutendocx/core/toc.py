from __future__ import annotations

from typing import Any, Dict, List, Set
import os
import re

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .loader import Loader
from .cover import _ensure_output_path
from .layout import ensure_body_section_with_numbering
from .docx_format import (
    W_NS,
    apply_text_style_to_run_element,
    apply_text_style_to_style,
    has_text_style,
    run_has_visible_text,
    style_name_by_id,
    text_style_from_override,
)


def _w_tag(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def _paragraph_style_id_xml(p_el) -> str:
    try:
        p_style = p_el.find(f"./{_w_tag('pPr')}/{_w_tag('pStyle')}")
        if p_style is not None:
            return str(p_style.get(_w_tag("val")) or "")
    except Exception:
        pass
    return ""


def _toc_level_from_name(value: str | None) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    m = re.search(r"\btoc\s*([1-9])\b", text)
    if m:
        return int(m.group(1))
    if text in {"11", "toc1"}:
        return 1
    if text in {"21", "toc2"}:
        return 2
    if text in {"31", "toc3"}:
        return 3
    return None


def _is_toc_paragraph_element(p_el, style_names: Dict[str, str]) -> bool:
    sid = _paragraph_style_id_xml(p_el)
    sname = style_names.get(sid, "")
    if _toc_level_from_name(sid) or _toc_level_from_name(sname):
        return True
    if str(sname or "").lower().startswith("toc"):
        return True
    try:
        instr = " ".join(t for t in p_el.xpath(".//w:instrText/text()") if t)
    except Exception:
        instr = ""
    upper = instr.upper()
    return "TOC" in upper or "PAGEREF" in upper


def _toc_level_for_paragraph(p_el, style_names: Dict[str, str]) -> int:
    sid = _paragraph_style_id_xml(p_el)
    return _toc_level_from_name(style_names.get(sid)) or _toc_level_from_name(sid) or 1


def find_toc_paragraph_indices(doc: Document) -> List[int]:
    indices: List[int] = []
    style_names = style_name_by_id(doc)
    try:
        paragraphs = list(doc._element.body.xpath(".//w:p"))
    except Exception:
        paragraphs = []
    for i, p_el in enumerate(paragraphs):
        if _is_toc_paragraph_element(p_el, style_names):
            indices.append(i)
    return indices


def _nearest_toc_removal_element(p_el):
    cur = p_el
    selected = p_el
    while cur is not None:
        parent = cur.getparent()
        if parent is not None and parent.tag == _w_tag("body"):
            return selected
        if cur.tag == _w_tag("sdt"):
            selected = cur
        cur = parent
    return p_el


def remove_existing_toc(doc: Document) -> Dict[str, Any]:
    style_names = style_name_by_id(doc)
    try:
        paragraphs = list(doc._element.body.xpath(".//w:p"))
    except Exception:
        paragraphs = []

    idxs: List[int] = []
    removal_elements: List[Any] = []
    seen: Set[int] = set()
    for i, p_el in enumerate(paragraphs):
        if not _is_toc_paragraph_element(p_el, style_names):
            continue
        idxs.append(i)
        remove_el = _nearest_toc_removal_element(p_el)
        if id(remove_el) in seen:
            continue
        seen.add(id(remove_el))
        removal_elements.append(remove_el)

    for element in reversed(removal_elements):
        try:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
        except Exception:
            continue
    return {"removed": len(removal_elements), "paragraphs_removed": len(idxs), "indices": idxs}


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


def resolve_toc_style_overrides(config: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    so = (config or {}).get("style_overrides", {}) or {}
    toc_ov = so.get("TOC", {}) or {}
    mode = str(toc_ov.get("mode") or "same_body").strip().lower()
    if mode not in {"same_body", "same_heading", "custom"}:
        mode = "same_body"

    if mode == "custom":
        custom = text_style_from_override(toc_ov)
        return {1: custom, 2: dict(custom), 3: dict(custom)}

    if mode == "same_heading":
        h1 = text_style_from_override(so.get("Headings", {}) or {})
        h2 = text_style_from_override(so.get("Heading2", {}) or {}) or h1
        h3 = text_style_from_override(so.get("Heading3", {}) or {}) or h2 or h1
        body = text_style_from_override(so.get("Body", {}) or {})
        return {
            1: h1 or body,
            2: h2 or body,
            3: h3 or body,
        }

    body = text_style_from_override(so.get("Body", {}) or {})
    return {1: body, 2: dict(body), 3: dict(body)}


def _style_toc_level(style_obj) -> int | None:
    try:
        name = str(getattr(style_obj, "name", "") or "")
        sid = str(getattr(style_obj, "style_id", "") or "")
    except Exception:
        return None
    if name.lower() == "toc heading":
        return 1
    return _toc_level_from_name(name) or _toc_level_from_name(sid)


def _style_is_index_link(style_obj) -> bool:
    try:
        name = str(getattr(style_obj, "name", "") or "").lower()
        sid = str(getattr(style_obj, "style_id", "") or "").lower()
    except Exception:
        return False
    return name == "indexlink" or sid == "indexlink"


def repair_toc_result_runs(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    style_map = resolve_toc_style_overrides(config)
    if not any(has_text_style(v) for v in style_map.values()):
        return {"applied": False, "paragraphs_modified": 0, "runs_modified": 0}

    style_names = style_name_by_id(doc)
    paragraphs_modified = 0
    runs_modified = 0
    try:
        paragraphs = list(doc._element.body.xpath(".//w:p"))
    except Exception:
        paragraphs = []

    for p_el in paragraphs:
        if not _is_toc_paragraph_element(p_el, style_names):
            continue
        level = max(1, min(3, _toc_level_for_paragraph(p_el, style_names)))
        text_style = style_map.get(level) or style_map.get(1) or {}
        if not has_text_style(text_style):
            continue

        paragraph_modified = False
        for r_el in p_el.xpath(".//w:r"):
            if not run_has_visible_text(r_el):
                continue
            if apply_text_style_to_run_element(r_el, text_style):
                runs_modified += 1
                paragraph_modified = True
        if paragraph_modified:
            paragraphs_modified += 1

    return {
        "applied": bool(runs_modified),
        "paragraphs_modified": paragraphs_modified,
        "runs_modified": runs_modified,
    }


def apply_toc_styles(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    style_map = resolve_toc_style_overrides(config)
    styles_modified = 0
    index_link_modified = False

    try:
        styles = list(doc.styles)
    except Exception:
        styles = []

    for style_obj in styles:
        try:
            style_type = getattr(style_obj, "type", None)
        except Exception:
            continue

        if style_type == WD_STYLE_TYPE.PARAGRAPH:
            level = _style_toc_level(style_obj)
            if level is None:
                continue
            text_style = style_map.get(max(1, min(3, level))) or style_map.get(1) or {}
            if apply_text_style_to_style(style_obj, text_style):
                styles_modified += 1
        elif style_type == WD_STYLE_TYPE.CHARACTER and _style_is_index_link(style_obj):
            text_style = style_map.get(1) or {}
            if apply_text_style_to_style(style_obj, text_style):
                index_link_modified = True

    repaired = repair_toc_result_runs(doc, config)
    return {
        "applied": bool(styles_modified or index_link_modified or repaired.get("applied")),
        "styles_modified": styles_modified,
        "index_link_modified": index_link_modified,
        "result_runs": repaired,
    }


def restyle_toc_after_libreoffice(docx_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    doc = Document(docx_path)
    result = apply_toc_styles(doc, config)
    doc.save(docx_path)
    result["output_path"] = docx_path
    result["saved"] = True
    return result


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
    toc_style_result = apply_toc_styles(doc, config)

    # Ensure body section has proper page numbering restart for correct TOC
    # This is critical for LibreOffice to calculate correct page numbers
    section_fix_result = ensure_body_section_with_numbering(doc, config)

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
            "styles": toc_style_result,
            "heuristic": heuristic_info,
            "section_fix": section_fix_result,
        },
        "output_path": saved_path,
    }
