from __future__ import annotations

from typing import Any, Dict

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _add_section_break_next_page_to_paragraph(paragraph, start_number: int | None = None):
    p = paragraph._p
    pPr = p.get_or_add_pPr()
    sectPr = OxmlElement("w:sectPr")
    # <w:type w:val="nextPage"/>
    typ = OxmlElement("w:type")
    typ.set(qn("w:val"), "nextPage")
    sectPr.append(typ)
    if start_number is not None:
        # <w:pgNumType w:start="N"/>
        pg = OxmlElement("w:pgNumType")
        pg.set(qn("w:start"), str(int(start_number)))
        sectPr.append(pg)
    pPr.append(sectPr)


def _clear_footer(paragraph_container):
    # Remove all content from a footer body
    for p in list(paragraph_container.paragraphs):
        p._element.getparent().remove(p._element)


def _add_page_field(paragraph):
    # Builds a PAGE field: { PAGE }
    r = paragraph.add_run()
    fldBegin = OxmlElement("w:fldChar")
    fldBegin.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = " PAGE "
    fldSeparate = OxmlElement("w:fldChar")
    fldSeparate.set(qn("w:fldCharType"), "separate")
    fldEnd = OxmlElement("w:fldChar")
    fldEnd.set(qn("w:fldCharType"), "end")

    r._r.append(fldBegin)
    r._r.append(instrText)
    r._r.append(fldSeparate)
    r._r.append(fldEnd)


def ensure_update_fields_on_open(doc: Document, config: Dict[str, Any]) -> bool:
    """Ensure the document has w:updateFields set according to config.

    When layout.update_fields_on_open is true (default), Word will be
    instructed to update fields such as TOC on document open.
    """

    layout_cfg = ((config or {}).get("layout", {}) or {})
    flag = layout_cfg.get("update_fields_on_open", True)

    try:
        settings = doc.settings
        element = settings.element
    except Exception:
        return False

    try:
        nodes = element.xpath("./w:updateFields")
    except Exception:
        nodes = []

    node = None
    if nodes:
        node = nodes[0]
        for extra in nodes[1:]:
            try:
                extra.getparent().remove(extra)
            except Exception:
                pass
    if node is None:
        node = OxmlElement("w:updateFields")
        element.append(node)

    try:
        node.set(qn("w:val"), "true" if bool(flag) else "false")
    except Exception:
        return False

    return True


def apply_sections_and_numbering(doc: Document, config: Dict[str, Any], last_cover_para_index: int, first_body_para_index: int) -> None:
    """Create three logical sections:
    A) Cover (page 1, no number)
    B) Blank page (page 1 of numbering but not printed)
    C) Body (continues; PAGE prints starting from 2 on physical page 3)

    We insert section breaks:
    - after last cover paragraph (start=1 for numbering for Section B)
    - at the first body paragraph (nextPage) to start Section C
    Then we add PAGE field only to the last section's footer.
    """
    numbering = (config or {}).get("layout", {}).get("numbering", {})
    start_val = int(numbering.get("page2_start_value", 1))
    print_on_page2 = bool(numbering.get("print_on_page2", False))

    # Section break after cover -> Section B starts next page, numbering start
    last_cover_p = doc.paragraphs[last_cover_para_index]
    _add_section_break_next_page_to_paragraph(last_cover_p, start_number=start_val)

    # Section break at first body paragraph -> Section C on next page
    if 0 <= first_body_para_index < len(doc.paragraphs):
        first_body_p = doc.paragraphs[first_body_para_index]
        _add_section_break_next_page_to_paragraph(first_body_p, start_number=None)

    # After modifying sectPr manually, python-docx will expose sections in order
    sections = doc.sections

    # Ensure first-page footer has no PAGE (cover)
    if len(sections) >= 1:
        secA = sections[0]
        _clear_footer(secA.footer)

    # Section B (blank page): optionally print number (default false)
    if len(sections) >= 2:
        secB = sections[1]
        _clear_footer(secB.footer)
        if print_on_page2:
            p = secB.footer.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_page_field(p)

    # Section C (body): always print PAGE centered
    if len(sections) >= 3:
        secC = sections[2]
        _clear_footer(secC.footer)
        p = secC.footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_page_field(p)
