from __future__ import annotations

import os
from typing import Any, Dict, List, Set

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from .loader import Loader
from .scan import _style_key, _style_name, _has_paragraph_overrides
from .cover import _has_page_or_section_break, _ensure_output_path
from .styles_xml import cleanup_styles_xml


def _compute_body_start_index(doc: Document) -> int:
    """Return index of the first body paragraph (after the cover block).

    The cover block is defined as all paragraphs from the start of the
    document up to and including the first paragraph that contains a page
    or section break, reusing the same heuristic as the cover pipeline.
    If no such break is found, the whole document is treated as body.
    """
    cover_indices: List[int] = []
    found_break = False
    for idx, p in enumerate(doc.paragraphs):
        cover_indices.append(idx)
        if _has_page_or_section_break(p):
            found_break = True
            break
    if cover_indices and found_break:
        last_cover = max(cover_indices)
        return min(last_cover + 1, len(doc.paragraphs))
    return 0


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


def _apply_body_style_overrides(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply centralized overrides for the Body paragraph style.

    This uses roles.Body to locate the primary body style (default "Normal"),
    and then applies overrides from style_overrides.Body plus any ephemeral
    _body_override payload that may be attached to the config by the web API.

    The goal is to adjust the *style definition* rather than touching every
    paragraph individually, so that formatting remains centrally controlled
    and predictable.
    """

    roles_cfg = (config or {}).get("roles", {}) or {}
    body_name = str(roles_cfg.get("Body") or "Normal")

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
        return {"applied": False, "style": body_name, "changes": {}}

    try:
        style = doc.styles[body_name]
    except Exception:
        return {"applied": False, "style": body_name, "missing": True, "changes": {}}

    changes: Dict[str, Any] = {}

    # Font-level overrides
    try:
        f = style.font
    except Exception:
        f = None
    if f is not None:
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

    # Paragraph-level overrides (alignment and basic spacing parameters).
    try:
        pf = style.paragraph_format
    except Exception:
        pf = None
    if pf is not None:
        if isinstance(align, str) and align:
            val = None
            a = align.lower()
            if a == "left":
                val = WD_ALIGN_PARAGRAPH.LEFT
            elif a == "center":
                val = WD_ALIGN_PARAGRAPH.CENTER
            elif a == "right":
                val = WD_ALIGN_PARAGRAPH.RIGHT
            elif a == "justify":
                val = WD_ALIGN_PARAGRAPH.JUSTIFY
            if val is not None:
                try:
                    pf.alignment = val
                    changes["alignment"] = a
                except Exception:
                    pass
        if isinstance(line_spacing, (int, float)) and line_spacing > 0:
            try:
                pf.line_spacing = float(line_spacing)
                changes["line_spacing"] = float(line_spacing)
            except Exception:
                pass
        if isinstance(spacing_before_pt, (int, float)) and spacing_before_pt >= 0:
            try:
                pf.space_before = Pt(float(spacing_before_pt))
                changes["spacing_before_pt"] = float(spacing_before_pt)
            except Exception:
                pass
        if isinstance(spacing_after_pt, (int, float)) and spacing_after_pt >= 0:
            try:
                pf.space_after = Pt(float(spacing_after_pt))
                changes["spacing_after_pt"] = float(spacing_after_pt)
            except Exception:
                pass

    return {"applied": bool(changes), "style": body_name, "changes": changes}


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
        }
    }


def apply_whole_document(input_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    loader = Loader()
    doc = loader.open(input_path)

    body_start = _compute_body_start_index(doc)

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

    try:
        normal_style = doc.styles["Normal"]
    except Exception:
        normal_style = None

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
            if collapse_misc and not protected and normal_style is not None and name != "Normal":
                try:
                    p.style = normal_style
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
            if collapse_misc and normal_style is not None:
                try:
                    p.style = normal_style
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

    body_overrides = _apply_body_style_overrides(doc, config)
    special_overrides = _apply_special_style_overrides(doc, config)

    out_cfg = (config or {}).get("output", {}) or {}
    out_dir = out_cfg.get("dir", "output")
    os.makedirs(out_dir, exist_ok=True)
    versioning = bool(out_cfg.get("versioning", True))
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
            "special_overrides": special_overrides,
        },
        "output_path": saved_path,
    }
