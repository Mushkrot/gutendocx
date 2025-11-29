"""
Body styles detection using AI Vision.

This module provides functionality to:
1. Find pages in a document that contain headings
2. Render selected pages to PNG
3. Use AI Vision to detect heading levels and body text
4. Extract style parameters from detected elements
"""

import os
import tempfile
import shutil
import subprocess
import base64
import json
import time
import re
from typing import Any, Dict, Optional, List, Tuple
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH


def _which_soffice() -> Optional[str]:
    """Find LibreOffice soffice executable."""
    candidates = [
        shutil.which("soffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _pt(size) -> float:
    """Convert size to points."""
    if size is None:
        return 0.0
    if hasattr(size, "pt"):
        return float(size.pt)
    return float(size)


def _render_docx_to_pdf(docx_path: str, out_dir: str) -> str:
    """Convert DOCX to PDF using LibreOffice."""
    soffice = _which_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice 'soffice' not found")
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        soffice,
        "--headless",
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        out_dir,
        docx_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    base = os.path.splitext(os.path.basename(docx_path))[0]
    pdf_path = os.path.join(out_dir, f"{base}.pdf")
    if not os.path.exists(pdf_path):
        alt = os.path.join(out_dir, f"{base}.PDF")
        if os.path.exists(alt):
            pdf_path = alt
    if not os.path.exists(pdf_path):
        raise RuntimeError("PDF render failed: output PDF not found")
    return pdf_path


def _render_pdf_pages_to_png(pdf_path: str, out_dir: str, dpi: int, pages: List[int]) -> List[str]:
    """Render specific PDF pages to PNG files."""
    try:
        from pdf2image import convert_from_path
    except Exception as e:
        raise RuntimeError("pdf2image is required") from e

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    png_paths = []
    
    for page_num in pages:
        images = convert_from_path(pdf_path, dpi=dpi, first_page=page_num, last_page=page_num)
        if images:
            png_path = os.path.join(out_dir, f"{base}_page{page_num}.png")
            images[0].save(png_path, format="PNG")
            png_paths.append(png_path)
    
    return png_paths


def find_pages_with_headings(doc: Document, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Find pages that contain headings/chapter titles.
    
    Returns info about where headings appear and which pages to render.
    """
    # Look for paragraphs that might be headings:
    # - Style name contains "Heading" or "Title" or "Chapter"
    # - Large font size (> 14pt)
    # - ALL CAPS text
    # - Short text (< 100 chars) that's not empty
    
    heading_indicators = []
    body_start_idx = 0
    
    # Find first page break (end of cover) - but only in first ~30 paragraphs
    # Don't scan whole document as many docs have section breaks throughout
    first_break_found = False
    for i, p in enumerate(doc.paragraphs[:30]):
        if first_break_found:
            break
        # Check for page/section break
        for run in p.runs:
            if run._element.xml and ('w:br' in run._element.xml and 'w:type="page"' in run._element.xml):
                body_start_idx = i + 1
                first_break_found = True
                break
        # Also check paragraph XML for section breaks
        if not first_break_found and 'w:sectPr' in p._element.xml:
            body_start_idx = i + 1
            first_break_found = True
    
    # Analyze ALL paragraphs (not just after body_start_idx) to find headings
    # We need to find headings throughout the document
    for i, p in enumerate(doc.paragraphs):
        text = (p.text or "").strip()
        if not text or len(text) > 150:
            continue
        
        style_name = p.style.name if p.style else ""
        # Check for heading-like styles: "Heading X", "Title", "Chapter", "Para XX" (Gutenberg style)
        is_heading_style = any(kw in style_name.lower() for kw in ["heading", "title", "chapter", "toc"])
        # Also check for "Para XX" styles which Gutenberg uses for headings
        if not is_heading_style and style_name.startswith("Para "):
            is_heading_style = True
        
        # Check font size
        max_size = 0.0
        for run in p.runs:
            if run.font.size:
                max_size = max(max_size, _pt(run.font.size))
            elif p.style and p.style.font and p.style.font.size:
                max_size = max(max_size, _pt(p.style.font.size))
        
        # Check if ALL CAPS
        is_caps = text.isupper() and len(text) > 3
        
        # Check if centered
        is_centered = False
        try:
            is_centered = p.alignment == WD_ALIGN_PARAGRAPH.CENTER
        except:
            pass
        
        # Score this paragraph as potential heading
        score = 0
        if is_heading_style:
            score += 3
        if max_size >= 16:
            score += 2
        elif max_size >= 14:
            score += 1
        if is_caps:
            score += 2
        if is_centered:
            score += 1
        if len(text) < 50:
            score += 1
        
        if score >= 2:
            heading_indicators.append({
                "para_idx": i,
                "text": text[:80],
                "style": style_name,
                "size_pt": max_size,
                "is_caps": is_caps,
                "is_centered": is_centered,
                "score": score,
            })
    
    # Estimate page numbers (rough: ~25-30 paragraphs per page for typical book)
    # This is approximate - actual page breaks depend on formatting
    paragraphs_per_page = 28
    
    # Group headings by estimated page
    pages_with_headings: Dict[int, List[Dict]] = {}
    for h in heading_indicators:
        estimated_page = max(2, (h["para_idx"] - body_start_idx) // paragraphs_per_page + 2)
        if estimated_page not in pages_with_headings:
            pages_with_headings[estimated_page] = []
        pages_with_headings[estimated_page].append(h)
    
    # Select pages from different parts of the document for better coverage
    # We need pages from: beginning, middle, and later sections
    all_pages = sorted(pages_with_headings.keys())
    
    selected_pages = []
    if all_pages:
        # Always include first page with headings (usually near beginning)
        selected_pages.append(all_pages[0])
        
        # Include a page from middle of document
        if len(all_pages) > 2:
            mid_idx = len(all_pages) // 2
            if all_pages[mid_idx] not in selected_pages:
                selected_pages.append(all_pages[mid_idx])
        
        # Include a page from later in document (where chapters often are)
        if len(all_pages) > 1:
            # Pick page around 60-70% through
            later_idx = int(len(all_pages) * 0.7)
            if all_pages[later_idx] not in selected_pages:
                selected_pages.append(all_pages[later_idx])
        
        # Add one more page with highest heading score if we have room
        sorted_by_score = sorted(
            pages_with_headings.items(),
            key=lambda x: sum(h["score"] for h in x[1]),
            reverse=True
        )
        for page, _ in sorted_by_score:
            if page not in selected_pages and len(selected_pages) < 5:
                selected_pages.append(page)
                break
    
    # Ensure we have at least pages 2-4 if no headings found
    if not selected_pages:
        selected_pages = [2, 3, 4]
    
    # Also estimate total pages and add a late page if document is large
    total_pages_est = max(10, len(doc.paragraphs) // paragraphs_per_page)
    if total_pages_est > 50 and len(selected_pages) < 5:
        late_page = int(total_pages_est * 0.8)
        if late_page not in selected_pages:
            selected_pages.append(late_page)
    
    selected_pages = sorted(set(selected_pages))[:5]
    
    print(f"DEBUG find_pages: total_paras={len(doc.paragraphs)}, est_pages={total_pages_est}, selected={selected_pages}")
    
    return {
        "body_start_idx": body_start_idx,
        "heading_indicators": heading_indicators[:20],  # Limit for response size
        "pages_with_headings": {k: v for k, v in list(pages_with_headings.items())[:10]},
        "selected_pages": selected_pages,
        "total_paragraphs": len(doc.paragraphs),
    }


def _prepare_api_image(png_path: str, max_px: int = 1600, quality: int = 85) -> str:
    """Prepare image for API: resize and convert to base64 JPEG."""
    from PIL import Image
    im = Image.open(png_path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > max_px:
        scale = max_px / float(max(w, h))
        im = im.resize((int(w * scale), int(h * scale)))
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        jpg_path = tmp.name
    im.save(jpg_path, format="JPEG", quality=quality, optimize=True)
    with open(jpg_path, "rb") as f:
        b = f.read()
    try:
        os.remove(jpg_path)
    except:
        pass
    return "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")


def detect_body_styles_vision(input_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Use AI Vision to detect heading levels and body text styles.
    
    1. Find pages with headings
    2. Render those pages to PNG
    3. Send to AI for analysis
    4. Return detected roles with text snippets
    """
    cover_cfg = config.get("cover", {}) or {}
    vision_cfg = cover_cfg.get("vision", {}) or {}
    model = vision_cfg.get("model", "gpt-4o-mini")
    render_dpi = int(vision_cfg.get("render_dpi", 220))
    out_dir = vision_cfg.get("out_dir", "output/vision")
    keep_rendered = bool(vision_cfg.get("keep_rendered", True))
    
    t0 = time.time()
    warnings = []
    rendered_pngs = []
    
    # Load document and find pages with headings
    doc = Document(input_path)
    page_info = find_pages_with_headings(doc, config)
    selected_pages = page_info.get("selected_pages", [2, 3])
    
    print(f"DEBUG body_vision: selected_pages={selected_pages}")
    
    # Render pages to PNG
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = _render_docx_to_pdf(input_path, tmp)
            rendered_pngs = _render_pdf_pages_to_png(pdf_path, out_dir, render_dpi, selected_pages)
    except Exception as e:
        warnings.append(f"render_failed: {e}")
        return {
            "ok": False,
            "error": str(e),
            "warnings": warnings,
            "page_info": page_info,
        }
    
    if not rendered_pngs:
        warnings.append("no_pages_rendered")
        return {
            "ok": False,
            "error": "No pages rendered",
            "warnings": warnings,
            "page_info": page_info,
        }
    
    # Load API key
    env_path = vision_cfg.get("env_path")
    if env_path:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.expanduser(env_path))
        except:
            pass
    
    if not os.getenv("OPENAI_API_KEY"):
        warnings.append("missing_api_key")
        return {
            "ok": False,
            "error": "Missing OpenAI API key",
            "warnings": warnings,
            "page_info": page_info,
            "rendered_pngs": rendered_pngs,
        }
    
    # Call AI Vision
    try:
        from openai import OpenAI
        client = OpenAI()
        
        # Prepare images
        image_contents = []
        for png_path in rendered_pngs:
            data_url = _prepare_api_image(png_path)
            image_contents.append({"type": "image_url", "image_url": {"url": data_url}})
        
        prompt = """Analyze these book pages and identify ALL distinct text styles by their visual role and font size.

This is a classic book with multiple heading levels. Look carefully for EACH DIFFERENT FONT SIZE:
- heading1: Chapter NUMBER in smaller font, like "CHAPTER I" or "CHAPTER XII" (often 13-14pt)
- heading2: Chapter TITLE in larger font, like "The Growth of Conscience" or "Recapitulation of Principles" (often 18-20pt)
- heading3: Section titles like "FOOTNOTES:" or "APPENDIX" (medium font)
- heading4: Smaller subsection titles if present
- body: Regular paragraph text - the main content, usually justified

IMPORTANT: On chapter pages, the chapter NUMBER (e.g. "CHAPTER I") and chapter TITLE (e.g. "The Growth of Conscience") often have DIFFERENT font sizes - identify them separately!

For EACH distinct font size/style you see, return one example:
- role: "heading1", "heading2", "heading3", "heading4", or "body"
- text: first 40 characters of the text (exact text as shown)
- confidence: 0.0 to 1.0

Return strictly as JSON:
{"items":[{"role":"heading1","text":"CHAPTER XII","confidence":0.95},{"role":"heading2","text":"Recapitulation of Principles","confidence":0.9},...]}

Include at least one example of each distinct font size you can identify (typically 3-5 different sizes)."""

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *image_contents,
                ],
            }
        ]
        
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            timeout=90,
        )
        
        txt = resp.choices[0].message.content if resp.choices else ""
        
        # Parse JSON response
        items = []
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', txt, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                items = data.get("items", [])
        except Exception as e:
            warnings.append(f"json_parse_error: {e}")
        
        print(f"DEBUG body_vision: AI returned {len(items)} items")
        for item in items:
            print(f"  - {item.get('role')}: {item.get('text', '')[:40]}...")
        
        return {
            "ok": True,
            "items": items,
            "page_info": page_info,
            "rendered_pngs": rendered_pngs,
            "warnings": warnings,
            "model": model,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
        
    except Exception as e:
        warnings.append(f"api_error: {e}")
        return {
            "ok": False,
            "error": str(e),
            "warnings": warnings,
            "page_info": page_info,
            "rendered_pngs": rendered_pngs,
        }


def _find_text_in_doc(doc: Document, search_text: str, start_idx: int = 0) -> Optional[Dict[str, Any]]:
    """Find text in document, returning paragraph, run, and style info.
    
    Returns dict with:
    - para_idx: paragraph index
    - para: paragraph object
    - run: run object if text found in specific run, else None
    - run_style: character style name if run has one
    - para_style: paragraph style name
    """
    # Clean and normalize search text
    search_clean = re.sub(r'[^\w\s]', '', search_text.upper().strip())
    search_norm = re.sub(r'\s+', ' ', search_clean)[:30]
    
    print(f"DEBUG _find_text_in_doc: searching for '{search_norm}' from idx {start_idx}")
    
    # Search from start_idx first, then from beginning if not found
    for search_start in [start_idx, 0]:
        for i, p in enumerate(doc.paragraphs[search_start:], start=search_start):
            para_clean = re.sub(r'[^\w\s]', '', (p.text or "").upper().strip())
            para_text = re.sub(r'\s+', ' ', para_clean)
            if len(para_text) < 3:
                continue
            
            if search_norm in para_text or para_text[:30] in search_norm:
                # Found in paragraph - now check which run
                para_style = p.style.name if p.style else None
                
                # Check each run for the specific text
                for run in p.runs:
                    run_clean = re.sub(r'[^\w\s]', '', (run.text or "").upper().strip())
                    run_text = re.sub(r'\s+', ' ', run_clean)
                    if len(run_text) < 3:
                        continue
                    if search_norm in run_text or run_text in search_norm:
                        run_style = run.style.name if run.style else None
                        print(f"DEBUG _find_text_in_doc: FOUND in run at idx {i}: para_style='{para_style}', run_style='{run_style}', text='{run_text[:30]}'")
                        return {
                            "para_idx": i,
                            "para": p,
                            "run": run,
                            "run_style": run_style,
                            "para_style": para_style,
                        }
                
                # Text spans multiple runs or not in any run - return paragraph level
                print(f"DEBUG _find_text_in_doc: FOUND at para level idx {i}: style='{para_style}'")
                return {
                    "para_idx": i,
                    "para": p,
                    "run": None,
                    "run_style": None,
                    "para_style": para_style,
                }
        
        if search_start == 0:
            break
    
    print(f"DEBUG _find_text_in_doc: NOT FOUND")
    return None


def _extract_paragraph_style(p, doc: Document) -> Dict[str, Any]:
    """Extract style parameters from a paragraph."""
    result = {}
    
    # Get font size - check runs first, then paragraph style chain
    size_pt = 0.0
    family = None
    bold = None
    italic = None
    all_caps = None
    
    print(f"DEBUG _extract_paragraph_style: para text='{(p.text or '')[:40]}', style={p.style.name if p.style else None}")
    
    # Check runs for direct formatting
    for run in p.runs:
        if run.font.size and size_pt == 0:
            size_pt = _pt(run.font.size)
        if run.font.name and not family:
            family = run.font.name
        if run.font.bold is not None and bold is None:
            bold = run.font.bold
        if run.font.italic is not None and italic is None:
            italic = run.font.italic
        if run.font.all_caps is not None and all_caps is None:
            all_caps = run.font.all_caps
    
    # Fallback to paragraph style chain
    style = p.style
    while style:
        if style.font:
            if size_pt == 0 and style.font.size:
                size_pt = _pt(style.font.size)
            if not family and style.font.name:
                family = style.font.name
            if bold is None and style.font.bold is not None:
                bold = style.font.bold
            if italic is None and style.font.italic is not None:
                italic = style.font.italic
            if all_caps is None and style.font.all_caps is not None:
                all_caps = style.font.all_caps
        style = style.base_style
    
    print(f"DEBUG _extract_paragraph_style: size_pt={size_pt}, family={family}, bold={bold}")
    
    # Always include what we found, even if size is 0
    if size_pt > 0:
        result["size_pt"] = size_pt
    if family:
        result["family"] = family
    if bold is not None:
        result["bold"] = bold
    if italic is not None:
        result["italic"] = italic
    if all_caps is not None:
        result["all_caps"] = all_caps
    
    # If we have nothing, at least return family from style name as fallback
    if not result and p.style:
        result["_style_name"] = p.style.name
    
    # Alignment
    try:
        if p.alignment == WD_ALIGN_PARAGRAPH.CENTER:
            result["align"] = "center"
        elif p.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
            result["align"] = "right"
        elif p.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY:
            result["align"] = "justify"
        elif p.alignment == WD_ALIGN_PARAGRAPH.LEFT:
            result["align"] = "left"
    except:
        pass
    
    return result


def learn_body_styles(input_path: str, config: Dict[str, Any], vision: bool = True, min_confidence: float = 0.6) -> Dict[str, Any]:
    """
    Learn body styles (headings and body text) from a document.
    
    Uses AI Vision to detect heading levels and body text,
    then extracts style parameters from the actual document.
    
    Args:
        min_confidence: Minimum confidence threshold for AI detections (0.0-1.0)
    """
    doc = Document(input_path)
    
    # Get AI detection results
    if vision:
        detection = detect_body_styles_vision(input_path, config)
    else:
        # Fallback: use heuristic detection
        detection = {
            "ok": False,
            "error": "Vision disabled, heuristic not implemented",
            "items": [],
        }
    
    if not detection.get("ok"):
        return {
            "ok": False,
            "error": detection.get("error", "Detection failed"),
            "warnings": detection.get("warnings", []),
        }
    
    # Filter items by min_confidence
    all_items = detection.get("items", [])
    items = [it for it in all_items if float(it.get("confidence", 0)) >= min_confidence]
    
    print(f"DEBUG learn_body_styles: {len(all_items)} items from AI, {len(items)} passed min_confidence={min_confidence}")
    page_info = detection.get("page_info", {})
    body_start_idx = page_info.get("body_start_idx", 0)
    
    # Extract styles for each detected role
    extracted = {
        "heading1": {},
        "heading2": {},
        "heading3": {},
        "heading4": {},
        "body": {},
    }
    
    for item in items:
        role = item.get("role", "").lower()
        text = item.get("text", "")
        confidence = item.get("confidence", 0.5)
        
        if role not in extracted or not text:
            continue
        
        # Skip if we already have a higher-confidence match
        if extracted[role] and extracted[role].get("_confidence", 0) >= confidence:
            continue
        
        # Find this text in the document (checks both paragraph and run level)
        found = _find_text_in_doc(doc, text, body_start_idx)
        if found:
            para = found["para"]
            run = found.get("run")
            idx = found["para_idx"]
            
            # Extract style - prefer run style (character style) over paragraph style
            params = _extract_paragraph_style(para, doc)
            
            # Determine the effective style name
            # Priority: run style (if meaningful) > paragraph style
            # "Default Paragraph Font" is not meaningful - use paragraph style instead
            effective_style = None
            run_style = found.get("run_style")
            if run and run_style and run_style != "Default Paragraph Font":
                effective_style = run_style
                params["_style_type"] = "character"
            elif found.get("para_style"):
                effective_style = found["para_style"]
                params["_style_type"] = "paragraph"
            
            if effective_style:
                params["_style_name"] = effective_style
            if para.style:
                params["_para_style"] = para.style.name
                params["_style_id"] = para.style.style_id
            
            # If we have a run with a meaningful character style, extract from that style FIRST
            # Character style takes priority over paragraph style
            if run and run.style and run.style.font and run_style and run_style != "Default Paragraph Font":
                char_style = run.style
                print(f"DEBUG: checking character style '{char_style.name}' font: size={char_style.font.size}, name={char_style.font.name}")
                if char_style.font.size:
                    params["size_pt"] = _pt(char_style.font.size)
                if char_style.font.name:
                    params["family"] = char_style.font.name
                if char_style.font.bold is not None:
                    params["bold"] = char_style.font.bold
                if char_style.font.all_caps is not None:
                    params["all_caps"] = char_style.font.all_caps
            
            # Then check run's direct formatting (overrides character style)
            if run:
                if run.font.size:
                    params["size_pt"] = _pt(run.font.size)
                if run.font.name:
                    params["family"] = run.font.name
                if run.font.bold is not None:
                    params["bold"] = run.font.bold
                if run.font.all_caps is not None:
                    params["all_caps"] = run.font.all_caps
            
            params["_confidence"] = confidence
            params["_text"] = text[:50]
            params["_para_idx"] = idx
            extracted[role] = params
            print(f"DEBUG learn_body_styles: {role} -> style='{effective_style}' (type={params.get('_style_type')}), params={params}")
    
    # Build config update with style overrides AND style mappings
    config_update = {
        "style_overrides": {},
        "detected_style_mapping": {},  # Maps our roles to actual Word style names
    }
    
    # Build style mapping for remap_rules
    style_mapping = {}
    
    if extracted["heading1"]:
        h1 = {k: v for k, v in extracted["heading1"].items() if not k.startswith("_")}
        if h1.get("family"):
            h1["font"] = h1.pop("family")
        config_update["style_overrides"]["Headings"] = h1
        if extracted["heading1"].get("_style_name"):
            style_mapping["Headings"] = extracted["heading1"]["_style_name"]
    
    if extracted["heading2"]:
        h2 = {k: v for k, v in extracted["heading2"].items() if not k.startswith("_")}
        if h2.get("family"):
            h2["font"] = h2.pop("family")
        config_update["style_overrides"]["Heading2"] = h2
        if extracted["heading2"].get("_style_name"):
            style_mapping["Heading2"] = extracted["heading2"]["_style_name"]
    
    if extracted["heading3"]:
        h3 = {k: v for k, v in extracted["heading3"].items() if not k.startswith("_")}
        if h3.get("family"):
            h3["font"] = h3.pop("family")
        config_update["style_overrides"]["Heading3"] = h3
        if extracted["heading3"].get("_style_name"):
            style_mapping["Heading3"] = extracted["heading3"]["_style_name"]
    
    if extracted.get("heading4"):
        h4 = {k: v for k, v in extracted["heading4"].items() if not k.startswith("_")}
        if h4.get("family"):
            h4["font"] = h4.pop("family")
        config_update["style_overrides"]["Heading4"] = h4
        if extracted["heading4"].get("_style_name"):
            style_mapping["Heading4"] = extracted["heading4"]["_style_name"]
    
    if extracted["body"]:
        body = {k: v for k, v in extracted["body"].items() if not k.startswith("_")}
        if body.get("family"):
            body["font"] = body.pop("family")
        config_update["style_overrides"]["Body"] = body
        if extracted["body"].get("_style_name"):
            style_mapping["Body"] = extracted["body"]["_style_name"]
    
    config_update["detected_style_mapping"] = style_mapping
    
    print(f"DEBUG learn_body_styles: style_mapping = {style_mapping}")
    
    return {
        "ok": True,
        "styles": extracted,
        "style_mapping": style_mapping,  # Include in response for UI
        "config_update": config_update,
        "detection": detection,
        "warnings": detection.get("warnings", []),
    }
