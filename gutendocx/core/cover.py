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

    cover_paras = []
    found_break = False
    for p in doc.paragraphs:
        if _has_page_or_section_break(p):
            cover_paras.append(p)  # include the paragraph that contains the break
            found_break = True
            break
        cover_paras.append(p)

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

    if clusters:
        title_cluster = clusters[0]
        for idx in title_cluster:
            role_map[cand_idxs[idx]] = "Cover Title"

    if len(clusters) > 1:
        subtitle_cluster = clusters[1]
        for idx in subtitle_cluster:
            role_map[cand_idxs[idx]] = "Cover Subtitle"

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

    # Find best author line anywhere on the cover (not only after title/subtitle)
    best_idx = None
    best_score = -1
    for idx in cand_idxs:
        p = cover_paras[idx]
        t_uc = _uc(_norm_text(p.text))
        if not t_uc:
            continue
        score = 0
        if any(m in t_uc for m in author_markers):
            score += 2
        if bool(re.match(r"^[A-Z .,'\-]+$", t_uc)) and len(t_uc) <= 60:
            score += 1
        # Prefer smaller-than-title sizes slightly
        try:
            sz = _para_max_font_size_pt(p)
            if title_idxs:
                max_title_sz = max(_para_max_font_size_pt(cover_paras[i]) for i in title_idxs)
                if sz < max_title_sz:
                    score += 1
        except Exception:
            pass
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_idx is not None and best_score >= 1:
        role_map[best_idx] = "Cover Author"
        # attach year on same line or next line
        t_self = _norm_text(cover_paras[best_idx].text)
        if t_self and year_rx.search(t_self):
            pass
        elif best_idx + 1 < len(cover_paras):
            t_next = _norm_text(cover_paras[best_idx + 1].text)
            if t_next and year_rx.search(t_next):
                role_map[best_idx + 1] = "Cover Author"

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

    changed: List[Tuple[int, str]] = []
    for i in cover_idxs:
        p = doc.paragraphs[i]
        role = assignments.get(i)
        if role == "Cover Title":
            p.style = title_style
        elif role == "Cover Subtitle":
            p.style = subtitle_style
        elif role == "Cover Author":
            p.style = author_style
        else:
            if norm_cfg.get("collapse_misc_to_normal", True):
                p.style = doc.styles["Normal"]
        if role:
            changed.append((i, role))

    return {"changed": changed}


def _ensure_output_path(out_dir: str, input_path: str, versioning: bool = True) -> str:
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


def run_cover_pipeline(input_path: str, config: Dict[str, Any], out_dir: str, dry_run: bool = False, no_layout: bool = False) -> Dict[str, Any]:
    loader = Loader()
    doc = loader.open(input_path)

    detection = detect_cover_roles(doc, config)
    applied = {"changed": []}
    if not detection.get("skip"):
        applied = apply_cover_styles(doc, detection, config)

    cover_idxs = detection.get("cover_paragraph_indices", [])
    last_cover_idx = max(cover_idxs) if cover_idxs else 0
    first_body_idx = min(last_cover_idx + 1, len(doc.paragraphs) - 1)

    if not no_layout and not detection.get("skip"):
        apply_sections_and_numbering(doc, config, last_cover_idx, first_body_idx)

    os.makedirs(out_dir, exist_ok=True)
    out_cfg = (config or {}).get("output", {})
    versioning = bool(out_cfg.get("versioning", True))
    out_path = _ensure_output_path(out_dir, input_path, versioning=versioning)

    saved_path = None
    if not dry_run:
        saved_path = loader.save(doc, out_path)

    return {
        "detection": detection,
        "applied": applied,
        "output_path": saved_path or out_path,
        "dry_run": dry_run,
        "layout_applied": not no_layout,
    }
