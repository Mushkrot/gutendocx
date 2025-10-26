from typing import Dict, Any

from .loader import Loader


def _style_key(style) -> str:
    if style is None:
        return "None"
    # python-docx Style has .style_id and .name; use id if available
    sid = getattr(style, "style_id", None)
    if sid:
        return str(sid)
    name = getattr(style, "name", None)
    return str(name) if name else "Unknown"


def _style_name(style) -> str:
    if style is None:
        return "None"
    name = getattr(style, "name", None)
    if name:
        return str(name)
    sid = getattr(style, "style_id", None)
    return str(sid) if sid else "Unknown"


def _has_run_overrides(run) -> bool:
    f = run.font
    # If any direct formatting property is explicitly set (not None)
    return any(
        v is not None
        for v in (
            run.bold,
            run.italic,
            run.underline,
            getattr(f, "name", None),
            getattr(f, "size", None),
            getattr(f, "color", None),
            getattr(f, "all_caps", None),
            getattr(f, "small_caps", None),
        )
    )


def _has_paragraph_overrides(paragraph) -> bool:
    pf = paragraph.paragraph_format
    para_over = any(
        v is not None
        for v in (
            getattr(pf, "left_indent", None),
            getattr(pf, "right_indent", None),
            getattr(pf, "first_line_indent", None),
            getattr(pf, "space_before", None),
            getattr(pf, "space_after", None),
            getattr(pf, "line_spacing", None),
            getattr(paragraph, "alignment", None),
        )
    )
    run_over = any(_has_run_overrides(r) for r in paragraph.runs)
    return para_over or run_over


def prescan(input_path: str, max_samples: int = 3) -> Dict[str, Any]:
    loader = Loader()
    doc = loader.open(input_path)

    paragraph_styles: Dict[str, Dict[str, Any]] = {}
    character_styles: Dict[str, Dict[str, Any]] = {}
    table_styles: Dict[str, Dict[str, Any]] = {}

    para_total = 0
    run_total = 0
    table_total = 0

    # Paragraphs
    for p in doc.paragraphs:
        para_total += 1
        skey = _style_key(p.style)
        sname = _style_name(p.style)
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

        # Character styles from runs
        for r in p.runs:
            run_total += 1
            if r.style is not None:
                ckey = _style_key(r.style)
                cname = _style_name(r.style)
                crec = character_styles.setdefault(
                    ckey, {"name": cname, "count": 0, "samples": []}
                )
                crec["count"] += 1
                rtxt = (r.text or "").strip()
                if rtxt and len(crec["samples"]) < max_samples:
                    crec["samples"].append(rtxt)

    # Tables
    for t in getattr(doc, "tables", []):
        table_total += 1
        skey = _style_key(getattr(t, "style", None))
        sname = _style_name(getattr(t, "style", None))
        trec = table_styles.setdefault(skey, {"name": sname, "count": 0})
        trec["count"] += 1

    # Sort dictionaries by count descending for readability
    def _sorted(d: Dict[str, Dict[str, Any]]):
        return dict(
            sorted(d.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)
        )

    inventory = {
        "paragraph": _sorted(paragraph_styles),
        "character": _sorted(character_styles),
        "table": _sorted(table_styles),
        "summary": {
            "paragraph_total": para_total,
            "run_total": run_total,
            "table_total": table_total,
        },
        "likely_roles": {},
    }

    return inventory
