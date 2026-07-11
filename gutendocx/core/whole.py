from __future__ import annotations

import os
from typing import Any, Dict, List, Set

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from .loader import Loader
from .scan import _style_key, _style_name, _has_paragraph_overrides
from .cover import _ensure_output_path
from .styles_xml import cleanup_styles_xml
from .docx_format import (
    W_NS,
    apply_text_style_to_run_element,
    has_text_style,
    run_has_visible_text,
    style_name_by_id,
    text_style_from_override,
)
from .layout import ensure_body_section_with_numbering, analyze_document_sections, ensure_blank_page_after_cover, apply_footer_styles
from .word_cleanup import apply_word_cleanup


def _w_tag(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def _has_explicit_page_break(p) -> bool:
    """Check for EXPLICIT page or section breaks only.
    
    Unlike _has_page_or_section_break in cover.py, this does NOT count
    lastRenderedPageBreak, which is just a rendering marker, not an actual break.
    """
    el = p._element
    try:
        # Explicit page break: <w:br w:type="page"/>
        if el.xpath('.//w:br[@w:type="page"]'):
            return True
        # Section break in paragraph properties
        if el.xpath('./w:pPr/w:sectPr'):
            return True
    except Exception:
        return False
    return False


_COVER_PARAGRAPH_STYLE_NAMES = {
    "Title",
    "Subtitle",
    "Author",
    "Cover Title",
    "Cover Subtitle",
    "Cover Author",
}
_MIN_RECOVERED_BODY_CHARS = 40


def _paragraph_visible_text(p) -> str:
    try:
        return "".join(p._element.xpath(".//w:t/text()"))
    except Exception:
        try:
            return str(p.text or "")
        except Exception:
            return ""


def _paragraph_has_visible_or_structural_content(p) -> bool:
    if _paragraph_visible_text(p).strip():
        return True
    try:
        return bool(p._element.xpath(".//w:fldChar|.//w:instrText|.//w:drawing|.//w:pict|.//w:object"))
    except Exception:
        return False


def _recover_cover_anchored_body_start(doc: Document, legacy_body_start: int) -> int:
    """Recover real post-cover text skipped by the two-break assumption."""
    paragraphs = list(doc.paragraphs)
    if legacy_body_start <= 0 or not paragraphs:
        return legacy_body_start

    cover_indices = [
        idx
        for idx, p in enumerate(paragraphs[:legacy_body_start])
        if _style_name(getattr(p, "style", None)) in _COVER_PARAGRAPH_STYLE_NAMES
    ]
    if not cover_indices:
        return legacy_body_start

    candidate = cover_indices[-1] + 1
    while candidate < legacy_body_start and not _paragraph_visible_text(paragraphs[candidate]).strip():
        candidate += 1
    if candidate >= legacy_body_start:
        return legacy_body_start

    recovered_chars = sum(
        len(_paragraph_visible_text(p).strip())
        for p in paragraphs[candidate:legacy_body_start]
    )
    if recovered_chars < _MIN_RECOVERED_BODY_CHARS:
        return legacy_body_start
    return candidate


def _compute_body_start_index(doc: Document) -> int:
    """Return index of the first body paragraph (after the cover + blank page).

    The document structure is expected to be:
      - Page 1: Cover (Title, Subtitle, Author) ending with a page/section break
      - Page 2: Blank page ending with a page/section break  
      - Page 3+: Body text (starts here)
    
    We need to find TWO page/section breaks. The body starts after the second break.
    If only one break is found, body starts after that break unless that
    break is a trailing final-document marker with no following body content.
    If no break is found, the whole document is treated as body (index 0).
    """
    break_indices: list[int] = []
    
    for idx, p in enumerate(doc.paragraphs):
        # Use explicit page break check (not lastRenderedPageBreak)
        if _has_explicit_page_break(p):
            break_indices.append(idx)
            # Stop after finding 2 breaks
            if len(break_indices) >= 2:
                break
    
    if len(break_indices) >= 2:
        # Body starts after the SECOND break
        body_start = break_indices[1] + 1
        body_start = min(body_start, len(doc.paragraphs))
        return _recover_cover_anchored_body_start(doc, body_start)
    elif len(break_indices) == 1:
        trailing_paragraphs = doc.paragraphs[break_indices[0] + 1 :]
        if not any(_paragraph_has_visible_or_structural_content(p) for p in trailing_paragraphs):
            return 0
        # Only one break found - body starts after it
        body_start = break_indices[0] + 1
        body_start = min(body_start, len(doc.paragraphs))
        return _recover_cover_anchored_body_start(doc, body_start)
    
    return 0


def _uses_single_trailing_break_as_body_boundary(doc: Document, body_start: int) -> bool:
    """Return True when body starts at 0 only because one final explicit break was ignored."""
    if body_start != 0:
        return False

    paragraphs = list(doc.paragraphs)
    if not paragraphs:
        return False

    break_indices: list[int] = []
    for idx, p in enumerate(paragraphs):
        if _has_explicit_page_break(p):
            break_indices.append(idx)
            if len(break_indices) > 1:
                return False

    if len(break_indices) != 1:
        return False
    trailing_paragraphs = paragraphs[break_indices[0] + 1 :]
    return not any(_paragraph_has_visible_or_structural_content(p) for p in trailing_paragraphs)


def _collect_special_flags(run) -> Dict[str, bool]:
    f = run.font
    bold = bool(getattr(run, "bold", None) is True or getattr(f, "bold", None) is True)
    italic = bool(getattr(run, "italic", None) is True or getattr(f, "italic", None) is True)
    underline = bool(getattr(run, "underline", None))
    strike = bool(getattr(f, "strike", None) is True or getattr(f, "double_strike", None) is True)
    all_caps = bool(getattr(f, "all_caps", None) is True)
    small_caps = bool(getattr(f, "small_caps", None) is True)
    return {
        "bold": bold,
        "italic": italic,
        "underline": underline,
        "strike": strike,
        "all_caps": all_caps,
        "small_caps": small_caps,
    }


def _combo_name(flags: Dict[str, bool]) -> str:
    parts_order = ["bold", "italic", "underline", "strike", "all_caps", "small_caps"]
    label = {
        "bold": "Bold",
        "italic": "Italic",
        "underline": "Underline",
        "strike": "Strike",
        "all_caps": "AllCaps",
        "small_caps": "SmallCaps",
    }
    active = [label[k] for k in parts_order if flags.get(k)]
    return "".join(active)


def _ensure_char_style(doc: Document, name: str, flags: Dict[str, bool]):
    styles = doc.styles
    try:
        style = styles[name]
    except KeyError:
        style = styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
    if style.type == WD_STYLE_TYPE.CHARACTER:
        f = style.font
        if flags.get("bold"):
            f.bold = True
        if flags.get("italic"):
            f.italic = True
        if flags.get("underline"):
            f.underline = True
        if flags.get("strike"):
            try:
                f.strike = True
            except Exception:
                pass
        if flags.get("all_caps"):
            f.all_caps = True
        if flags.get("small_caps"):
            f.small_caps = True
    return style


def _collect_used_style_ids(doc: Document) -> Dict[str, Set[str]]:
    """Collect styleIds actually used in the document, including headers/footers.

    Returns a dict with keys: paragraph, character, table.
    """

    para_ids: Set[str] = set()
    char_ids: Set[str] = set()
    table_ids: Set[str] = set()

    def _add_para(p):
        st = getattr(p, "style", None)
        if st is not None:
            sid = getattr(st, "style_id", None)
            if sid:
                para_ids.add(str(sid))
        for r in getattr(p, "runs", []) or []:
            rst = getattr(r, "style", None)
            if rst is not None:
                csid = getattr(rst, "style_id", None)
                if csid:
                    char_ids.add(str(csid))

    def _add_table(t):
        st = getattr(t, "style", None)
        if st is not None:
            sid = getattr(st, "style_id", None)
            if sid:
                table_ids.add(str(sid))
        for row in getattr(t, "rows", []) or []:
            for cell in getattr(row, "cells", []) or []:
                for p in getattr(cell, "paragraphs", []) or []:
                    _add_para(p)

    for p in getattr(doc, "paragraphs", []) or []:
        _add_para(p)

    for t in getattr(doc, "tables", []) or []:
        _add_table(t)

    for sec in getattr(doc, "sections", []) or []:
        for part in (
            getattr(sec, "header", None),
            getattr(sec, "first_page_header", None),
            getattr(sec, "even_page_header", None),
            getattr(sec, "footer", None),
            getattr(sec, "first_page_footer", None),
            getattr(sec, "even_page_footer", None),
        ):
            if part is None:
                continue
            for p in getattr(part, "paragraphs", []) or []:
                _add_para(p)
            for t in getattr(part, "tables", []) or []:
                _add_table(t)

    return {
        "paragraph": para_ids,
        "character": char_ids,
        "table": table_ids,
    }


def _apply_special_style_overrides(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    specials_cfg = (config or {}).get("special_overrides", {}) or {}
    if not isinstance(specials_cfg, dict) or not specials_cfg:
        return {"applied": False, "styles": {}}

    applied: Dict[str, Dict[str, Any]] = {}

    for name, ov in specials_cfg.items():
        if not isinstance(ov, dict):
            continue
        try:
            style = doc.styles[name]
        except Exception:
            try:
                style = doc.styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
            except Exception:
                continue
        if getattr(style, "type", None) != WD_STYLE_TYPE.CHARACTER:
            continue

        changes: Dict[str, Any] = {}
        try:
            f = style.font
        except Exception:
            f = None
        if f is None:
            continue

        font_name = ov.get("font") or ov.get("family")
        size_pt = ov.get("size_pt")
        bold = ov.get("bold") if "bold" in ov else None
        italic = ov.get("italic") if "italic" in ov else None
        underline = ov.get("underline") if "underline" in ov else None
        strike = ov.get("strike") if "strike" in ov else None
        all_caps = ov.get("all_caps") if "all_caps" in ov else None
        small_caps = ov.get("small_caps") if "small_caps" in ov else None

        if font_name:
            try:
                f.name = font_name
                changes["font_family"] = font_name
            except Exception:
                pass
        if isinstance(size_pt, (int, float)) and size_pt > 0:
            try:
                f.size = Pt(float(size_pt))
                changes["size_pt"] = float(size_pt)
            except Exception:
                pass
        if bold is not None:
            try:
                f.bold = bool(bold)
                changes["bold"] = bool(bold)
            except Exception:
                pass
        if italic is not None:
            try:
                f.italic = bool(italic)
                changes["italic"] = bool(italic)
            except Exception:
                pass
        if underline is not None:
            try:
                f.underline = bool(underline)
                changes["underline"] = bool(underline)
            except Exception:
                pass
        if strike is not None:
            try:
                f.strike = bool(strike)
                changes["strike"] = bool(strike)
            except Exception:
                pass
        if all_caps is not None:
            try:
                f.all_caps = bool(all_caps)
                changes["all_caps"] = bool(all_caps)
            except Exception:
                pass
        if small_caps is not None:
            try:
                f.small_caps = bool(small_caps)
                changes["small_caps"] = bool(small_caps)
            except Exception:
                pass

        if changes:
            applied[name] = changes

    return {"applied": bool(applied), "styles": applied}


def _paragraph_style_id_xml(p_el) -> str:
    try:
        p_style = p_el.find(f"./{_w_tag('pPr')}/{_w_tag('pStyle')}")
        if p_style is not None:
            return str(p_style.get(_w_tag("val")) or "")
    except Exception:
        pass
    return ""


def _body_region_roots(doc: Document, body_start: int) -> List[Any]:
    """Return direct body-child elements that belong to the post-cover body."""
    roots: List[Any] = []
    try:
        body = doc._element.body
    except Exception:
        return roots

    direct_paragraph_index = 0
    for child in list(body):
        if child.tag == _w_tag("p"):
            if direct_paragraph_index >= body_start:
                roots.append(child)
            direct_paragraph_index += 1
        elif direct_paragraph_index >= body_start:
            roots.append(child)
    return roots


def _direct_body_child(el):
    cur = el
    while cur is not None:
        parent = cur.getparent()
        if parent is not None and parent.tag == _w_tag("body"):
            return cur
        cur = parent
    return None


def _is_in_body_region_xml(el, body_roots: List[Any]) -> bool:
    root = _direct_body_child(el)
    return root is not None and any(root is item or root == item for item in body_roots)


def _is_toc_paragraph_xml(p_el, style_names: Dict[str, str]) -> bool:
    sid = _paragraph_style_id_xml(p_el)
    sname = style_names.get(sid, "")
    if sid.lower().startswith("toc") or sname.lower().startswith("toc"):
        return True
    try:
        instr = " ".join(t for t in p_el.xpath(".//w:instrText/text()") if t)
    except Exception:
        instr = ""
    upper = instr.upper()
    return "TOC" in upper or "PAGEREF" in upper


def _is_protected_body_paragraph_xml(
    p_el,
    style_names: Dict[str, str],
    protected_names: Set[str],
    detected_heading_names: Set[str],
) -> bool:
    sid = _paragraph_style_id_xml(p_el)
    name = style_names.get(sid, "")
    if not name:
        return False
    lname = name.lower()
    return bool(
        name in protected_names
        or name.startswith("Heading ")
        or name in detected_heading_names
        or lname.startswith("toc")
    )


def _apply_body_font_to_tables_and_hyperlinks(
    doc: Document,
    config: Dict[str, Any],
    body_start: int,
    protected_names: Set[str],
    detected_heading_names: Set[str],
) -> Dict[str, Any]:
    so = (config or {}).get("style_overrides", {}) or {}
    text_style = text_style_from_override(so.get("Body", {}) or {})
    if not has_text_style(text_style):
        return {
            "applied": False,
            "paragraphs_modified": 0,
            "table_runs_modified": 0,
            "hyperlink_runs_modified": 0,
        }

    try:
        body = doc._element.body
    except Exception:
        return {
            "applied": False,
            "paragraphs_modified": 0,
            "table_runs_modified": 0,
            "hyperlink_runs_modified": 0,
        }

    body_roots = _body_region_roots(doc, body_start)
    style_names = style_name_by_id(doc)
    paragraphs_modified = 0
    table_runs_modified = 0
    hyperlink_runs_modified = 0

    for p_el in body.xpath(".//w:p"):
        if not _is_in_body_region_xml(p_el, body_roots):
            continue
        if _is_toc_paragraph_xml(p_el, style_names):
            continue
        if _is_protected_body_paragraph_xml(p_el, style_names, protected_names, detected_heading_names):
            continue

        in_table = bool(p_el.xpath("ancestor::w:tbl"))
        paragraph_modified = False
        for r_el in p_el.xpath(".//w:r"):
            in_hyperlink = bool(r_el.xpath("ancestor::w:hyperlink"))
            if not in_table and not in_hyperlink:
                continue
            if not run_has_visible_text(r_el):
                continue
            if apply_text_style_to_run_element(r_el, text_style):
                paragraph_modified = True
                if in_table:
                    table_runs_modified += 1
                if in_hyperlink:
                    hyperlink_runs_modified += 1

        if paragraph_modified:
            paragraphs_modified += 1

    return {
        "applied": bool(paragraphs_modified),
        "paragraphs_modified": paragraphs_modified,
        "table_runs_modified": table_runs_modified,
        "hyperlink_runs_modified": hyperlink_runs_modified,
    }


def restyle_body_nested_runs(docx_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Re-apply body font overrides to table text and visible hyperlink runs."""
    doc = Document(docx_path)
    body_start = _compute_body_start_index(doc)
    protected_names = {
        "Title",
        "Subtitle",
        "Author",
        "Cover Title",
        "Cover Subtitle",
        "Cover Author",
        "Header",
        "Footer",
    }
    detected_mapping = (config or {}).get("detected_style_mapping", {}) or {}
    detected_heading_names = {
        str(v)
        for k, v in detected_mapping.items()
        if str(k) in ("Headings", "Heading1", "Heading2", "Heading3", "Heading4") and v
    }
    result = _apply_body_font_to_tables_and_hyperlinks(
        doc,
        config,
        body_start,
        protected_names,
        detected_heading_names,
    )
    doc.save(docx_path)
    result["output_path"] = docx_path
    result["saved"] = True
    return result


def _apply_body_style_overrides(doc: Document, config: Dict[str, Any], body_start: int) -> Dict[str, Any]:
    """Apply overrides directly to body paragraphs, only for explicitly specified properties.

    This function applies formatting changes ONLY for properties that are explicitly
    set in the config. Properties not specified are left unchanged, preserving the
    original document formatting.
    
    The overrides come from style_overrides.Body in the config.
    """

    so = (config or {}).get("style_overrides", {}) or {}
    base_ov = so.get("Body", {}) or {}

    # Normalize fields: allow either "font" or "family" for font name.
    font_name = base_ov.get("font") or base_ov.get("family")
    size_pt = base_ov.get("size_pt")
    align = base_ov.get("align")
    bold = base_ov.get("bold")
    italic = base_ov.get("italic")
    line_spacing = base_ov.get("line_spacing")
    spacing_before_pt = base_ov.get("spacing_before_pt")
    spacing_after_pt = base_ov.get("spacing_after_pt")

    if not any(
        v is not None
        for v in (font_name, size_pt, align, bold, italic, line_spacing, spacing_before_pt, spacing_after_pt)
    ):
        return {"applied": False, "changes": {}, "paragraphs_modified": 0}

    # Protected style names that should not be modified
    protected_names = {
        "Title", "Subtitle", "Author",
        "Cover Title", "Cover Subtitle", "Cover Author",
        "Header", "Footer",
    }
    detected_mapping = (config or {}).get("detected_style_mapping", {}) or {}
    detected_heading_names = {
        str(v)
        for k, v in detected_mapping.items()
        if str(k) in ("Headings", "Heading1", "Heading2", "Heading3", "Heading4") and v
    }

    changes: Dict[str, Any] = {}
    paragraphs_modified = 0
    skip_line_spacing_for_trailing_break = (
        isinstance(line_spacing, (int, float))
        and line_spacing > 0
        and _uses_single_trailing_break_as_body_boundary(doc, body_start)
    )
    line_spacing_skipped = 0

    # Compute alignment value once
    align_val = None
    if isinstance(align, str) and align:
        a = align.lower()
        if a == "left":
            align_val = WD_ALIGN_PARAGRAPH.LEFT
        elif a == "center":
            align_val = WD_ALIGN_PARAGRAPH.CENTER
        elif a == "right":
            align_val = WD_ALIGN_PARAGRAPH.RIGHT
        elif a == "justify":
            align_val = WD_ALIGN_PARAGRAPH.JUSTIFY

    for idx, p in enumerate(doc.paragraphs):
        if idx < body_start:
            continue

        # Skip protected styles and headings
        style = getattr(p, "style", None)
        name = _style_name(style)
        if name:
            if name in protected_names or name.startswith("Heading ") or name in detected_heading_names or name.lower().startswith("toc"):
                continue

        modified = False

        # Apply font-level overrides to each run in the paragraph
        if font_name or size_pt is not None or bold is not None or italic is not None:
            for r in p.runs:
                if not run_has_visible_text(r._r):
                    continue
                try:
                    f = r.font
                    if font_name:
                        f.name = font_name
                        # Also set eastAsia and cs fonts for full coverage
                        # This ensures LibreOffice uses the correct font
                        try:
                            f.cs_name = font_name  # Complex script font
                        except Exception:
                            pass
                        # Clear theme font references which override explicit fonts
                        try:
                            rPr = r._r.get_or_add_rPr()
                            for attr in ('asciiTheme', 'hAnsiTheme', 'csTheme', 'eastAsiaTheme'):
                                rFonts = rPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts')
                                if rFonts is not None:
                                    rFonts.attrib.pop('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}' + attr, None)
                        except Exception:
                            pass
                        if "font_family" not in changes:
                            changes["font_family"] = font_name
                        modified = True
                    if isinstance(size_pt, (int, float)) and size_pt > 0:
                        f.size = Pt(float(size_pt))
                        if "size_pt" not in changes:
                            changes["size_pt"] = float(size_pt)
                        modified = True
                    if bold is not None:
                        f.bold = bool(bold)
                        if "bold" not in changes:
                            changes["bold"] = bool(bold)
                        modified = True
                    if italic is not None:
                        f.italic = bool(italic)
                        if "italic" not in changes:
                            changes["italic"] = bool(italic)
                        modified = True
                except Exception:
                    pass

        # Apply paragraph-level overrides
        try:
            pf = p.paragraph_format
        except Exception:
            pf = None
        
        if pf is not None:
            if align_val is not None:
                try:
                    pf.alignment = align_val
                    if "alignment" not in changes:
                        changes["alignment"] = align
                    modified = True
                except Exception:
                    pass
            if isinstance(line_spacing, (int, float)) and line_spacing > 0:
                if skip_line_spacing_for_trailing_break:
                    line_spacing_skipped += 1
                else:
                    try:
                        pf.line_spacing = float(line_spacing)
                        if "line_spacing" not in changes:
                            changes["line_spacing"] = float(line_spacing)
                        modified = True
                    except Exception:
                        pass
            if isinstance(spacing_before_pt, (int, float)) and spacing_before_pt >= 0:
                try:
                    pf.space_before = Pt(float(spacing_before_pt))
                    if "spacing_before_pt" not in changes:
                        changes["spacing_before_pt"] = float(spacing_before_pt)
                    modified = True
                except Exception:
                    pass
            if isinstance(spacing_after_pt, (int, float)) and spacing_after_pt >= 0:
                try:
                    pf.space_after = Pt(float(spacing_after_pt))
                    if "spacing_after_pt" not in changes:
                        changes["spacing_after_pt"] = float(spacing_after_pt)
                    modified = True
                except Exception:
                    pass

        if modified:
            paragraphs_modified += 1

    nested_font_result = _apply_body_font_to_tables_and_hyperlinks(
        doc,
        config,
        body_start,
        protected_names,
        detected_heading_names,
    )

    return {
        "applied": bool(changes) or bool(nested_font_result.get("applied")),
        "changes": changes,
        "paragraphs_modified": paragraphs_modified,
        "line_spacing_skipped_for_trailing_break_boundary": line_spacing_skipped,
        "nested_font_overrides": nested_font_result,
    }


def _paragraph_has_field_code(p) -> bool:
    try:
        return bool(p._p.xpath(".//w:fldChar|.//w:instrText"))
    except Exception:
        return False


def _safe_body_style_name(config: Dict[str, Any]) -> str:
    roles_cfg = (config or {}).get("roles", {}) or {}
    configured = str(roles_cfg.get("Body") or "").strip()
    if configured and configured.lower() not in {"normal", "обычный"}:
        return configured
    return "GD Body"


def _ensure_safe_body_style(doc: Document, config: Dict[str, Any]):
    style_name = _safe_body_style_name(config)
    try:
        style = doc.styles[style_name]
    except KeyError:
        style = doc.styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
        try:
            style.base_style = doc.styles["Normal"]
        except Exception:
            pass

    try:
        style.paragraph_format.keep_with_next = False
    except Exception:
        pass
    return style


def _apply_body_style_normalization(doc: Document, config: Dict[str, Any], body_start: int) -> Dict[str, Any]:
    """Move ordinary body paragraphs onto a safe body style.

    This intentionally does not modify Word's global Normal style. Some source
    documents carry pagination flags like keep-with-next on Normal itself, and
    changing Normal can leak into cover text, page numbers, and TOC styles.
    """
    norm_cfg = (config or {}).get("body_style_normalization", {}) or {}
    if norm_cfg.get("enabled") is False:
        return {
            "applied": False,
            "enabled": False,
            "style": None,
            "paragraphs_normalized": 0,
            "skip_reasons": {},
        }

    protected_names = {
        "Title",
        "Subtitle",
        "Author",
        "Cover Title",
        "Cover Subtitle",
        "Cover Author",
        "Header",
        "Footer",
    }
    detected_mapping = (config or {}).get("detected_style_mapping", {}) or {}
    detected_heading_names = {
        str(v)
        for k, v in detected_mapping.items()
        if str(k) in ("Headings", "Heading1", "Heading2", "Heading3", "Heading4") and v
    }

    try:
        safe_style = _ensure_safe_body_style(doc, config)
    except Exception:
        return {
            "applied": False,
            "enabled": True,
            "style": _safe_body_style_name(config),
            "paragraphs_normalized": 0,
            "skip_reasons": {},
            "reason": "style_unavailable",
        }

    safe_style_name = _style_name(safe_style) or _safe_body_style_name(config)
    paragraphs_normalized = 0
    keep_next_cleared = 0
    skip_reasons: Dict[str, int] = {}

    def skip(reason: str) -> None:
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    for idx, p in enumerate(doc.paragraphs):
        if idx < body_start:
            skip("before_body")
            continue

        style = getattr(p, "style", None)
        name = _style_name(style)
        lname = name.lower() if name else ""
        if name in protected_names:
            skip("protected")
            continue
        if name == "Para1":
            skip("para1")
            continue
        if name.startswith("Heading ") or name.startswith("Heading") or name in detected_heading_names:
            skip("heading")
            continue
        if lname.startswith("toc"):
            skip("toc")
            continue
        if _paragraph_has_field_code(p):
            skip("field")
            continue

        try:
            if _style_name(getattr(p, "style", None)) != safe_style_name:
                p.style = safe_style
                paragraphs_normalized += 1
        except Exception:
            skip("assign_failed")
            continue

        try:
            if p.paragraph_format.keep_with_next is not False:
                p.paragraph_format.keep_with_next = False
                keep_next_cleared += 1
        except Exception:
            pass

    return {
        "applied": paragraphs_normalized > 0 or keep_next_cleared > 0,
        "enabled": True,
        "style": safe_style_name,
        "paragraphs_normalized": paragraphs_normalized,
        "keep_with_next_cleared": keep_next_cleared,
        "skip_reasons": skip_reasons,
    }


def _paragraph_has_manual_line_break(p) -> bool:
    """Return True when a paragraph contains a manual line break, not a page/column break."""
    try:
        for br in p._element.xpath('.//w:br'):
            br_type = br.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type')
            if br_type in (None, "", "textWrapping"):
                return True
    except Exception:
        pass

    try:
        text = p.text or ""
    except Exception:
        text = ""
    return "\n" in text or "@L@" in text or "^l" in text


def _apply_para1_manual_line_break_style(doc: Document, config: Dict[str, Any], body_start: int) -> Dict[str, Any]:
    """Apply left-aligned Para1 to non-heading body paragraphs with manual line breaks."""
    protected_names = {
        "Title",
        "Subtitle",
        "Author",
        "Cover Title",
        "Cover Subtitle",
        "Cover Author",
        "Header",
        "Footer",
    }
    detected_mapping = (config or {}).get("detected_style_mapping", {}) or {}
    detected_heading_names = {
        str(v)
        for k, v in detected_mapping.items()
        if str(k) in ("Headings", "Heading1", "Heading2", "Heading3", "Heading4") and v
    }

    para1_name = "Para1"
    try:
        para1_style = doc.styles[para1_name]
    except KeyError:
        try:
            para1_style = doc.styles.add_style(para1_name, WD_STYLE_TYPE.PARAGRAPH)
            para1_style.base_style = doc.styles["Normal"]
        except Exception:
            para1_style = None
    except Exception:
        para1_style = None

    if para1_style is None or getattr(para1_style, "type", None) != WD_STYLE_TYPE.PARAGRAPH:
        return {"applied": False, "style": para1_name, "paragraphs_modified": 0, "reason": "style_unavailable"}

    try:
        para1_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    except Exception:
        pass

    paragraphs_modified = 0
    for idx, p in enumerate(doc.paragraphs):
        if idx < body_start:
            continue

        style = getattr(p, "style", None)
        name = _style_name(style)
        if name:
            lname = name.lower()
            if (
                name in protected_names
                or name.startswith("Heading ")
                or name.startswith("Heading")
                or name in detected_heading_names
                or lname.startswith("toc")
            ):
                continue

        if not _paragraph_has_manual_line_break(p):
            continue

        modified = False
        try:
            if _style_name(getattr(p, "style", None)) != para1_name:
                p.style = para1_style
                modified = True
        except Exception:
            pass
        try:
            if p.paragraph_format.alignment != WD_ALIGN_PARAGRAPH.LEFT:
                p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
                modified = True
        except Exception:
            pass
        if modified:
            paragraphs_modified += 1

    return {
        "applied": paragraphs_modified > 0,
        "style": para1_name,
        "alignment": "center",
        "paragraphs_modified": paragraphs_modified,
    }


def _apply_headings_style_overrides(doc: Document, config: Dict[str, Any], body_start: int) -> Dict[str, Any]:
    """Apply overrides to Heading paragraphs (chapter titles).
    
    This applies formatting to paragraphs mapped to heading roles. In addition
    to built-in Heading 1/2/3/4 styles, it respects detected_style_mapping from
    Learn Body Styles, because Gutenberg DOCX files often use custom style
    names like Para 04 or Para 08 for headings.
    """
    so = (config or {}).get("style_overrides", {}) or {}
    detected_mapping = (config or {}).get("detected_style_mapping", {}) or {}

    role_keys = ("Headings", "Heading2", "Heading3", "Heading4")
    default_style_names = {
        "Headings": ["Heading 1", "Heading1", "Heading 2", "Heading2", "Heading 3", "Heading3", "Heading 4", "Heading4"],
        "Heading2": ["Heading 2", "Heading2"],
        "Heading3": ["Heading 3", "Heading3"],
        "Heading4": ["Heading 4", "Heading4"],
    }

    role_overrides: Dict[str, Dict[str, Any]] = {}
    for role in role_keys:
        ov = so.get(role, {}) or {}
        if isinstance(ov, dict) and any(v is not None for v in ov.values()):
            role_overrides[role] = ov

    if not role_overrides:
        return {"applied": False, "changes": {}, "paragraphs_modified": 0}

    style_to_role: Dict[str, str] = {}
    for role, ov in role_overrides.items():
        mapped = detected_mapping.get(role)
        if mapped:
            style_to_role[str(mapped)] = role
        for name in default_style_names.get(role, []):
            style_to_role.setdefault(name, role)

    changes: Dict[str, Any] = {}
    paragraphs_modified = 0

    def _align_value(align: Any):
        if not isinstance(align, str) or not align:
            return None
        a = align.lower()
        if a == "left":
            return WD_ALIGN_PARAGRAPH.LEFT
        if a == "center":
            return WD_ALIGN_PARAGRAPH.CENTER
        if a == "right":
            return WD_ALIGN_PARAGRAPH.RIGHT
        if a == "justify":
            return WD_ALIGN_PARAGRAPH.JUSTIFY
        return None

    for idx, p in enumerate(doc.paragraphs):
        if idx < body_start:
            continue

        style = getattr(p, "style", None)
        name = _style_name(style)
        role = style_to_role.get(name or "")
        if not role:
            # Backward-compatible fallback: old configs only had Headings.
            if name and name.startswith("Heading") and "Headings" in role_overrides:
                role = "Headings"
            else:
                continue

        ov = role_overrides.get(role, {})
        font_name = ov.get("font") or ov.get("family")
        size_pt = ov.get("size_pt")
        align = ov.get("align")
        bold = ov.get("bold")
        italic = ov.get("italic")
        all_caps = ov.get("all_caps")
        align_val = _align_value(align)

        if not any(v is not None for v in (font_name, size_pt, align, bold, italic, all_caps)):
            continue

        modified = False

        if font_name or size_pt is not None or bold is not None or italic is not None or all_caps is not None:
            for r in p.runs:
                if not run_has_visible_text(r._r):
                    continue
                try:
                    f = r.font
                    if font_name:
                        f.name = font_name
                        # Also set cs font for full coverage
                        try:
                            f.cs_name = font_name
                        except Exception:
                            pass
                        # Clear theme font references which override explicit fonts
                        try:
                            rPr = r._r.get_or_add_rPr()
                            for attr in ('asciiTheme', 'hAnsiTheme', 'csTheme', 'eastAsiaTheme'):
                                rFonts = rPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts')
                                if rFonts is not None:
                                    rFonts.attrib.pop('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}' + attr, None)
                        except Exception:
                            pass
                        if "font_family" not in changes:
                            changes["font_family"] = font_name
                        changes.setdefault("roles", {}).setdefault(role, {})["font_family"] = font_name
                        modified = True
                    if isinstance(size_pt, (int, float)) and size_pt > 0:
                        f.size = Pt(float(size_pt))
                        if "size_pt" not in changes:
                            changes["size_pt"] = float(size_pt)
                        changes.setdefault("roles", {}).setdefault(role, {})["size_pt"] = float(size_pt)
                        modified = True
                    if bold is not None:
                        f.bold = bool(bold)
                        if "bold" not in changes:
                            changes["bold"] = bool(bold)
                        changes.setdefault("roles", {}).setdefault(role, {})["bold"] = bool(bold)
                        modified = True
                    if italic is not None:
                        f.italic = bool(italic)
                        if "italic" not in changes:
                            changes["italic"] = bool(italic)
                        changes.setdefault("roles", {}).setdefault(role, {})["italic"] = bool(italic)
                        modified = True
                    if all_caps is not None:
                        f.all_caps = bool(all_caps)
                        if "all_caps" not in changes:
                            changes["all_caps"] = bool(all_caps)
                        changes.setdefault("roles", {}).setdefault(role, {})["all_caps"] = bool(all_caps)
                        modified = True
                except Exception:
                    pass

        if align_val is not None:
            try:
                pf = p.paragraph_format
                pf.alignment = align_val
                if "alignment" not in changes:
                    changes["alignment"] = align
                changes.setdefault("roles", {}).setdefault(role, {})["alignment"] = align
                modified = True
            except Exception:
                pass

        if modified:
            paragraphs_modified += 1

    return {
        "applied": bool(changes),
        "changes": changes,
        "paragraphs_modified": paragraphs_modified,
        "style_targets": style_to_role,
    }


def analyze_whole_document(input_path: str, config: Dict[str, Any], max_samples: int = 3) -> Dict[str, Any]:
    """Analyze styles used in the document body (beyond the cover).

    This function does **not** modify the document. It returns an inventory
    of paragraph styles in the body region (excluding the cover block) and
    a summary of special direct-formatting combinations (bold/italic/etc.)
    observed at the run level.
    """
    loader = Loader()
    doc = loader.open(input_path)

    body_start = _compute_body_start_index(doc)

    paragraph_styles: Dict[str, Dict[str, Any]] = {}
    special_styles: Dict[str, Dict[str, Any]] = {}

    para_total = 0
    run_total = 0

    for idx, p in enumerate(doc.paragraphs):
        if idx < body_start:
            continue
        para_total += 1

        style = getattr(p, "style", None)
        skey = _style_key(style)
        sname = _style_name(style)

        # Skip explicit cover-related styles when working on whole document
        if sname in {"Title", "Subtitle", "Author"}:
            continue

        rec = paragraph_styles.setdefault(
            skey,
            {"name": sname, "count": 0, "has_direct_overrides": False, "samples": []},
        )
        rec["count"] += 1
        if not rec["has_direct_overrides"] and _has_paragraph_overrides(p):
            rec["has_direct_overrides"] = True
        text = (p.text or "").strip()
        if text and len(rec["samples"]) < max_samples:
            rec["samples"].append(text)

        # Run-level special formatting inventory (direct formatting only)
        for r in p.runs:
            run_total += 1
            flags = _collect_special_flags(r)
            if not any(flags.values()):
                continue
            cname = _combo_name(flags)
            if not cname:
                continue
            srec = special_styles.setdefault(
                cname,
                {"name": cname, "flags": flags.copy(), "count_runs": 0, "samples": []},
            )
            srec["count_runs"] += 1
            rtxt = (r.text or "").strip()
            if rtxt and len(srec["samples"]) < max_samples:
                srec["samples"].append(rtxt)

    def _sorted(d: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return dict(sorted(d.items(), key=lambda kv: kv[1].get("count", 0), reverse=True))

    paragraph_styles_sorted = _sorted(paragraph_styles)
    special_styles_list: List[Dict[str, Any]] = []
    for name in sorted(special_styles.keys()):
        special_styles_list.append(special_styles[name])

    heading_styles: List[Dict[str, Any]] = []
    for skey, rec in paragraph_styles_sorted.items():
        name = str(rec.get("name") or "")
        if name.startswith("Heading "):
            level = None
            try:
                tail = name.split("Heading ", 1)[1].strip()
                level = int(tail.split(" ", 1)[0]) if tail else None
            except Exception:
                level = None
            heading_styles.append(
                {
                    "style_key": skey,
                    "name": name,
                    "level": level,
                    "count": rec.get("count", 0),
                }
            )

    heading_styles.sort(key=lambda h: (h["level"] if isinstance(h.get("level"), int) else 999, h["name"]))

    # Analyze document section structure for TOC page numbering
    section_analysis = analyze_document_sections(doc)

    return {
        "whole": {
            "body_start_index": body_start,
            "paragraph_styles": paragraph_styles_sorted,
            "heading_styles": heading_styles,
            "special_styles": special_styles_list,
            "summary": {
                "body_paragraph_total": para_total,
                "body_run_total": run_total,
            },
            "section_analysis": section_analysis,
        }
    }


def apply_whole_document(input_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    loader = Loader()
    doc = loader.open(input_path)

    body_start = _compute_body_start_index(doc)
    word_cleanup = apply_word_cleanup(doc, config, body_start)

    norm_cfg = (((config or {}).get("cover", {}) or {}).get("normalize", {}) or {})
    collapse_misc = bool(norm_cfg.get("collapse_misc_to_normal", False))
    map_runs_to_char_styles = bool(norm_cfg.get("map_runs_to_char_styles", True))
    cleanup_unused_styles = bool(norm_cfg.get("cleanup_unused_styles", False))

    protected_names = {
        "Title",
        "Subtitle",
        "Author",
        "Cover Title",
        "Cover Subtitle",
        "Cover Author",
        "Header",
        "Footer",
    }

    # Get body style name from config (default "GD Body", NOT "Normal")
    # This ensures we don't modify Normal which would affect Cover styles
    roles_cfg = (config or {}).get("roles", {}) or {}
    body_style_name = str(roles_cfg.get("Body") or "GD Body")
    
    # Get or create the body style
    try:
        body_style = doc.styles[body_style_name]
    except KeyError:
        # Create the style if it doesn't exist, based on Normal
        try:
            body_style = doc.styles.add_style(body_style_name, WD_STYLE_TYPE.PARAGRAPH)
            body_style.base_style = doc.styles["Normal"]
        except Exception:
            body_style = doc.styles["Normal"]
    except Exception:
        body_style = None

    collapsed_paragraphs = 0
    run_combo_counts: Dict[str, int] = {}
    created_char_styles: List[str] = []

    pf_attrs = (
        "space_before",
        "space_after",
        "line_spacing",
        "line_spacing_rule",
        "first_line_indent",
        "left_indent",
        "right_indent",
        "alignment",
        "keep_together",
        "keep_with_next",
        "page_break_before",
        "widow_control",
    )

    for idx, p in enumerate(doc.paragraphs):
        if idx < body_start:
            continue

        style = getattr(p, "style", None)
        name = _style_name(style)

        # Collect paragraph-level direct overrides and style-level defaults
        # only when we are actually collapsing styles. In the safe mode
        # (collapse_misc is False) we avoid touching paragraph_format to
        # keep the document layout as stable as possible.
        para_pf_vals: Dict[str, Any] = {}
        style_pf_vals: Dict[str, Any] = {}
        if collapse_misc:
            try:
                ppf = getattr(p, "paragraph_format", None)
            except Exception:
                ppf = None
            if ppf is not None:
                for attr in pf_attrs:
                    try:
                        val = getattr(ppf, attr, None)
                    except Exception:
                        val = None
                    if val is not None:
                        para_pf_vals[attr] = val

            # Then collect style-level defaults which we will re-apply only
            # where there was no paragraph-level override.
            try:
                spf = getattr(style, "paragraph_format", None)
            except Exception:
                spf = None
            if spf is not None:
                for attr in pf_attrs:
                    try:
                        val = getattr(spf, attr, None)
                    except Exception:
                        val = None
                    if val is not None:
                        style_pf_vals[attr] = val

        is_toc = False
        if name:
            lname = name.lower()
            if lname.startswith("toc"):
                is_toc = True
            protected = bool(
                name in protected_names
                or name.startswith("Heading ")
                or is_toc
            )
            # Only reassign styles if collapse_misc is explicitly enabled
            # Otherwise, preserve original paragraph styles to maintain formatting
            if collapse_misc and not protected and body_style is not None and name != body_style_name:
                try:
                    p.style = body_style
                    collapsed_paragraphs += 1
                    pf = p.paragraph_format
                    # 1) Reapply style-level values where there was no
                    #    direct paragraph override.
                    for attr, val in style_pf_vals.items():
                        if attr in para_pf_vals:
                            continue
                        try:
                            setattr(pf, attr, val)
                        except Exception:
                            pass
                    # 2) Reapply paragraph-level overrides so they stay
                    #    exactly as in the original document.
                    for attr, val in para_pf_vals.items():
                        try:
                            setattr(pf, attr, val)
                        except Exception:
                            pass
                except Exception:
                    pass
        else:
            # No style name - only assign body_style if collapse_misc is enabled
            if collapse_misc and body_style is not None:
                try:
                    p.style = body_style
                    collapsed_paragraphs += 1
                except Exception:
                    pass

        if is_toc:
            continue

        if map_runs_to_char_styles:
            for r in p.runs:
                flags = _collect_special_flags(r)
                if not any(flags.values()):
                    continue
                cname = _combo_name(flags)
                if not cname:
                    continue
                run_combo_counts[cname] = run_combo_counts.get(cname, 0) + 1
                style_obj = _ensure_char_style(doc, cname, flags)
                if style_obj is not None:
                    if cname not in created_char_styles:
                        created_char_styles.append(cname)
                    try:
                        r.style = style_obj
                    except Exception:
                        pass
                f = r.font
                try:
                    f.bold = None
                    f.italic = None
                    f.underline = None
                    f.strike = None
                    if hasattr(f, "double_strike"):
                        setattr(f, "double_strike", None)
                    f.all_caps = None
                    f.small_caps = None
                except Exception:
                    pass

    body_style_normalization = _apply_body_style_normalization(doc, config, body_start)
    body_overrides = _apply_body_style_overrides(doc, config, body_start)
    headings_overrides = _apply_headings_style_overrides(doc, config, body_start)
    para1_manual_breaks = _apply_para1_manual_line_break_style(doc, config, body_start)
    special_overrides = _apply_special_style_overrides(doc, config)

    # Ensure blank page (page 2) exists after cover
    # This must be done BEFORE section numbering fix
    blank_page_result = ensure_blank_page_after_cover(doc, config)

    # Ensure body section has proper page numbering restart for correct TOC
    # This converts the last page break before body into a section break
    # with pgNumType start=1, so LibreOffice calculates correct page numbers
    section_fix_result = ensure_body_section_with_numbering(doc, config)

    # Apply footer styles (page number styling) with numbering starting from 3
    # This clears all footers and adds styled PAGE field only to body section
    footer_result = apply_footer_styles(doc, config)

    out_cfg = (config or {}).get("output", {}) or {}
    out_dir = out_cfg.get("dir", "output")
    os.makedirs(out_dir, exist_ok=True)
    versioning = bool(out_cfg.get("versioning", False))
    output_path = _ensure_output_path(out_dir, input_path, versioning=versioning)
    saved_path = loader.save(doc, output_path)
    cleanup_stats: Dict[str, Any] = {
        "before": 0,
        "after": 0,
        "removed": [],
        "skipped": True,
    }
    if cleanup_unused_styles:
        # Collect styleIds that are actually used after normalization and
        # perform a conservative cleanup of styles.xml.
        used = _collect_used_style_ids(doc)
        keep_ids: Set[str] = set()
        for k in ("paragraph", "character", "table"):
            keep_ids.update(used.get(k, set()))

        # Whitelist important styles by name and created character styles.
        name_whitelist = [
            "Normal",
            body_style_name,  # Add the body style (e.g. "GD Body")
            "Para1",
            "Title",
            "Subtitle",
            "Author",
            "Cover Title",
            "Cover Subtitle",
            "Cover Author",
            "Default Paragraph Font",
            "Hyperlink",
        ]
        name_whitelist.extend(created_char_styles)

        # Add Heading N and TOC* styles by scanning doc.styles by name.
        try:
            for st in doc.styles:  # type: ignore[assignment]
                try:
                    name = str(getattr(st, "name", "") or "")
                    sid = getattr(st, "style_id", None)
                except Exception:
                    continue
                if not sid:
                    continue
                lname = name.lower()
                if name.startswith("Heading ") or lname.startswith("toc"):
                    keep_ids.add(str(sid))
        except Exception:
            pass

        # Resolve styleIds for explicitly whitelisted names.
        for nm in name_whitelist:
            try:
                st = doc.styles[nm]
                sid = getattr(st, "style_id", None)
                if sid:
                    keep_ids.add(str(sid))
            except Exception:
                continue

        cleanup_stats = cleanup_styles_xml(saved_path, keep_ids)

    return {
        "whole": {
            "body_start_index": body_start,
            "collapsed_paragraphs": collapsed_paragraphs,
            "run_combos": run_combo_counts,
            "created_char_styles": sorted(created_char_styles),
            "styles_cleanup": cleanup_stats,
            "body_overrides": body_overrides,
            "body_style_normalization": body_style_normalization,
            "headings_overrides": headings_overrides,
            "word_cleanup": word_cleanup,
            "para1_manual_breaks": para1_manual_breaks,
            "special_overrides": special_overrides,
            "blank_page_fix": blank_page_result,
            "section_fix": section_fix_result,
            "footer_result": footer_result,
        },
        "output_path": saved_path,
    }
