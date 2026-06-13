from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


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


def _clear_footer(footer):
    """Remove all content from a footer completely.
    
    This removes all child elements from the footer XML, not just paragraphs.
    This ensures no duplicate content remains.
    """
    # Get the XML element of the footer
    footer_element = footer._element
    # Remove all children (paragraphs, tables, etc.)
    for child in list(footer_element):
        footer_element.remove(child)


def _set_rpr_bool(rpr, tag: str, value: bool) -> None:
    node = rpr.find(qn(f"w:{tag}"))
    if node is None:
        node = OxmlElement(f"w:{tag}")
        rpr.append(node)
    node.set(qn("w:val"), "1" if bool(value) else "0")


def _apply_page_run_style(run, style_overrides: Optional[Dict[str, Any]] = None) -> None:
    """Apply page-number text formatting directly to a run."""
    if not style_overrides:
        return

    from docx.shared import Pt

    rpr = run._r.get_or_add_rPr()
    font_family = style_overrides.get("font_family")
    if font_family:
        run.font.name = str(font_family)
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.insert(0, rfonts)
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            rfonts.set(qn(f"w:{attr}"), str(font_family))

    size_pt = style_overrides.get("size_pt")
    if size_pt:
        run.font.size = Pt(float(size_pt))
        sz_cs = rpr.find(qn("w:szCs"))
        if sz_cs is None:
            sz_cs = OxmlElement("w:szCs")
            rpr.append(sz_cs)
        sz_cs.set(qn("w:val"), str(int(round(float(size_pt) * 2))))

    if "bold" in style_overrides:
        run.font.bold = bool(style_overrides.get("bold"))
        _set_rpr_bool(rpr, "bCs", bool(style_overrides.get("bold")))
    if "italic" in style_overrides:
        run.font.italic = bool(style_overrides.get("italic"))
        _set_rpr_bool(rpr, "iCs", bool(style_overrides.get("italic")))


def _add_page_field(paragraph, style_overrides: Optional[Dict[str, Any]] = None):
    """Builds a PAGE field: { PAGE } with optional style overrides.
    
    Args:
        paragraph: The paragraph to add the page field to
        style_overrides: Optional dict with keys:
            - font_family: str
            - size_pt: float
            - bold: bool
            - italic: bool
    """
    fldBegin = OxmlElement("w:fldChar")
    fldBegin.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = " PAGE \\* MERGEFORMAT "
    fldSeparate = OxmlElement("w:fldChar")
    fldSeparate.set(qn("w:fldCharType"), "separate")
    fldEnd = OxmlElement("w:fldChar")
    fldEnd.set(qn("w:fldCharType"), "end")

    begin_run = paragraph.add_run()
    _apply_page_run_style(begin_run, style_overrides)
    begin_run._r.append(fldBegin)

    instr_run = paragraph.add_run()
    _apply_page_run_style(instr_run, style_overrides)
    instr_run._r.append(instrText)

    separate_run = paragraph.add_run()
    _apply_page_run_style(separate_run, style_overrides)
    separate_run._r.append(fldSeparate)

    # Seed a styled result run so Word/LibreOffice have visible text
    # formatting to preserve when updating the PAGE field.
    result_run = paragraph.add_run("1")
    _apply_page_run_style(result_run, style_overrides)

    end_run = paragraph.add_run()
    _apply_page_run_style(end_run, style_overrides)
    end_run._r.append(fldEnd)


def restyle_footer_page_numbers(docx_path: str, config: Dict[str, Any], footer_style_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Re-apply page-number footer styling to an existing DOCX file."""
    doc = Document(docx_path)
    result = apply_footer_styles(doc, config, footer_style_overrides)
    doc.save(docx_path)
    result["output_path"] = docx_path
    result["saved"] = True
    return result

def _has_explicit_page_break(p) -> bool:
    """Check for explicit page break (<w:br w:type="page"/>)."""
    el = p._element
    try:
        if el.xpath('.//w:br[@w:type="page"]'):
            return True
    except Exception:
        return False
    return False


def _has_section_break(p) -> bool:
    """Check if paragraph has a section break in its pPr."""
    el = p._element
    try:
        if el.xpath('./w:pPr/w:sectPr'):
            return True
    except Exception:
        return False
    return False


def _get_section_page_start(sectPr) -> Optional[int]:
    """Get the pgNumType start value from a sectPr element."""
    try:
        pgNumType = sectPr.find(f'{{{W_NS}}}pgNumType')
        if pgNumType is not None:
            start = pgNumType.get(f'{{{W_NS}}}start')
            if start is not None:
                return int(start)
    except Exception:
        pass
    return None


def _remove_page_break_from_paragraph(p) -> bool:
    """Remove <w:br w:type="page"/> from paragraph. Returns True if removed."""
    removed = False
    try:
        for br in p._element.xpath('.//w:br[@w:type="page"]'):
            br.getparent().remove(br)
            removed = True
    except Exception:
        pass
    return removed


def analyze_document_sections(doc: Document) -> Dict[str, Any]:
    """Analyze document structure for sections, page breaks, and numbering.
    
    Returns info about:
    - Number of sections
    - Page break locations
    - Section break locations with their pgNumType settings
    - Whether body section has proper numbering restart
    """
    result = {
        "section_count": len(doc.sections),
        "page_breaks": [],
        "section_breaks": [],
        "body_section_pgNumType_start": None,
        "body_has_numbering_restart": False,
        "needs_section_fix": False,
    }
    
    # Find page breaks and section breaks in paragraphs
    for idx, p in enumerate(doc.paragraphs):
        if _has_explicit_page_break(p):
            result["page_breaks"].append(idx)
        if _has_section_break(p):
            pPr = p._element.find(f'{{{W_NS}}}pPr')
            if pPr is not None:
                sectPr = pPr.find(f'{{{W_NS}}}sectPr')
                if sectPr is not None:
                    start = _get_section_page_start(sectPr)
                    result["section_breaks"].append({
                        "paragraph_index": idx,
                        "pgNumType_start": start
                    })
    
    # Check the BODY section (last section, document-level sectPr) for numbering
    # This is the correct place to check - body section's pgNumType determines TOC numbering
    if len(doc.sections) >= 1:
        body_sectPr = doc.sections[-1]._sectPr
        body_start = _get_section_page_start(body_sectPr)
        result["body_section_pgNumType_start"] = body_start
        result["body_has_numbering_restart"] = body_start is not None
    
    # We need a fix if:
    # 1. There are page breaks (indicating cover/blank structure)
    # 2. Body section doesn't have numbering restart
    page_breaks = result["page_breaks"]
    if len(page_breaks) >= 1:
        result["needs_section_fix"] = not result["body_has_numbering_restart"]
    
    return result


def _set_section_page_start(sectPr, start_number: int) -> None:
    """Set pgNumType start on a sectPr element."""
    # Remove existing pgNumType if present
    for existing in sectPr.findall(f'{{{W_NS}}}pgNumType'):
        sectPr.remove(existing)
    # Add new pgNumType
    pgNumType = OxmlElement("w:pgNumType")
    pgNumType.set(qn("w:start"), str(start_number))
    sectPr.append(pgNumType)


def ensure_body_section_with_numbering(doc: Document, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """Ensure the body section has proper page numbering restart.
    
    This function:
    1. Finds the page break before body (blank->body transition)
    2. Converts it to a section break (ends cover+blank section)
    3. Sets pgNumType start=1 on the BODY section (document-level sectPr)
    
    Key insight: In DOCX, sectPr in paragraph defines the section ENDING at that
    paragraph. The document-level sectPr defines the LAST section (body).
    So we set pgNumType start=1 on doc.sections[-1]._sectPr for correct TOC.
    
    Returns dict with action taken and indices.
    """
    result = {
        "action": "none",
        "section_break_added_at": None,
    }
    
    # Check if body section already has a section break (skip if already processed)
    if len(doc.sections) >= 2:
        result["action"] = "already_has_multiple_sections"
        return result
    
    # Find page breaks (only first few, looking for cover->blank->body structure)
    page_break_indices = []
    for idx, p in enumerate(doc.paragraphs):
        if _has_explicit_page_break(p) and not _has_section_break(p):
            page_break_indices.append(idx)
            # We only need to find the first 2 page breaks (cover->blank, blank->body)
            if len(page_break_indices) >= 2:
                break
    
    if len(page_break_indices) < 1:
        result["action"] = "no_page_breaks_found"
        return result
    
    # Use the FIRST page break (cover->blank transition)
    # This preserves the second page break which creates the blank page
    # Document structure: Cover [break1+section] Blank [break2] Body
    target_idx = page_break_indices[0]
    target_para = doc.paragraphs[target_idx]
    
    # Check if this paragraph already has a section break
    if not _has_section_break(target_para):
        # Add section break WITHOUT pgNumType (just to separate cover+blank from body)
        # We do NOT restart page numbering - pages continue: 1 (cover), 2 (blank), 3+ (body)
        _add_section_break_next_page_to_paragraph(target_para, start_number=None)
        # Keep the page break - don't remove it, section break is in addition
        result["section_break_added_at"] = target_idx
    
    # Do NOT set pgNumType on body section - let page numbers continue naturally
    # Cover = page 1, Blank = page 2, Body starts at page 3
    result["action"] = "section_break_added_continuous_numbering"
    
    return result


def ensure_blank_page_after_cover(doc: Document, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """Ensure there is a blank page (page 2) after the cover.
    
    Document structure should be:
    - Page 1: Cover (ends with page/section break)
    - Page 2: Blank page (ends with page/section break)  
    - Page 3+: Body content
    
    This function checks for two page breaks and inserts a blank paragraph
    with page break if the blank page is missing.
    
    Returns dict with action taken.
    """
    result = {
        "action": "none",
        "blank_page_exists": False,
        "inserted_at": None,
    }
    
    # Find page breaks in first part of document
    page_break_indices = []
    for idx, p in enumerate(doc.paragraphs):
        if idx > 50:  # Only check first 50 paragraphs
            break
        if _has_explicit_page_break(p) or _has_section_break(p):
            page_break_indices.append(idx)
            if len(page_break_indices) >= 2:
                break
    
    if len(page_break_indices) < 1:
        result["action"] = "no_breaks_found"
        return result
    
    if len(page_break_indices) >= 2:
        # Two breaks found - blank page should exist
        first_break_idx = page_break_indices[0]
        second_break_idx = page_break_indices[1]
        
        # Check if there's at least one paragraph between breaks that is blank
        has_blank = False
        for idx in range(first_break_idx + 1, second_break_idx + 1):
            p = doc.paragraphs[idx]
            text = p.text.strip() if p.text else ""
            if not text:
                has_blank = True
                break
        
        if has_blank:
            result["action"] = "blank_page_already_exists"
            result["blank_page_exists"] = True
            return result
    
    # Only one break or no blank paragraph found - need to insert blank page
    # Insert after the first break (which ends the cover)
    insert_after_idx = page_break_indices[0]
    
    # Get the paragraph after which to insert
    if insert_after_idx + 1 < len(doc.paragraphs):
        # Insert a new blank paragraph with page break after the first break paragraph
        ref_para = doc.paragraphs[insert_after_idx]
        ref_element = ref_para._element
        
        # Create new paragraph element
        new_p = OxmlElement("w:p")
        # Add page break
        new_r = OxmlElement("w:r")
        new_br = OxmlElement("w:br")
        new_br.set(qn("w:type"), "page")
        new_r.append(new_br)
        new_p.append(new_r)
        
        # Insert after the reference paragraph
        ref_element.addnext(new_p)
        
        result["action"] = "blank_paragraph_inserted"
        result["inserted_at"] = insert_after_idx + 1
        result["blank_page_exists"] = True
    else:
        result["action"] = "could_not_insert"
    
    return result


def apply_sections_and_numbering(
    doc: Document, 
    config: Dict[str, Any], 
    last_cover_para_index: int, 
    first_body_para_index: int,
    footer_style_overrides: Optional[Dict[str, Any]] = None
) -> None:
    """Create three logical sections with natural page numbering:
    A) Cover (page 1, no footer)
    B) Blank page (page 2, no footer by default)
    C) Body (page 3+, PAGE field shows actual page number)

    Page numbering continues naturally without reset:
    - Cover = page 1
    - Blank = page 2  
    - Body starts at page 3

    We insert section breaks:
    - after last cover paragraph
    - at the first body paragraph
    Then we add PAGE field only to the body section's footer with optional styling.
    Footers are unlinked from previous sections to prevent inheritance.
    
    Args:
        doc: The document
        config: Configuration dict
        last_cover_para_index: Index of last cover paragraph
        first_body_para_index: Index of first body paragraph
        footer_style_overrides: Optional dict with font_family, size_pt, bold, italic
    """
    numbering = (config or {}).get("layout", {}).get("numbering", {})
    print_on_page2 = bool(numbering.get("print_on_page2", False))

    # Section break after cover -> Section B starts next page
    # No pgNumType set - page numbers continue naturally (cover=1, blank=2, body=3+)
    last_cover_p = doc.paragraphs[last_cover_para_index]
    _add_section_break_next_page_to_paragraph(last_cover_p, start_number=None)

    # Section break at first body paragraph -> Section C starts next page
    # No pgNumType set - page numbers continue naturally
    if 0 <= first_body_para_index < len(doc.paragraphs):
        first_body_p = doc.paragraphs[first_body_para_index]
        _add_section_break_next_page_to_paragraph(first_body_p, start_number=None)

    # After modifying sectPr manually, python-docx will expose sections in order
    sections = doc.sections

    # Ensure first-page footer has no PAGE (cover)
    # Unlink from previous to prevent inheritance
    if len(sections) >= 1:
        secA = sections[0]
        secA.footer.is_linked_to_previous = False
        _clear_footer(secA.footer)

    # Section B (blank page): optionally print number (default false)
    if len(sections) >= 2:
        secB = sections[1]
        secB.footer.is_linked_to_previous = False
        _clear_footer(secB.footer)
        if print_on_page2:
            p = secB.footer.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_page_field(p, footer_style_overrides)

    # Section C (body): always print PAGE centered with optional styling
    if len(sections) >= 3:
        secC = sections[2]
        secC.footer.is_linked_to_previous = False
        _clear_footer(secC.footer)
        p = secC.footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_page_field(p, footer_style_overrides)


def apply_footer_styles(doc: Document, config: Dict[str, Any], footer_style_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply footer styles to existing document sections.
    
    This function:
    1. Clears existing footers in all sections
    2. Unlinks footers from previous sections to prevent inheritance
    3. Adds PAGE field with optional styling to body section (last section)
    4. Leaves cover and blank page sections without page numbers
    
    Note: This function does NOT set pgNumType. Page numbering should
    continue naturally (Cover=1, Blank=2, Body=3+). The PAGE field
    in the footer will show the actual page number.
    
    Args:
        doc: The document
        config: Configuration dict
        footer_style_overrides: Optional dict with font_family, size_pt, bold, italic
    
    Returns:
        Dict with info about what was changed
    """
    result = {
        "action": "none",
        "sections_count": len(doc.sections),
        "footer_applied_to": None,
    }
    
    # Get footer style from config if not provided directly
    if footer_style_overrides is None:
        so = (config or {}).get("style_overrides", {}) or {}
        footer_style_overrides = so.get("Footer")
    
    sections = doc.sections
    
    # Unlink all footers from previous section and clear them
    # This prevents footer inheritance that causes duplication
    for sec in sections:
        # Unlink footer from previous section
        sec.footer.is_linked_to_previous = False
        _clear_footer(sec.footer)
    
    # Apply PAGE field only to last section (body) with styling
    if len(sections) >= 1:
        body_sec = sections[-1]
        # Make sure footer is unlinked
        body_sec.footer.is_linked_to_previous = False
        p = body_sec.footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_page_field(p, footer_style_overrides)
        result["action"] = "footer_styled"
        result["footer_applied_to"] = len(sections) - 1
    
    # Do NOT set pgNumType here - page numbers should continue naturally
    # Cover=page 1, Blank=page 2, Body starts at page 3
    # The PAGE field will show the correct physical page number
    
    return result


def fix_theme_fonts(docx_path: str, major_font: str = "Cambria", minor_font: str = "Cambria") -> Dict[str, Any]:
    """Replace theme fonts in DOCX to ensure consistency between Word and LibreOffice.
    
    Many DOCX files use theme fonts (e.g., Calibri, Calibri Light) which may not be
    available in LibreOffice. This function replaces theme font definitions in
    word/theme/theme1.xml with specified fonts that ARE available.
    
    Args:
        docx_path: Path to the DOCX file (will be modified in place)
        major_font: Font to use for headings (replaces majorFont/latin)
        minor_font: Font to use for body text (replaces minorFont/latin)
    
    Returns:
        Dict with info about what was changed
    """
    import zipfile
    import tempfile
    import shutil
    from lxml import etree
    
    result = {
        "changed": False,
        "original_major": None,
        "original_minor": None,
        "new_major": major_font,
        "new_minor": minor_font,
    }
    
    # Open DOCX as ZIP
    temp_dir = tempfile.mkdtemp()
    try:
        # Extract all files
        with zipfile.ZipFile(docx_path, 'r') as zin:
            zin.extractall(temp_dir)
        
        theme_path = os.path.join(temp_dir, 'word', 'theme', 'theme1.xml')
        if not os.path.exists(theme_path):
            result["error"] = "No theme1.xml found"
            return result
        
        # Parse theme XML
        tree = etree.parse(theme_path)
        root = tree.getroot()
        
        ns_a = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
        
        # Find and update major font (headings)
        major_latin = root.find('.//a:fontScheme/a:majorFont/a:latin', ns_a)
        if major_latin is not None:
            result["original_major"] = major_latin.get('typeface')
            if result["original_major"] != major_font:
                major_latin.set('typeface', major_font)
                result["changed"] = True
        
        # Find and update minor font (body)
        minor_latin = root.find('.//a:fontScheme/a:minorFont/a:latin', ns_a)
        if minor_latin is not None:
            result["original_minor"] = minor_latin.get('typeface')
            if result["original_minor"] != minor_font:
                minor_latin.set('typeface', minor_font)
                result["changed"] = True
        
        if result["changed"]:
            # Write updated theme XML
            tree.write(theme_path, xml_declaration=True, encoding='UTF-8', standalone=True)
            
            # Repack DOCX
            with zipfile.ZipFile(docx_path, 'w', zipfile.ZIP_DEFLATED) as zout:
                for root_dir, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root_dir, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zout.write(file_path, arcname)
        
        return result
    
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
