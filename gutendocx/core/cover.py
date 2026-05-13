from __future__ import annotations

from typing import Any, Dict, List, Tuple
import os
import re

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from .loader import Loader
from .layout import apply_sections_and_numbering


def _pt(val) -> float:
    try:
        return float(getattr(val, "pt", 0.0) or 0.0)
    except Exception:
        return 0.0


def _run_size_pt(r) -> float:
    sz = _pt(getattr(r.font, "size", None))
    if sz:
        return sz
    try:
        rs = getattr(r, "style", None)
        if rs is not None:
            sz = _pt(getattr(rs.font, "size", None))
            if sz:
                return sz
    except Exception:
        pass
    return 0.0


def _para_max_font_size_pt(p) -> float:
    max_pt = 0.0
    for r in p.runs:
        sz = _run_size_pt(r)
        if sz > max_pt:
            max_pt = sz
    if max_pt == 0.0:
        try:
            max_pt = _pt(getattr(getattr(p.style, "font", None), "size", None)) or 0.0
        except Exception:
            pass
    return max_pt


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _is_empty_para(p) -> bool:
    return _norm_text(p.text) == ""


def _uc(s: str) -> str:
    return (s or "").upper()


def _uppercase_ratio(s: str) -> float:
    t = re.sub(r"[^A-Za-z]", "", s)
    if not t:
        return 0.0
    up = sum(1 for ch in t if ch.isupper())
    return up / max(len(t), 1)


def _is_decorative_line(s: str) -> bool:
    t = _norm_text(s)
    return bool(re.match(r"^[\-–—_•|]+$", t))


def _is_centered(p) -> bool:
    try:
        if p.alignment == WD_ALIGN_PARAGRAPH.CENTER:
            return True
        st = getattr(p, "style", None)
        if st is not None:
            pf = getattr(st, "paragraph_format", None)
            if pf is not None and pf.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                return True
    except Exception:
        return False
    return False


def _has_page_or_section_break(p) -> bool:
    el = p._element
    try:
        # python-docx OxmlElement.xpath doesn't accept namespaces kwarg; ns prefixes are predefined
        if el.xpath('.//w:br[@w:type="page"]'):
            return True
        if el.xpath('.//w:lastRenderedPageBreak'):
            return True
        if el.xpath('./w:pPr/w:sectPr'):
            return True
    except Exception:
        return False
    return False


def _has_explicit_page_or_section_break(p) -> bool:
    el = p._element
    try:
        if el.xpath('.//w:br[@w:type="page"]'):
            return True
        if el.xpath('./w:pPr/w:sectPr'):
            return True
    except Exception:
        return False
    return False


def _has_last_rendered_page_break(p) -> bool:
    el = p._element
    try:
        return bool(el.xpath('.//w:lastRenderedPageBreak'))
    except Exception:
        return False


def _collect_cover_paragraphs(doc: Document) -> (List, bool):
    cover_paras = []
    found_break = False
    for i, p in enumerate(doc.paragraphs):
        cover_paras.append(p)
        if _has_explicit_page_or_section_break(p):
            found_break = True
            break
        if _has_last_rendered_page_break(p):
            non_empty_added = 0
            for j in range(i + 1, min(i + 7, len(doc.paragraphs))):
                p2 = doc.paragraphs[j]
                if _has_explicit_page_or_section_break(p2):
                    cover_paras.append(p2)
                    found_break = True
                    break
                t2 = _norm_text(p2.text)
                if not t2:
                    cover_paras.append(p2)
                    continue
                if len(t2) <= 40:
                    cover_paras.append(p2)
                    non_empty_added += 1
                    if non_empty_added >= 3:
                        break
                    continue
                break
            found_break = True
            break
    return cover_paras, found_break


def _ensure_paragraph_style(doc: Document, style_name: str, font_cfg: Dict[str, Any]):
    styles = doc.styles
    try:
        style = styles[style_name]
    except KeyError:
        style = styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
    if font_cfg:
        st_font = style.font
        fam = font_cfg.get("family")
        if fam:
            st_font.name = fam
        sz = font_cfg.get("size_pt")
        if sz:
            from docx.shared import Pt

            st_font.size = Pt(float(sz))
        if font_cfg.get("bold") is not None:
            st_font.bold = bool(font_cfg.get("bold"))
        if font_cfg.get("all_caps") is not None:
            st_font.all_caps = bool(font_cfg.get("all_caps"))
        if font_cfg.get("small_caps") is not None:
            st_font.small_caps = bool(font_cfg.get("small_caps"))
        align = font_cfg.get("align")
        if align == "center":
            style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "right":
            style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif align == "left":
            style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    return style


def extract_style_params(paragraph) -> Dict[str, Any]:
    """Extract font/style parameters from a paragraph.
    
    Priority for font properties (family, size):
    1. Direct formatting on runs (most specific - what user actually sees)
    2. Paragraph style (fallback)
    
    For size_pt: uses maximum size across all runs (the dominant visual size).
    
    Returns dict with: family, size_pt, bold, italic, all_caps, small_caps, align
    """
    result: Dict[str, Any] = {}
    
    # FIRST: Try to get font info from runs (direct formatting takes priority)
    # This is what the user actually sees in the document
    if paragraph.runs:
        # Collect all run sizes for debugging
        run_info = []
        first_valid_run = None
        
        for i, run in enumerate(paragraph.runs):
            try:
                rf = run.font
                size = getattr(rf, "size", None)
                sz_pt = _pt(size) if size is not None else 0.0
                family = getattr(rf, "name", None)
                text_preview = (run.text or "")[:20].replace("\n", " ")
                run_info.append({"idx": i, "size_pt": sz_pt, "family": family, "text": text_preview})
                
                # Track first run with valid size and non-empty text
                if first_valid_run is None and sz_pt > 0 and run.text and run.text.strip():
                    first_valid_run = {
                        "size_pt": sz_pt,
                        "family": family,
                        "bold": getattr(rf, "bold", None),
                        "all_caps": getattr(rf, "all_caps", None),
                    }
            except Exception:
                continue
        
        print(f"DEBUG extract_style_params: paragraph text preview='{(paragraph.text or '')[:50].replace(chr(10), ' ')}'")
        print(f"DEBUG extract_style_params: run_info={run_info}")
        print(f"DEBUG extract_style_params: first_valid_run={first_valid_run}")
        
        # Use FIRST valid run (not max) - this is typically the main content
        if first_valid_run:
            if first_valid_run["size_pt"] > 0:
                result["size_pt"] = first_valid_run["size_pt"]
            if first_valid_run["family"]:
                result["family"] = first_valid_run["family"]
            if first_valid_run["bold"] is not None:
                result["bold"] = bool(first_valid_run["bold"])
            if first_valid_run["all_caps"] is not None:
                result["all_caps"] = bool(first_valid_run["all_caps"])
    
    # SECOND: Fallback to paragraph style for missing properties
    style = getattr(paragraph, "style", None)
    if style is not None:
        try:
            sf = style.font
            # Font family - only if not found in runs
            if "family" not in result:
                family = getattr(sf, "name", None)
                if family:
                    result["family"] = family
            
            # Size - only if not found in runs
            if "size_pt" not in result:
                size = getattr(sf, "size", None)
                if size is not None:
                    result["size_pt"] = _pt(size)
            
            # Boolean attributes - only if not found in runs
            if "bold" not in result:
                bold = getattr(sf, "bold", None)
                if bold is not None:
                    result["bold"] = bool(bold)
            
            if "all_caps" not in result:
                all_caps = getattr(sf, "all_caps", None)
                if all_caps is not None:
                    result["all_caps"] = bool(all_caps)
        except Exception:
            pass
        
        # Alignment from paragraph style
        try:
            pf = style.paragraph_format
            align = getattr(pf, "alignment", None)
            if align is not None:
                if align == WD_ALIGN_PARAGRAPH.CENTER:
                    result["align"] = "center"
                elif align == WD_ALIGN_PARAGRAPH.RIGHT:
                    result["align"] = "right"
                elif align == WD_ALIGN_PARAGRAPH.LEFT:
                    result["align"] = "left"
                elif align == WD_ALIGN_PARAGRAPH.JUSTIFY:
                    result["align"] = "justify"
        except Exception:
            pass
    
    # Fallback alignment from paragraph direct formatting
    if "align" not in result:
        try:
            pf = paragraph.paragraph_format
            align = getattr(pf, "alignment", None)
            if align is not None:
                if align == WD_ALIGN_PARAGRAPH.CENTER:
                    result["align"] = "center"
                elif align == WD_ALIGN_PARAGRAPH.RIGHT:
                    result["align"] = "right"
                elif align == WD_ALIGN_PARAGRAPH.LEFT:
                    result["align"] = "left"
                elif align == WD_ALIGN_PARAGRAPH.JUSTIFY:
                    result["align"] = "justify"
        except Exception:
            pass
    
    return result


def _find_run_style_by_text(doc, cover_paras: List, search_text: str) -> Dict[str, Any]:
    """Find a run containing the search_text and return its style params.
    
    This handles cases where multiple roles (e.g. subtitle + author) are in one paragraph.
    We search for the specific text from vision detection and read the style of matching runs.
    """
    if not search_text:
        return {}
    
    # Normalize search text for matching
    search_norm = re.sub(r'\s+', ' ', search_text.strip().upper())
    if len(search_norm) < 3:
        return {}
    
    # Use first few words for matching (AI might truncate)
    search_words = search_norm.split()[:4]
    search_prefix = ' '.join(search_words)
    
    print(f"DEBUG _find_run_style_by_text: searching for '{search_prefix[:30]}...'")
    
    for p in cover_paras:
        for run in p.runs:
            run_text = (run.text or "").strip()
            if not run_text:
                continue
            run_norm = re.sub(r'\s+', ' ', run_text.upper())
            
            # Check if run contains the search text
            # Run must be at least 3 chars and match significantly
            if len(run_norm) < 3:
                continue
            if search_prefix in run_norm or (run_norm in search_prefix and len(run_norm) >= len(search_prefix) * 0.5):
                # Use _run_size_pt which checks run style fallback
                sz_pt = _run_size_pt(run)
                
                # If still 0, try paragraph style chain (including base styles)
                if sz_pt == 0:
                    try:
                        pstyle = p.style
                        while pstyle and sz_pt == 0:
                            if pstyle.font and pstyle.font.size:
                                sz_pt = _pt(pstyle.font.size)
                                break
                            pstyle = pstyle.base_style
                    except Exception:
                        pass
                
                rf = run.font
                family = getattr(rf, "name", None)
                
                # If no family in run, try paragraph style chain
                if not family:
                    try:
                        pstyle = p.style
                        while pstyle and not family:
                            if pstyle.font:
                                family = getattr(pstyle.font, "name", None)
                                if family:
                                    break
                            pstyle = pstyle.base_style
                    except Exception:
                        pass
                
                print(f"DEBUG _find_run_style_by_text: FOUND run '{run_text[:30]}' size={sz_pt}pt family={family}")
                
                if sz_pt > 0:
                    result = {"size_pt": sz_pt}
                    if family:
                        result["family"] = family
                    bold = getattr(rf, "bold", None)
                    if bold is not None:
                        result["bold"] = bool(bold)
                    all_caps = getattr(rf, "all_caps", None)
                    if all_caps is not None:
                        result["all_caps"] = bool(all_caps)
                    
                    # Get alignment from paragraph
                    try:
                        align = p.alignment
                        if align == WD_ALIGN_PARAGRAPH.CENTER:
                            result["align"] = "center"
                        elif align == WD_ALIGN_PARAGRAPH.RIGHT:
                            result["align"] = "right"
                        elif align == WD_ALIGN_PARAGRAPH.LEFT:
                            result["align"] = "left"
                    except Exception:
                        pass
                    
                    return result
    
    return {}


def learn_cover_styles(input_path: str, config: Dict[str, Any], vision: bool = True) -> Dict[str, Any]:
    """Learn cover styles from an existing document.
    
    Uses AI vision detection to identify Title/Subtitle/Author elements visually,
    then finds the corresponding runs by matching text and extracts their style parameters.
    
    This correctly handles cases where multiple roles are in one paragraph
    (e.g., subtitle and author in same paragraph with different sizes).
    
    Returns:
        Dict with 'styles' (extracted params), 'detection' (role assignments), 'config_update' (new config section)
    """
    loader = Loader()
    doc = loader.open(input_path)
    
    # Run detection (same as in run_cover_pipeline)
    use_vision = bool(vision or (((config.get("cover", {}) or {}).get("vision", {}) or {}).get("enabled", False)))
    detection = None
    
    print(f"DEBUG learn_cover_styles: use_vision={use_vision}")
    
    if use_vision:
        try:
            from .vision import detect_cover_roles_vision
            detection = detect_cover_roles_vision(input_path, config)
            print(f"DEBUG learn_cover_styles: vision detection skip={detection.get('skip')}, warnings={detection.get('warnings')}")
            if detection.get("skip"):
                # Fallback to non-vision
                print("DEBUG learn_cover_styles: vision returned skip=True, falling back to heuristics")
                detection = detect_cover_roles(doc, config)
                detection["vision_fallback"] = True
        except Exception as e:
            print(f"DEBUG learn_cover_styles: vision exception: {e}, falling back to heuristics")
            detection = detect_cover_roles(doc, config)
            detection["vision_fallback"] = True
            detection.setdefault("warnings", []).append(f"vision_error: {e}")
    
    if detection is None:
        detection = detect_cover_roles(doc, config)
    
    if detection.get("skip"):
        return {
            "ok": False,
            "error": "Could not detect cover roles",
            "detection": detection,
            "styles": {},
            "config_update": {},
        }
    
    # Get cover paragraphs
    cover_idxs = detection.get("cover_paragraph_indices", [])
    cover_paras = [doc.paragraphs[i] for i in cover_idxs if i < len(doc.paragraphs)]
    
    extracted: Dict[str, Dict[str, Any]] = {
        "title": {},
        "subtitle": {},
        "author": {},
    }
    
    # If we have vision_items, use text matching to find exact runs
    # This handles cases where subtitle+author are in one paragraph
    vision_items = detection.get("vision_items", [])
    
    if vision_items:
        print(f"DEBUG learn_cover_styles: using vision_items for text matching, {len(vision_items)} items")
        for item in vision_items:
            role = item.get("role", "").lower()
            text = item.get("t_uc", "") or item.get("text", "")
            
            if role in ("title", "subtitle", "author") and text:
                print(f"DEBUG learn_cover_styles: vision item role={role}, text='{text[:40]}...'")
                params = _find_run_style_by_text(doc, cover_paras, text)
                if params and not extracted[role]:
                    extracted[role] = params
                    extracted[role]["_vision_text"] = text[:50]
    
    # Fallback: if vision_items didn't give us all roles, use paragraph-level extraction
    assignments = detection.get("assignments", {})
    role_to_key = {
        "Cover Title": "title",
        "Cover Subtitle": "subtitle",
        "Cover Author": "author",
    }
    
    for idx in cover_idxs:
        role = assignments.get(idx) or assignments.get(str(idx))
        if role and role in role_to_key:
            key = role_to_key[role]
            if not extracted[key]:  # Only if not already found via vision_items
                p = doc.paragraphs[idx]
                params = extract_style_params(p)
                if params:
                    extracted[key] = params
                    extracted[key]["_paragraph_index"] = idx
                    extracted[key]["_paragraph_text"] = (p.text or "")[:100]
    
    print(f"DEBUG learn_cover_styles: extracted styles = {extracted}")
    
    # Build config update structure
    config_update: Dict[str, Any] = {
        "cover": {
            "styles": {}
        }
    }
    
    for role_key in ("title", "subtitle", "author"):
        params = extracted.get(role_key, {})
        if params:
            # Remove internal fields
            clean_params = {k: v for k, v in params.items() if not k.startswith("_")}
            if clean_params:
                config_update["cover"]["styles"][role_key] = {
                    "font": clean_params
                }
    
    return {
        "ok": True,
        "detection": detection,
        "styles": extracted,
        "config_update": config_update,
    }


def _cluster_by_size(paras: List, delta_pct: float) -> List[List[int]]:
    if not paras:
        return []
    sizes = [_para_max_font_size_pt(p) for p in paras]
    clusters: List[List[int]] = []
    current: List[int] = []

    def similar(a: float, b: float) -> bool:
        if a == 0 or b == 0:
            return a == b
        return abs(a - b) <= max(a, b) * (delta_pct / 100.0)

    for i, sz in enumerate(sizes):
        if not current:
            current = [i]
        else:
            prev_sz = sizes[current[-1]]
            if similar(prev_sz, sz):
                current.append(i)
            else:
                clusters.append(current)
                current = [i]
    if current:
        clusters.append(current)
    clusters.sort(key=lambda idxs: sum(sizes[i] for i in idxs) / max(len(idxs), 1), reverse=True)
    return clusters


def detect_cover_roles(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = config.get("cover", {})
    detect_cfg = cfg.get("detect", {})
    author_markers = [_uc(x) for x in detect_cfg.get("author_markers", [])]
    year_rx = re.compile(detect_cfg.get("year_regex", r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b"))
    max_non_empty = int(detect_cfg.get("max_non_empty", 25))
    delta = float(detect_cfg.get("size_delta_pct", 10))

    cover_paras, found_break = _collect_cover_paragraphs(doc)

    warnings: List[str] = []
    if not cover_paras or not found_break:
        warnings.append("no_page_break_found_or_empty_cover")
        return {
            "cover_paragraph_indices": [],
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
        }

    cand_idxs = [i for i, p in enumerate(cover_paras) if not _is_empty_para(p) and not _is_decorative_line(p.text)]
    cands = [cover_paras[i] for i in cand_idxs]

    clusters = _cluster_by_size(cands, delta)
    role_map: Dict[int, str] = {}

    clusters_info: List[Dict[str, Any]] = []
    sizes = [_para_max_font_size_pt(p) for p in cands]
    if all(sz == 0.0 for sz in sizes) and cands:
        warnings.append("all_effective_font_sizes_zero")
        return {
            "cover_paragraph_indices": [int(i) for i in range(len(cover_paras))],
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
        }
    for cl in clusters:
        avg = sum(sizes[i] for i in cl) / max(len(cl), 1)
        clusters_info.append({"indices": [cand_idxs[i] for i in cl], "avg_size_pt": avg})

    # Multi-line Title grouping: include adjacent lines with size within tolerance of max
    title_within_pct = float(detect_cfg.get("title_within_pct", 12.0))
    max_size = max(sizes) if sizes else 0.0
    # positions in cand list that qualify for title by size
    title_pos = [pos for pos, sz in enumerate(sizes) if max_size > 0 and sz >= max_size * (1 - title_within_pct / 100.0)]
    # group contiguous positions
    title_groups: List[List[int]] = []
    cur: List[int] = []
    for pos in title_pos:
        if not cur or pos == cur[-1] - 1 or pos == cur[-1] + 1:
            if not cur or pos == cur[-1] + 1:
                cur.append(pos)
            elif pos == cur[-1] - 1:
                # unlikely since title_pos is increasing, but keep safety
                cur.append(pos)
        else:
            title_groups.append(cur)
            cur = [pos]
    if cur:
        title_groups.append(cur)
    # choose the topmost group (smallest cand index)
    title_block_abs: List[int] = []
    if title_groups:
        title_group = min(title_groups, key=lambda g: cand_idxs[g[0]])
        for pos in title_group:
            abs_idx = cand_idxs[pos]
            role_map[abs_idx] = "Cover Title"
            title_block_abs.append(abs_idx)

    # Extend Title block downward to include adjacent centered/caps lines (safeguarded)
    if title_block_abs:
        title_block_abs.sort()
        max_title_sz = max((_para_max_font_size_pt(cover_paras[i]) for i in title_block_abs), default=0.0)
        # scan following candidate positions after the last title index
        last_title_abs = title_block_abs[-1]
        # find its position in cand_idxs ordering
        if last_title_abs in cand_idxs:
            start_pos = cand_idxs.index(last_title_abs) + 1
            added = 0
            while start_pos < len(cand_idxs) and added < 3:
                idx_abs = cand_idxs[start_pos]
                p = cover_paras[idx_abs]
                t_uc = _uc(_norm_text(p.text))
                # stop if author markers/year encountered
                if any(m in t_uc for m in author_markers) or bool(year_rx.search(t_uc)):
                    break
                # consider decorative/empty as gap and continue scanning further
                if _is_empty_para(p) or _is_decorative_line(p.text):
                    start_pos += 1
                    continue
                sz = _para_max_font_size_pt(p)
                caps = _uppercase_ratio(t_uc)
                centered = _is_centered(p)
                # Relaxed rule: strong ALL-CAPS can join Title even if smaller or not explicitly centered
                if (centered and (sz >= max_title_sz * 0.6 or caps >= 0.6)) or (caps >= 0.8):
                    role_map[idx_abs] = "Cover Title"
                    title_block_abs.append(idx_abs)
                    added += 1
                    start_pos += 1
                    continue
                break

    # Prepare sets used by later steps
    title_set = set(k for k, v in role_map.items() if v == "Cover Title")
    last_idx = max(role_map.keys(), default=-1)

    prefer_center = bool(detect_cfg.get("prefer_center", True))
    min_title_upper = float(detect_cfg.get("min_title_upper_pct", 0.0))

    def is_author_para(p) -> bool:
        t = _uc(_norm_text(p.text))
        if any(m in t for m in author_markers):
            return True
        if bool(re.match(r"^[A-Z .,'\-]+$", t)) and len(t) <= 60:
            return True
        return False

    # Find Author after Title block; prefer markers/year; do not override Title/Sub
    best_idx = None
    best_score = -1
    # compute a search start after last title line
    search_start = 0
    if title_block_abs:
        last_t = max(title_block_abs)
        if last_t in cand_idxs:
            search_start = cand_idxs.index(last_t) + 1
    for pos in range(search_start, len(cand_idxs)):
        idx = cand_idxs[pos]
        # skip only Title; allow overriding a tentative Subtitle if strong Author evidence
        if idx in title_set or role_map.get(idx) == "Cover Title":
            continue
        p = cover_paras[idx]
        t_uc = _uc(_norm_text(p.text))
        if not t_uc:
            continue
        score = 0
        if any(m in t_uc for m in author_markers):
            score += 3
        if bool(year_rx.search(t_uc)):
            score += 1
        # simple name-like pattern (allow ALL CAPS names as fallback)
        if bool(re.match(r"^[A-Z][A-Za-z .,'\-]+$", t_uc)) and len(t_uc) <= 60:
            score += 1
        # Prefer smaller-than-title sizes slightly (best-effort)
        try:
            sz = _para_max_font_size_pt(p)
            if title_block_abs:
                max_title_sz = max(_para_max_font_size_pt(cover_paras[i]) for i in title_block_abs)
                if sz < max_title_sz:
                    score += 1
        except Exception:
            pass
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_idx is not None and best_score >= 2:  # require stronger evidence (marker/year/name+smaller)
        role_map[best_idx] = "Cover Author"

        t_self = _uc(_norm_text(cover_paras[best_idx].text))
        marker_only = any((m == t_self) for m in author_markers if m)
        self_has_year = bool(t_self and year_rx.search(t_self))
        self_name_like = bool(re.match(r"^[A-Z][A-Za-z .,'\-]+$", t_self)) and len(t_self) <= 60

        extend = marker_only or (not self_has_year and not self_name_like)
        if extend:
            added_any = False
            for j in range(best_idx + 1, min(best_idx + 4, len(cover_paras))):
                p2 = cover_paras[j]
                if _is_empty_para(p2) or _is_decorative_line(p2.text):
                    continue
                t2 = _uc(_norm_text(p2.text))
                if not t2:
                    continue
                is_year = bool(year_rx.search(t2)) and len(re.sub(r"\D", "", t2)) == 4
                is_name = bool(re.match(r"^[A-Z][A-Za-z .,'\-]+$", t2)) and len(t2) <= 80
                is_marker = any((m == t2) for m in author_markers if m)
                if is_year or is_name or is_marker:
                    role_map[j] = "Cover Author"
                    added_any = True
                    if is_year:
                        break
                    continue
                if added_any:
                    break
        else:
            if not self_has_year and best_idx + 1 < len(cover_paras):
                t_next = _uc(_norm_text(cover_paras[best_idx + 1].text))
                if t_next and year_rx.search(t_next) and len(re.sub(r"\D", "", t_next)) == 4:
                    role_map[best_idx + 1] = "Cover Author"

    # Subtitle from remaining candidates via clusters, excluding title and author indices
    title_author_set = set(k for k, v in role_map.items() if v in ("Cover Title", "Cover Author"))
    rem_positions = [i for i, idx in enumerate(cand_idxs) if idx not in title_author_set]
    if rem_positions:
        rem_sizes = [sizes[i] for i in rem_positions]
        # build clusters on remaining by reusing similarity on rem_positions order
        rem_clusters: List[List[int]] = []
        rem_cur: List[int] = []
        def similar(a: float, b: float) -> bool:
            if a == 0 or b == 0:
                return a == b
            return abs(a - b) <= max(a, b) * (delta / 100.0)
        for j, sz in enumerate(rem_sizes):
            if not rem_cur:
                rem_cur = [rem_positions[j]]
            else:
                prev_sz = sizes[rem_cur[-1]]
                if similar(prev_sz, sz):
                    rem_cur.append(rem_positions[j])
                else:
                    rem_clusters.append(rem_cur)
                    rem_cur = [rem_positions[j]]
        if rem_cur:
            rem_clusters.append(rem_cur)
        # pick the cluster with highest average size as subtitle
        if rem_clusters:
            rem_clusters.sort(key=lambda idxs: sum(sizes[i] for i in idxs) / max(len(idxs), 1), reverse=True)
            subtitle_cluster = rem_clusters[0]
            for pos in subtitle_cluster:
                role_map[cand_idxs[pos]] = "Cover Subtitle"

    # small refinement: if title lines are not centered and subtitle lines are centered, prefer centered ones for title/subtitle roles
    if prefer_center:
        def centered(idx: int) -> bool:
            try:
                return cover_paras[idx].alignment == WD_ALIGN_PARAGRAPH.CENTER
            except Exception:
                return False
        # promote centered lines within first two clusters
        for idx in list(role_map.keys()):
            if role_map[idx] in ("Cover Title", "Cover Subtitle") and not centered(idx):
                # search nearby line in same cluster that is centered
                pass

    # warn if uppercase ratio very low for title cluster
    title_idxs = [k for k, v in role_map.items() if v == "Cover Title"]
    if min_title_upper > 0 and title_idxs:
        ratios = [_uppercase_ratio(_norm_text(cover_paras[i].text)) for i in title_idxs]
        if ratios and max(ratios) < min_title_upper:
            warnings.append("title_uppercase_ratio_low")

    return {
        "cover_paragraph_indices": list(range(len(cover_paras))),
        "assignments": {int(k): v for k, v in role_map.items()},
        "clusters": clusters_info,
        "warnings": warnings,
        "skip": False,
    }


def apply_cover_styles(doc: Document, detection: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    cover_cfg = config.get("cover", {})
    styles_cfg = cover_cfg.get("styles", {})
    norm_cfg = cover_cfg.get("normalize", {})

    title_style = _ensure_paragraph_style(doc, styles_cfg.get("title", {}).get("name", "Cover Title"), styles_cfg.get("title", {}).get("font", {}))
    subtitle_style = _ensure_paragraph_style(doc, styles_cfg.get("subtitle", {}).get("name", "Cover Subtitle"), styles_cfg.get("subtitle", {}).get("font", {}))
    author_style = _ensure_paragraph_style(doc, styles_cfg.get("author", {}).get("name", "Cover Author"), styles_cfg.get("author", {}).get("font", {}))

    assignments: Dict[int, str] = {int(k): v for k, v in detection.get("assignments", {}).items()}
    cover_idxs: List[int] = detection.get("cover_paragraph_indices", [])

    clear_roles = (norm_cfg.get("clear_direct_formatting_on_roles", {}) or {})
    clear_title = bool(clear_roles.get("title", True))
    clear_subtitle = bool(clear_roles.get("subtitle", False))
    clear_author = bool(clear_roles.get("author", False))

    def _clear_runs(p):
        for r in p.runs:
            try:
                r.style = None
            except Exception:
                pass
            f = r.font
            try:
                f.size = None
            except Exception:
                pass
            try:
                f.bold = None
            except Exception:
                pass
            try:
                f.italic = None
            except Exception:
                pass
            try:
                f.all_caps = None
            except Exception:
                pass
            try:
                f.small_caps = None
            except Exception:
                pass

    changed: List[Tuple[int, str]] = []
    for i in cover_idxs:
        p = doc.paragraphs[i]
        role = assignments.get(i)
        if role == "Cover Title":
            p.style = title_style
            if clear_title:
                _clear_runs(p)
        elif role == "Cover Subtitle":
            p.style = subtitle_style
            if clear_subtitle:
                _clear_runs(p)
        elif role == "Cover Author":
            p.style = author_style
            if clear_author:
                _clear_runs(p)
        else:
            if norm_cfg.get("collapse_misc_to_normal", True):
                p.style = doc.styles["Normal"]
        if role:
            changed.append((i, role))

    return {"changed": changed}


def _ensure_output_path(out_dir: str, input_path: str, versioning: bool = False) -> str:
    base = os.path.splitext(os.path.basename(input_path))[0]
    candidate = os.path.join(out_dir, f"{base}.docx")
    if not versioning:
        return candidate
    if not os.path.exists(candidate):
        return candidate
    i = 1
    while True:
        suffix = f"_v_{i:02d}"
        cand = os.path.join(out_dir, f"{base}{suffix}.docx")
        if not os.path.exists(cand):
            return cand
        i += 1


def run_cover_pipeline(input_path: str, config: Dict[str, Any], out_dir: str, dry_run: bool = False, no_layout: bool = False, vision: bool = False, footer_style_overrides: Dict[str, Any] = None) -> Dict[str, Any]:
    loader = Loader()
    doc = loader.open(input_path)

    use_vision = bool(vision or (((config.get("cover", {}) or {}).get("vision", {}) or {}).get("enabled", False)))
    detection = None
    if use_vision:
        try:
            from .vision import detect_cover_roles_vision
            detection = detect_cover_roles_vision(input_path, config)
            # If vision failed (skip=True), fallback to non-vision detection
            if detection.get("skip"):
                vision_warnings = detection.get("warnings", [])
                print(f"DEBUG: Vision detection failed with warnings={vision_warnings}, falling back to non-vision")
                detection = detect_cover_roles(doc, config)
                detection["vision_fallback"] = True
                detection.setdefault("warnings", []).extend(["vision_fallback"] + vision_warnings)
        except Exception as e:
            print(f"DEBUG: Vision exception: {e}, falling back to non-vision")
            detection = detect_cover_roles(doc, config)
            detection["vision_fallback"] = True
            detection.setdefault("warnings", []).extend(["vision_exception", str(e)])
    
    if detection is None:
        detection = detect_cover_roles(doc, config)
    applied = {"changed": []}
    if not detection.get("skip"):
        applied = apply_cover_styles(doc, detection, config)

    cover_idxs = detection.get("cover_paragraph_indices", [])
    last_cover_idx = max(cover_idxs) if cover_idxs else 0
    first_body_idx = min(last_cover_idx + 1, len(doc.paragraphs) - 1)

    if not no_layout and not detection.get("skip"):
        apply_sections_and_numbering(doc, config, last_cover_idx, first_body_idx, footer_style_overrides)

    os.makedirs(out_dir, exist_ok=True)
    out_cfg = (config or {}).get("output", {})
    versioning = bool(out_cfg.get("versioning", False))
    out_path = _ensure_output_path(out_dir, input_path, versioning=versioning)

    saved_path = None
    # Always save when not dry_run - user expects a file to download
    if not dry_run:
        saved_path = loader.save(doc, out_path)
    else:
        # Dry run mode - don't save, just analyze
        try:
            w = detection.get("warnings")
            if isinstance(w, list):
                w.append("dry_run_not_saved")
            else:
                detection["warnings"] = ["dry_run_not_saved"]
        except Exception:
            pass

    return {
        "detection": detection,
        "applied": applied,
        "output_path": saved_path,
        "dry_run": dry_run,
        "layout_applied": not no_layout,
    }
