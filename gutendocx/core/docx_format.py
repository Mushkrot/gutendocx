from __future__ import annotations

from typing import Any, Dict

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def text_style_from_override(override: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return the font-level subset used for direct run/style repair."""
    if not isinstance(override, dict):
        return {}
    out: Dict[str, Any] = {}
    family = override.get("font_family") or override.get("family") or override.get("font")
    if isinstance(family, str) and family.strip():
        out["font_family"] = family.strip()
    size_pt = override.get("size_pt")
    if isinstance(size_pt, (int, float)) and size_pt > 0:
        out["size_pt"] = float(size_pt)
    for key in ("bold", "italic"):
        if key in override:
            out[key] = bool(override.get(key))
    return out


def has_text_style(style: Dict[str, Any] | None) -> bool:
    return isinstance(style, dict) and any(key in style for key in ("font_family", "size_pt", "bold", "italic"))


def _get_or_add(parent, tag: str):
    node = parent.find(qn(f"w:{tag}"))
    if node is None:
        node = OxmlElement(f"w:{tag}")
        parent.append(node)
    return node


def _set_bool(rpr, tag: str, value: bool) -> None:
    node = _get_or_add(rpr, tag)
    node.set(qn("w:val"), "1" if bool(value) else "0")


def _apply_text_style_to_rpr(rpr, style: Dict[str, Any]) -> None:
    family = style.get("font_family")
    if family:
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.insert(0, rfonts)
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            rfonts.set(qn(f"w:{attr}"), str(family))
        for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "csTheme"):
            rfonts.attrib.pop(qn(f"w:{attr}"), None)

    if "size_pt" in style:
        half_points = str(int(round(float(style["size_pt"]) * 2)))
        _get_or_add(rpr, "sz").set(qn("w:val"), half_points)
        _get_or_add(rpr, "szCs").set(qn("w:val"), half_points)

    if "bold" in style:
        value = bool(style.get("bold"))
        _set_bool(rpr, "b", value)
        _set_bool(rpr, "bCs", value)

    if "italic" in style:
        value = bool(style.get("italic"))
        _set_bool(rpr, "i", value)
        _set_bool(rpr, "iCs", value)


def apply_text_style_to_run_element(run_el, style: Dict[str, Any]) -> bool:
    """Apply font-level formatting to an existing ``w:r`` XML element."""
    if not has_text_style(style):
        return False
    rpr = run_el.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        run_el.insert(0, rpr)
    _apply_text_style_to_rpr(rpr, style)
    return True


def apply_text_style_to_style(style_obj, style: Dict[str, Any]) -> bool:
    """Apply font-level formatting to a Word style object."""
    if not has_text_style(style):
        return False
    font = getattr(style_obj, "font", None)
    if font is not None:
        if style.get("font_family"):
            font.name = str(style["font_family"])
        if "size_pt" in style:
            font.size = Pt(float(style["size_pt"]))
        if "bold" in style:
            font.bold = bool(style["bold"])
        if "italic" in style:
            font.italic = bool(style["italic"])

    element = getattr(style_obj, "_element", None)
    if element is None:
        return True
    rpr = element.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        element.append(rpr)
    _apply_text_style_to_rpr(rpr, style)
    return True


def run_has_visible_text(run_el) -> bool:
    if run_el.find(qn("w:instrText")) is not None or run_el.find(qn("w:fldChar")) is not None:
        return False
    texts = run_el.findall(qn("w:t"))
    return any((text.text or "").strip() for text in texts)


def style_name_by_id(doc) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        styles = doc.styles
    except Exception:
        return out
    for style in styles:
        try:
            sid = str(getattr(style, "style_id", "") or "")
            name = str(getattr(style, "name", "") or "")
        except Exception:
            continue
        if sid:
            out[sid] = name
    return out
