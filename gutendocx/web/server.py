from typing import Optional, Any, Dict, List
import json
import os
import copy
import re
import time
import zipfile

from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from gutendocx.core.config import load_config, save_config
from gutendocx.core.cover import run_cover_pipeline, learn_cover_styles
from gutendocx.core.vision import detect_cover_roles_vision
from gutendocx.core.whole import analyze_whole_document, apply_whole_document
from gutendocx.core.toc import build_toc
from gutendocx.core.libreoffice_toc import run_libreoffice_convert


app = FastAPI(title="GutenDocx Web API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)

# Serve minimal static UI
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
OUTPUT_DIR = os.path.join(os.getcwd(), "output")
try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except Exception:
    pass
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

UPLOADS_DIR = os.path.join(os.getcwd(), "Uploads")
try:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
except Exception:
    pass


AI_COSTS_JSONL = os.path.join(OUTPUT_DIR, "ai_costs.jsonl")
AUDIT_EVENTS_JSONL = os.path.join(OUTPUT_DIR, "audit_events.jsonl")


AI_PRICES_PER_1M = {
    "gpt-4o": {"in": 2.50, "out": 10.00},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4.1": {"in": 2.00, "out": 8.00},
    "gpt-4.1-mini": {"in": 0.40, "out": 1.60},
    "gpt-4.1-nano": {"in": 0.10, "out": 0.40},
    "gpt-5": {"in": 1.25, "out": 10.00},
    "gpt-5-mini": {"in": 0.25, "out": 2.00},
    "gpt-5-nano": {"in": 0.05, "out": 0.40},
    "gpt-5.1": {"in": 1.25, "out": 10.00},
    "gpt-5.1-mini": {"in": 0.25, "out": 2.00},
}


def _normalize_model_for_pricing(model: Optional[str]) -> Optional[str]:
    if not model:
        return None
    m = str(model).strip()
    if not m:
        return None
    if m in AI_PRICES_PER_1M:
        return m
    if m.endswith("-vision"):
        m2 = m[:-len("-vision")]
        if m2 in AI_PRICES_PER_1M:
            return m2
    m2 = re.sub(r"\bgpt-5\.0", "gpt-5", m)
    if m2 in AI_PRICES_PER_1M:
        return m2
    return None


def _calc_ai_cost_usd(model: Optional[str], input_tokens: int, output_tokens: int) -> Optional[float]:
    key = _normalize_model_for_pricing(model)
    if not key:
        return None
    prices = AI_PRICES_PER_1M.get(key) or {}
    cost_in = (float(input_tokens or 0) / 1_000_000.0) * float(prices.get("in") or 0.0)
    cost_out = (float(output_tokens or 0) / 1_000_000.0) * float(prices.get("out") or 0.0)
    return float(cost_in + cost_out)


def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    except Exception:
        pass
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _bounded_str(value: Any, limit: int = 500) -> Optional[str]:
    if value is None:
        return None
    try:
        s = str(value)
    except Exception:
        return None
    if len(s) > limit:
        return s[:limit] + "...[truncated]"
    return s


def _request_context(request: Optional[Request]) -> Dict[str, Any]:
    if request is None:
        return {}
    headers = request.headers
    return {
        "client_ip": headers.get("cf-connecting-ip")
        or headers.get("x-forwarded-for")
        or (request.client.host if request.client else None),
        "method": request.method,
        "path": str(request.url.path),
        "user_agent": _bounded_str(headers.get("user-agent"), 300),
        "cf_ray": headers.get("cf-ray"),
        "cf_access_user": headers.get("cf-access-authenticated-user-email"),
        "referer": _bounded_str(headers.get("referer"), 300),
    }


def _file_ref(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = str(path)
    item: Dict[str, Any] = {
        "path": p,
        "name": os.path.basename(p),
    }
    try:
        abs_p = os.path.abspath(os.path.join(os.getcwd(), p))
        if os.path.exists(abs_p):
            item["size_bytes"] = os.path.getsize(abs_p)
    except Exception:
        pass
    return item


def _files_ref(paths: Optional[List[str]], limit: int = 50) -> List[Dict[str, Any]]:
    if not paths:
        return []
    return [x for x in (_file_ref(p) for p in paths[:limit]) if x]


def _styles_summary(styles: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(styles, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in ("body", "headings", "footer", "title", "subtitle", "author", "specials"):
        val = styles.get(key)
        if isinstance(val, dict):
            out[key] = val
    return out


HEADING_UI_TO_CONFIG = {
    "heading1": "Headings",
    "heading2": "Heading2",
    "heading3": "Heading3",
    "heading4": "Heading4",
}


def _style_override_from_ui(ov: Dict[str, Any], include_align: bool = True, footer: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    fam = ov.get("font_family") if footer else (ov.get("family") or ov.get("font"))
    if isinstance(fam, str) and fam.strip():
        out["font_family" if footer else "font"] = fam.strip()
    size_val = ov.get("size_pt")
    if isinstance(size_val, (int, float)) and size_val > 0:
        out["size_pt"] = float(size_val)
    if include_align:
        align = ov.get("align")
        if isinstance(align, str) and align.strip() and align.strip() != "keep":
            out["align"] = align.strip()
    for key in ("bold", "italic", "all_caps", "underline", "strike", "small_caps"):
        if key in ov:
            out[key] = bool(ov.get(key))
    line_spacing = ov.get("line_spacing")
    if isinstance(line_spacing, (int, float)) and line_spacing > 0:
        out["line_spacing"] = float(line_spacing)
    spacing_before = ov.get("spacing_before_pt")
    if isinstance(spacing_before, (int, float)) and spacing_before >= 0:
        out["spacing_before_pt"] = float(spacing_before)
    spacing_after = ov.get("spacing_after_pt")
    if isinstance(spacing_after, (int, float)) and spacing_after >= 0:
        out["spacing_after_pt"] = float(spacing_after)
    return out


def _merge_ui_style_overrides(cfg: Dict[str, Any], styles: Optional[Dict[str, Any]]) -> None:
    if not isinstance(styles, dict):
        return
    so = (cfg.get("style_overrides") or {}) or {}

    body_ov = styles.get("body")
    if isinstance(body_ov, dict):
        new_body = _style_override_from_ui(body_ov)
        if new_body:
            so["Body"] = new_body

    headings_ov = styles.get("headings")
    if isinstance(headings_ov, dict):
        nested = any(k in headings_ov for k in HEADING_UI_TO_CONFIG)
        if nested:
            for ui_key, cfg_key in HEADING_UI_TO_CONFIG.items():
                ov = headings_ov.get(ui_key)
                if not isinstance(ov, dict):
                    continue
                new_heading = _style_override_from_ui(ov)
                if new_heading:
                    so[cfg_key] = new_heading
        else:
            new_headings = _style_override_from_ui(headings_ov)
            if new_headings:
                so["Headings"] = new_headings

    footer_ov = styles.get("footer")
    if isinstance(footer_ov, dict):
        new_footer = _style_override_from_ui(footer_ov, include_align=False, footer=True)
        if new_footer:
            so["Footer"] = new_footer

    if so:
        cfg["style_overrides"] = so

    specials_ov = styles.get("specials")
    if isinstance(specials_ov, dict):
        so_specials = (cfg.get("special_overrides") or {}) or {}
        for name, ov in specials_ov.items():
            if not isinstance(ov, dict):
                continue
            cur = (so_specials.get(name) or {}) or {}
            new = dict(cur)
            new.update(_style_override_from_ui(ov))
            if new:
                so_specials[name] = new
        cfg["special_overrides"] = so_specials


def _apply_request_summary(req: "ApplyRequest") -> Dict[str, Any]:
    batch_files = [p for p in (req.batch_files or []) if p]
    return {
        "input": _file_ref(req.input),
        "batch_id": req.batch_id,
        "batch_count": len(batch_files),
        "batch_files": _files_ref(batch_files),
        "options": {
            "vision": bool(req.vision),
            "no_layout": bool(req.no_layout),
            "model": req.model,
            "min_confidence": req.min_confidence,
            "update_toc": bool(req.update_toc),
            "toc_mode": req.toc_mode,
            "apply_body": bool(req.apply_body),
            "apply_cover": bool(req.apply_cover),
            "config_path": req.config_path,
        },
        "styles": _styles_summary(req.styles),
    }


def _toc_request_summary(req: "TocApplyRequest") -> Dict[str, Any]:
    batch_files = [p for p in (req.batch_files or []) if p]
    return {
        "input": _file_ref(req.input),
        "batch_id": req.batch_id,
        "batch_count": len(batch_files),
        "batch_files": _files_ref(batch_files),
        "options": {
            "mode": req.mode,
            "config_path": req.config_path,
            "soffice": req.soffice,
            "timeout": req.timeout,
        },
    }


def _analyze_request_summary(req: "AnalyzeRequest") -> Dict[str, Any]:
    return {
        "input": _file_ref(req.input),
        "options": {
            "vision": bool(req.vision),
            "no_layout": bool(req.no_layout),
            "dry_run": bool(req.dry_run),
            "config_path": req.config_path,
            "model": req.model,
            "min_confidence": req.min_confidence,
        },
        "styles": _styles_summary(req.styles),
    }


def _audit_event(event: str, request: Optional[Request] = None, **data: Any) -> None:
    obj: Dict[str, Any] = {
        "ts": int(time.time()),
        "ts_ms": int(time.time() * 1000),
        "event": event,
    }
    obj.update(_request_context(request))
    obj.update(data)
    _append_jsonl(AUDIT_EVENTS_JSONL, obj)


class AuditHTTPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        t0 = time.time()
        response = None
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            _audit_event(
                "http.error",
                request,
                duration_ms=int((time.time() - t0) * 1000),
                error_type=type(e).__name__,
                error=_bounded_str(e, 500),
            )
            raise
        finally:
            if response is not None and request.url.path not in ("/health",):
                _audit_event(
                    "http.request",
                    request,
                    status_code=getattr(response, "status_code", None),
                    duration_ms=int((time.time() - t0) * 1000),
                )


app.add_middleware(AuditHTTPMiddleware)


def _new_ai_totals() -> Dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_usd": 0.0,
        "by_model": {},
    }


def _add_ai_usage(totals: Dict[str, Any], usage: Optional[Dict[str, Any]], event: Dict[str, Any]) -> None:
    if not usage or not isinstance(usage, dict):
        return
    model = usage.get("model")
    in_tok = usage.get("input_tokens")
    out_tok = usage.get("output_tokens")
    if not isinstance(in_tok, int):
        try:
            in_tok = int(in_tok)
        except Exception:
            in_tok = 0
    if not isinstance(out_tok, int):
        try:
            out_tok = int(out_tok)
        except Exception:
            out_tok = 0
    totals["input_tokens"] = int(totals.get("input_tokens") or 0) + int(in_tok)
    totals["output_tokens"] = int(totals.get("output_tokens") or 0) + int(out_tok)
    totals["total_tokens"] = int(totals.get("total_tokens") or 0) + int(in_tok) + int(out_tok)
    cost = _calc_ai_cost_usd(model, int(in_tok), int(out_tok))
    if isinstance(cost, float):
        totals["total_usd"] = float(totals.get("total_usd") or 0.0) + float(cost)
    bm = totals.get("by_model")
    if not isinstance(bm, dict):
        bm = {}
        totals["by_model"] = bm
    mk = str(model) if model else "unknown"
    rec = bm.get(mk)
    if not isinstance(rec, dict):
        rec = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "total_usd": 0.0}
        bm[mk] = rec
    rec["input_tokens"] = int(rec.get("input_tokens") or 0) + int(in_tok)
    rec["output_tokens"] = int(rec.get("output_tokens") or 0) + int(out_tok)
    rec["total_tokens"] = int(rec.get("total_tokens") or 0) + int(in_tok) + int(out_tok)
    if isinstance(cost, float):
        rec["total_usd"] = float(rec.get("total_usd") or 0.0) + float(cost)

    evt = {
        "ts": int(time.time()),
        "endpoint": "/apply",
        "model": model,
        "input_tokens": int(in_tok),
        "output_tokens": int(out_tok),
        "total_tokens": int(in_tok) + int(out_tok),
        "cost_usd": cost,
    }
    evt.update(event)
    _append_jsonl(AI_COSTS_JSONL, evt)

FONTS_DIR = os.path.abspath(
    os.environ.get("GUTENDOCX_FONTS_DIR") or os.path.join(os.getcwd(), "fonts")
)


def _get_available_fonts() -> List[str]:
    """Get list of available font family names from the fonts directory."""
    if not os.path.isdir(FONTS_DIR):
        return []
    
    font_names = set()
    for fname in os.listdir(FONTS_DIR):
        if fname.lower().endswith(('.ttf', '.otf', '.ttc')):
            # Extract font family name from filename
            # Remove extension and common suffixes like -Regular, -Bold, etc.
            name = os.path.splitext(fname)[0]
            # Remove weight/style suffixes
            for suffix in ['-Regular', '-Bold', '-Italic', '-BoldItalic', '-Light', 
                          '-Medium', '-SemiBold', '-ExtraBold', '-Thin', '-Black',
                          '-VariableFont_wght', ' Regular', ' Bold', ' Italic',
                          ' Bold Italic', ' Light', ' Medium']:
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break
            # Clean up remaining artifacts
            name = name.replace('_', ' ').replace('-', ' ').strip()
            if name:
                font_names.add(name)
    
    # Sort alphabetically, but put common fonts first
    priority_fonts = [
        'Times New Roman', 'Arial', 'Georgia', 'Garamond', 'Cambria', 'Calibri',
        'Helvetica', 'Verdana', 'Courier New', 'Palatino', 'Baskerville',
        'Book Antiqua', 'Century', 'Trebuchet MS'
    ]
    
    result = []
    remaining = set(font_names)
    for pf in priority_fonts:
        # Check if priority font exists (case-insensitive match)
        for fn in list(remaining):
            if fn.lower() == pf.lower():
                result.append(fn)
                remaining.discard(fn)
                break
    
    # Add remaining fonts sorted alphabetically
    result.extend(sorted(remaining))
    return result


def _build_download_meta(saved_path: Optional[str]) -> Optional[Dict[str, str]]:
    """Return download metadata if the saved file lives under OUTPUT_DIR."""
    if not saved_path:
        return None
    abs_path = os.path.abspath(saved_path)
    try:
        common = os.path.commonpath([abs_path, OUTPUT_DIR])
    except ValueError:
        return None
    if common != OUTPUT_DIR:
        return None
    rel_path = os.path.relpath(abs_path, OUTPUT_DIR)
    normalized = rel_path.replace(os.sep, "/")
    return {
        "filename": os.path.basename(abs_path),
        "url": f"/output/{normalized}",
    }


def _build_batch_zip(items: List[Dict[str, str]], batch_id: Optional[str], extra_files: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """Create a ZIP archive for a batch of processed DOCX files.

    Each item must have keys:
      - input_path: original input path (relative to project root)
      - output_path: saved DOCX path on disk
      - pdf_path: (optional) saved PDF path on disk
    """

    if not items:
        return None

    name = batch_id or f"batch_{int(time.time())}"
    zip_path = os.path.join(OUTPUT_DIR, f"{name}.zip")

    batch_root: Optional[str] = None
    if batch_id:
        candidate = os.path.join(UPLOADS_DIR, batch_id)
        if os.path.isdir(candidate):
            batch_root = os.path.abspath(candidate)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for it in items:
            inp_rel = it.get("input_path")
            out_path = it.get("output_path")
            pdf_path = it.get("pdf_path")
            
            # Add DOCX
            if out_path:
                abs_out = os.path.abspath(out_path)
                if os.path.exists(abs_out):
                    arcname = os.path.basename(abs_out)
                    if batch_root and inp_rel:
                        inp_abs = os.path.abspath(os.path.join(os.getcwd(), inp_rel))
                        try:
                            rel_to_root = os.path.relpath(inp_abs, batch_root)
                        except Exception:
                            rel_to_root = None
                        if rel_to_root and not rel_to_root.startswith(".."):
                            rel_dir = os.path.dirname(rel_to_root)
                            if rel_dir:
                                arcname = os.path.join(rel_dir, os.path.basename(abs_out))
                    zf.write(abs_out, arcname.replace(os.sep, "/"))
            
            # Add PDF if available
            if pdf_path:
                abs_pdf = os.path.abspath(pdf_path)
                if os.path.exists(abs_pdf):
                    pdf_arcname = os.path.basename(abs_pdf)
                    if batch_root and inp_rel:
                        inp_abs = os.path.abspath(os.path.join(os.getcwd(), inp_rel))
                        try:
                            rel_to_root = os.path.relpath(inp_abs, batch_root)
                        except Exception:
                            rel_to_root = None
                        if rel_to_root and not rel_to_root.startswith(".."):
                            rel_dir = os.path.dirname(rel_to_root)
                            if rel_dir:
                                pdf_arcname = os.path.join(rel_dir, os.path.basename(abs_pdf))
                    zf.write(abs_pdf, pdf_arcname.replace(os.sep, "/"))

        if extra_files:
            for ef in extra_files:
                if not isinstance(ef, dict):
                    continue
                ef_path = ef.get("path")
                if not ef_path:
                    continue
                abs_ef = os.path.abspath(str(ef_path))
                if not os.path.exists(abs_ef):
                    continue
                arcname = str(ef.get("arcname") or os.path.basename(abs_ef))
                zf.write(abs_ef, arcname.replace(os.sep, "/"))

    return zip_path


def _extract_cover_texts_for_report(input_path: str, detection: Optional[Dict[str, Any]]) -> Dict[str, str]:
    res = {"title": "", "subtitle": "", "author": ""}
    if not detection:
        return res
    try:
        from docx import Document  # type: ignore
    except Exception:
        return res
    try:
        doc = Document(input_path)
    except Exception:
        return res

    cover_idxs = detection.get("cover_paragraph_indices") or []
    try:
        cover_idxs = [int(i) for i in cover_idxs]
    except Exception:
        cover_idxs = []

    assignments = detection.get("assignments") or {}
    role_to_key = {
        "Cover Title": "title",
        "Cover Subtitle": "subtitle",
        "Cover Author": "author",
    }
    buckets: Dict[str, List[str]] = {"title": [], "subtitle": [], "author": []}
    for idx in sorted(cover_idxs):
        role = assignments.get(idx)
        if role is None:
            role = assignments.get(str(idx))
        key = role_to_key.get(str(role) if role is not None else "")
        if not key:
            continue
        if idx < 0 or idx >= len(doc.paragraphs):
            continue
        try:
            t = doc.paragraphs[idx].text or ""
        except Exception:
            t = ""
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            buckets[key].append(t)

    for k in ("title", "subtitle", "author"):
        res[k] = " ".join(buckets.get(k) or []).strip()
    return res


def _count_pdf_pages(pdf_path: Optional[str]) -> Optional[int]:
    if not pdf_path:
        return None
    abs_pdf = os.path.abspath(str(pdf_path))
    if not os.path.exists(abs_pdf):
        return None
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return None
    try:
        reader = PdfReader(abs_pdf)
        return int(len(getattr(reader, "pages", []) or []))
    except Exception:
        return None


def _write_batch_report_xlsx(rows: List[Dict[str, Any]], output_path: str) -> str:
    try:
        from openpyxl import Workbook  # type: ignore
        from openpyxl.styles import Alignment  # type: ignore
    except Exception as e:
        raise RuntimeError("openpyxl_missing") from e
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["Filename", "Title", "Subtitle", "Author", "Pages"])

    # Format header
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for cell in ws[1]:
        cell.alignment = header_alignment

    for r in rows:
        pages_val = r.get("pages")
        if not isinstance(pages_val, int):
            pages_val = ""
        ws.append(
            [
                str(r.get("filename") or ""),
                str(r.get("title") or ""),
                str(r.get("subtitle") or ""),
                str(r.get("author") or ""),
                pages_val,
            ]
        )

    # Center-align Pages column values (E)
    pages_alignment = Alignment(horizontal="center", vertical="center")
    for row in ws.iter_rows(min_row=2, min_col=5, max_col=5, max_row=ws.max_row):
        row[0].alignment = pages_alignment

    # Autofilter on header row for all populated rows
    ws.auto_filter.ref = f"A1:E{ws.max_row}"
    ws.freeze_panes = "A2"

    wb.save(output_path)
    return output_path


def _build_single_zip(docx_path: str, pdf_path: Optional[str] = None) -> Optional[str]:
    """Create a ZIP archive containing DOCX and optionally PDF for single file download."""
    if not docx_path or not os.path.exists(docx_path):
        return None
    
    base_name = os.path.splitext(os.path.basename(docx_path))[0]
    zip_path = os.path.join(OUTPUT_DIR, f"{base_name}_{int(time.time())}.zip")
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(docx_path, os.path.basename(docx_path))
        if pdf_path and os.path.exists(pdf_path):
            zf.write(pdf_path, os.path.basename(pdf_path))
    
    return zip_path


@app.post("/files/upload")
async def upload_files(request: Request, files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    """Upload one or more DOCX files (or folders) and store them under Uploads/.

    The client is expected to send each file with its relative path as the
    filename (e.g. using file.webkitRelativePath on the web). We preserve this
    structure under a generated batch directory.
    """

    t0 = time.time()
    if not files:
        _audit_event("upload.rejected", request, reason="no_files")
        raise HTTPException(status_code=400, detail="No files uploaded")

    batch_id = f"batch_{int(time.time())}"
    batch_dir = os.path.join(UPLOADS_DIR, batch_id)
    os.makedirs(batch_dir, exist_ok=True)

    saved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for f in files:
        rel = f.filename or f.filename or "document.docx"
        rel = rel.replace("\\", "/").strip("/")
        base_name = os.path.basename(rel) or "document.docx"
        # Skip Word lock/owner files (~$...) and any non-DOCX files entirely.
        if base_name.startswith("~$") or not base_name.lower().endswith(".docx"):
            skipped.append({"filename": rel, "reason": "not_docx_or_lock_file"})
            try:
                # Drain and close the stream so the server can reuse the connection safely.
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
            finally:
                await f.close()
            continue

        parts = [p for p in rel.split("/") if p and p not in (".", "..")]
        if not parts:
            parts = [base_name]
        rel_clean = "/".join(parts)
        dest = os.path.join(batch_dir, *rel_clean.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        try:
            with open(dest, "wb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
        finally:
            await f.close()

        rel_project = os.path.relpath(dest, os.getcwd()).replace(os.sep, "/")
        rel_batch = os.path.relpath(dest, batch_dir).replace(os.sep, "/")
        saved.append(
            {
                "name": os.path.basename(dest),
                "rel_path": rel_project,
                "batch_rel_path": rel_batch,
                "size_bytes": os.path.getsize(dest) if os.path.exists(dest) else None,
            }
        )

    resp = {
        "batch_id": batch_id,
        "root": os.path.relpath(batch_dir, os.getcwd()).replace(os.sep, "/"),
        "files": saved,
    }
    _audit_event(
        "upload.completed",
        request,
        batch_id=batch_id,
        count=len(saved),
        skipped=skipped,
        files=saved,
        duration_ms=int((time.time() - t0) * 1000),
    )
    return resp


@app.get("/")
def index():
    path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Not Found")


class AnalyzeRequest(BaseModel):
    input: str
    vision: bool = True
    no_layout: bool = True
    dry_run: bool = True
    config_path: Optional[str] = None
    model: Optional[str] = None
    min_confidence: Optional[float] = None
    styles: Optional[Dict[str, Any]] = None


class ApplyRequest(BaseModel):
    input: str
    vision: bool = True
    no_layout: bool = True
    config_path: Optional[str] = None
    model: Optional[str] = None
    min_confidence: Optional[float] = None
    styles: Optional[Dict[str, Any]] = None
    batch_files: Optional[List[str]] = None
    batch_id: Optional[str] = None
    update_toc: bool = False
    toc_mode: Optional[str] = None
    apply_body: bool = True
    apply_cover: bool = False


class TocApplyRequest(BaseModel):
    input: str
    mode: Optional[str] = None
    config_path: Optional[str] = None
    soffice: Optional[str] = None
    timeout: Optional[int] = None
    batch_files: Optional[List[str]] = None
    batch_id: Optional[str] = None


class LearnCoverStylesRequest(BaseModel):
    input: str
    vision: bool = True
    config_path: Optional[str] = None
    save_config: bool = True  # Whether to save learned styles to config.yaml
    min_confidence: Optional[float] = None


class ClientAuditEventRequest(BaseModel):
    event: str
    data: Optional[Dict[str, Any]] = None


@app.post("/events/client")
def client_audit_event(req: ClientAuditEventRequest, request: Request) -> Dict[str, Any]:
    data = req.data if isinstance(req.data, dict) else {}
    _audit_event(
        "client." + re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(req.event or "event"))[:100],
        request,
        data=data,
    )
    return {"ok": True}


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "time": int(time.time())}


@app.get("/config")
def get_config(config_path: str = None) -> Dict[str, Any]:
    """Get current config values for UI display."""
    try:
        cfg = load_config(config_path)
        # Extract relevant sections for UI
        cover_styles = cfg.get("cover", {}).get("styles", {})
        style_overrides = cfg.get("style_overrides", {})
        return {
            "ok": True,
            "cover": {
                "title": cover_styles.get("title", {}).get("font", {}),
                "subtitle": cover_styles.get("subtitle", {}).get("font", {}),
                "author": cover_styles.get("author", {}).get("font", {}),
            },
            "body": style_overrides.get("Body", {}),
            "headings": style_overrides.get("Headings", {}),
            "footer": style_overrides.get("Footer", {}),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/config/learn_cover_styles")
def config_learn_cover_styles(req: LearnCoverStylesRequest, request: Request) -> Dict[str, Any]:
    """Learn cover styles from an existing document and optionally save to config.
    
    This endpoint:
    1. Uses AI vision (or heuristics) to detect Title/Subtitle/Author paragraphs
    2. Extracts their font/style parameters
    3. Optionally saves to config.yaml
    
    Useful for creating a baseline config from an already-formatted document.
    """
    t0 = time.time()
    _audit_event(
        "learn_cover.started",
        request,
        input=_file_ref(req.input),
        options={
            "vision": bool(req.vision),
            "save_config": bool(req.save_config),
            "config_path": req.config_path,
            "min_confidence": req.min_confidence,
        },
    )
    print(f"DEBUG learn_cover_styles: input={req.input}, vision={req.vision}, save_config={req.save_config}, min_confidence={req.min_confidence}")
    try:
        cfg = load_config(req.config_path)
        
        # Apply min_confidence to config for vision detection
        if req.min_confidence is not None:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["min_confidence"] = float(req.min_confidence)
            c["vision"] = v
            cfg["cover"] = c
        
        result = learn_cover_styles(
            input_path=req.input,
            config=cfg,
            vision=req.vision,
        )
        
        print(f"DEBUG learn_cover_styles result: ok={result.get('ok')}, styles={result.get('styles')}")
        print(f"DEBUG learn_cover_styles config_update: {result.get('config_update')}")
        
        if not result.get("ok"):
            print(f"DEBUG learn_cover_styles: NOT OK, returning early. error={result.get('error')}")
        _audit_event(
            "learn_cover.completed",
            request,
            ok=bool(result.get("ok")),
            input=_file_ref(req.input),
            roles=list((result.get("styles") or {}).keys()) if isinstance(result.get("styles"), dict) else [],
            warnings=result.get("warnings"),
            error=result.get("error"),
            duration_ms=int((time.time() - t0) * 1000),
        )
        return result
        
        # If save_config is True, merge and save
        if req.save_config:
            config_update = result.get("config_update", {})
            print(f"DEBUG learn_cover_styles: save_config=True, config_update keys={config_update.keys() if config_update else 'empty'}")
            if config_update:
                # Deep merge cover.styles
                cover_cfg = cfg.get("cover", {}) or {}
                styles_cfg = cover_cfg.get("styles", {}) or {}
                
                new_styles = config_update.get("cover", {}).get("styles", {})
                print(f"DEBUG learn_cover_styles: new_styles to REPLACE = {new_styles}")
                for role_key, role_data in new_styles.items():
                    new_font = role_data.get("font", {}) or {}
                    # Skip if no font data found for this role (keep existing config)
                    if not new_font:
                        print(f"DEBUG learn_cover_styles: SKIPPING role_key={role_key} (no font data found)")
                        continue
                    print(f"DEBUG learn_cover_styles: replacing role_key={role_key}, role_data={role_data}")
                    if role_key in styles_cfg:
                        # REPLACE font settings completely (not merge)
                        styles_cfg[role_key]["font"] = new_font
                    else:
                        styles_cfg[role_key] = role_data
                
                cover_cfg["styles"] = styles_cfg
                cfg["cover"] = cover_cfg
                
                config_path = req.config_path or os.path.join(os.getcwd(), "config.yaml")
                print(f"DEBUG learn_cover_styles: saving to {config_path}")
                save_config(cfg, config_path)
                result["config_saved"] = True
                result["config_path"] = config_path
        
        return result
    except Exception as e:
        print(f"DEBUG learn_cover_styles EXCEPTION: {e}")
        _audit_event(
            "learn_cover.error",
            request,
            input=_file_ref(req.input),
            error_type=type(e).__name__,
            error=_bounded_str(e, 500),
            duration_ms=int((time.time() - t0) * 1000),
        )
        raise HTTPException(status_code=400, detail=str(e))


class LearnBodyStylesRequest(BaseModel):
    input: str
    vision: bool = True
    config_path: Optional[str] = None
    save_config: bool = True
    min_confidence: Optional[float] = None


@app.post("/config/learn_body_styles")
def config_learn_body_styles(req: LearnBodyStylesRequest, request: Request) -> Dict[str, Any]:
    """Learn body styles (headings and body text) from a document using AI Vision.
    
    This endpoint:
    1. Finds pages with headings in the document
    2. Renders 2-3 pages to PNG
    3. Uses AI Vision to detect heading levels (heading1/2/3) and body text
    4. Extracts style parameters from detected elements
    5. Optionally saves to config.yaml
    """
    t0 = time.time()
    _audit_event(
        "learn_body.started",
        request,
        input=_file_ref(req.input),
        options={
            "vision": bool(req.vision),
            "save_config": bool(req.save_config),
            "config_path": req.config_path,
            "min_confidence": req.min_confidence,
        },
    )
    print(f"DEBUG learn_body_styles: input={req.input}, vision={req.vision}, save_config={req.save_config}, min_confidence={req.min_confidence}")
    try:
        from ..core.body_vision import learn_body_styles
        
        cfg = load_config(req.config_path)
        
        # Apply min_confidence to config
        min_conf = req.min_confidence if req.min_confidence is not None else 0.6
        
        result = learn_body_styles(
            input_path=req.input,
            config=cfg,
            vision=req.vision,
            min_confidence=min_conf,
        )
        
        print(f"DEBUG learn_body_styles result: ok={result.get('ok')}, styles={result.get('styles')}")
        
        if not result.get("ok"):
            _audit_event(
                "learn_body.completed",
                request,
                ok=False,
                input=_file_ref(req.input),
                error=result.get("error"),
                warnings=result.get("warnings"),
                duration_ms=int((time.time() - t0) * 1000),
            )
            return result
        
        # If save_config is True, merge and save
        if req.save_config:
            config_update = result.get("config_update", {})
            if config_update:
                style_overrides = cfg.get("style_overrides", {}) or {}
                new_overrides = config_update.get("style_overrides", {})
                
                print(f"DEBUG learn_body_styles: new_overrides = {new_overrides}")
                
                for role_key, role_data in new_overrides.items():
                    # Skip if no data found for this role
                    if not role_data:
                        print(f"DEBUG learn_body_styles: SKIPPING {role_key} (no data)")
                        continue
                    print(f"DEBUG learn_body_styles: replacing {role_key} = {role_data}")
                    style_overrides[role_key] = role_data
                
                cfg["style_overrides"] = style_overrides
                detected_mapping = config_update.get("detected_style_mapping")
                if isinstance(detected_mapping, dict):
                    cur_mapping = (cfg.get("detected_style_mapping") or {}) or {}
                    cur_mapping.update({str(k): str(v) for k, v in detected_mapping.items() if v})
                    cfg["detected_style_mapping"] = cur_mapping
                
                config_path = req.config_path or os.path.join(os.getcwd(), "config.yaml")
                print(f"DEBUG learn_body_styles: saving to {config_path}")
                save_config(cfg, config_path)
                result["config_saved"] = True
                result["config_path"] = config_path
        
        _audit_event(
            "learn_body.completed",
            request,
            ok=bool(result.get("ok")),
            input=_file_ref(req.input),
            style_mapping=result.get("style_mapping"),
            roles=list((result.get("styles") or {}).keys()) if isinstance(result.get("styles"), dict) else [],
            config_saved=bool(result.get("config_saved")),
            ai_usage=(result.get("ai_usage") if isinstance(result, dict) else None),
            duration_ms=int((time.time() - t0) * 1000),
        )
        return result
    except Exception as e:
        print(f"DEBUG learn_body_styles EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        _audit_event(
            "learn_body.error",
            request,
            input=_file_ref(req.input),
            error_type=type(e).__name__,
            error=_bounded_str(e, 500),
            duration_ms=int((time.time() - t0) * 1000),
        )
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/cover/analyze")
def cover_analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    try:
        cfg = load_config(req.config_path)
        if req.model:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["model"] = req.model
            c["vision"] = v
            cfg["cover"] = c
        if req.min_confidence is not None:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["min_confidence"] = float(req.min_confidence)
            c["vision"] = v
            cfg["cover"] = c
        if req.styles:
            c = cfg.get("cover", {}) or {}
            s = c.get("styles", {}) or {}
            for role in ("title", "subtitle", "author"):
                ov = (req.styles.get(role) or {}) if isinstance(req.styles, dict) else {}
                if ov:
                    cur = s.get(role, {}) or {}
                    f = cur.get("font", {}) or {}
                    f.update({k: v for k, v in ov.items() if v is not None})
                    cur["font"] = f
                    s[role] = cur
            c["styles"] = s
            cfg["cover"] = c
        # Ensure no layout changes during analyze unless explicitly disabled
        res = run_cover_pipeline(
            input_path=req.input,
            config=cfg,
            out_dir=(cfg.get("output", {}) or {}).get("dir", "output"),
            dry_run=False,
            no_layout=bool(req.no_layout),
            vision=bool(req.vision),
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/toc/apply")
def toc_apply(req: TocApplyRequest, request: Request) -> Dict[str, Any]:
    """Apply TOC (Table of Contents) to one or more files."""
    t0 = time.time()
    _audit_event("toc_apply.started", request, **_toc_request_summary(req))
    print(f"DEBUG: toc_apply called. input={req.input}, batch_files={req.batch_files}")
    try:
        cfg = load_config(req.config_path)
        mode = req.mode or "structured"

        # LibreOffice settings
        toc_cfg = (cfg.get("toc", {}) or {})
        lo_cfg = (toc_cfg.get("libreoffice", {}) or {})
        soffice_bin = req.soffice or lo_cfg.get("binary") or "soffice"
        timeout = int(req.timeout or lo_cfg.get("timeout", 120))
        use_docker = bool(lo_cfg.get("use_docker", True))
        docker_image = lo_cfg.get("docker_image")  # Custom image with fonts
        out_cfg = (cfg.get("output", {}) or {})
        base_out = out_cfg.get("dir") or "output"
        lo_dir = lo_cfg.get("dir") or os.path.join(base_out, lo_cfg.get("subdir", "lo_toc"))

        def process_single_toc(input_path: str) -> Dict[str, Any]:
            """Process TOC for a single file."""
            toc_res = build_toc(input_path=input_path, config=cfg, mode=mode)
            pre_lo_path = toc_res.get("output_path")
            if not pre_lo_path:
                return {"error": "build_toc did not produce an output file", "input_path": input_path}

            print(f"DEBUG toc_apply: calling run_libreoffice_convert for {input_path}")
            lo_res = run_libreoffice_convert(
                pre_lo_path,
                soffice=soffice_bin,
                out_dir=lo_dir,
                timeout=timeout,
                use_docker=use_docker,
                docker_image=docker_image,
            )

            final_path = lo_res.get("output_path") or pre_lo_path
            result: Dict[str, Any] = {
                "toc": toc_res.get("toc"),
                "pre_libreoffice_output_path": pre_lo_path,
                "output_path": final_path,
                "libreoffice_ok": lo_res.get("ok"),
            }
            if not lo_res.get("ok"):
                result["toc_error"] = lo_res.get("error") or lo_res.get("stderr")
            return result

        batch_files = [p for p in (req.batch_files or []) if p]
        if batch_files:
            results: List[Dict[str, Any]] = []
            zip_items: List[Dict[str, str]] = []

            for path in batch_files:
                print(f"DEBUG toc_apply batch: processing {path}")
                r = process_single_toc(path)
                results.append({"input_path": path, "result": r})
                out_path = r.get("output_path")
                if out_path and os.path.isfile(out_path):
                    zip_items.append({"input_path": path, "output_path": str(out_path)})

            zip_path = _build_batch_zip(zip_items, req.batch_id)
            resp: Dict[str, Any] = {
                "batch": {
                    "id": req.batch_id,
                    "count": len(batch_files),
                    "items": results,
                },
                "output_path": zip_path,
            }
            download_meta = _build_download_meta(zip_path)
            if download_meta:
                resp["download"] = download_meta
            _audit_event(
                "toc_apply.completed",
                request,
                ok=True,
                batch_id=req.batch_id,
                batch_count=len(batch_files),
                output=_file_ref(zip_path),
                download=resp.get("download"),
                duration_ms=int((time.time() - t0) * 1000),
            )
            return resp

        # Single file mode
        toc_res = build_toc(input_path=req.input, config=cfg, mode=mode)
        pre_lo_path = toc_res.get("output_path")
        if not pre_lo_path:
            raise HTTPException(status_code=500, detail="build_toc did not produce an output file")

        lo_res = run_libreoffice_convert(
            pre_lo_path,
            soffice=soffice_bin,
            out_dir=lo_dir,
            timeout=timeout,
            use_docker=use_docker,
            docker_image=docker_image,
        )

        if not lo_res.get("ok"):
            err = lo_res.get("error") or f"LibreOffice failed with code {lo_res.get('returncode')}"
            raise HTTPException(status_code=500, detail=f"LibreOffice TOC update failed: {err}")

        final_path = lo_res.get("output_path") or pre_lo_path

        res: Dict[str, Any] = {
            "toc": toc_res.get("toc"),
            "pre_libreoffice_output_path": pre_lo_path,
            "output_path": final_path,
            "libreoffice": {
                "ok": lo_res.get("ok"),
                "returncode": lo_res.get("returncode"),
                "stdout": lo_res.get("stdout"),
                "stderr": lo_res.get("stderr"),
                "command": lo_res.get("command"),
            },
        }

        pdf_path = lo_res.get("pdf_output_path")
        if pdf_path:
            res["pdf_output_path"] = pdf_path

        # Build ZIP with both DOCX and PDF for download
        if final_path and pdf_path:
            zip_path = _build_single_zip(final_path, pdf_path)
            if zip_path:
                res["zip_path"] = zip_path
                download_meta = _build_download_meta(zip_path)
                if download_meta:
                    res["download"] = download_meta
        else:
            download_meta = _build_download_meta(final_path)
            if download_meta:
                res["download"] = download_meta

        _audit_event(
            "toc_apply.completed",
            request,
            ok=True,
            batch_id=req.batch_id,
            output=_file_ref(res.get("output_path")),
            pdf_output=_file_ref(res.get("pdf_output_path")),
            download=res.get("download"),
            duration_ms=int((time.time() - t0) * 1000),
        )
        return res
    except Exception as e:
        _audit_event(
            "toc_apply.error",
            request,
            error_type=type(e).__name__,
            error=_bounded_str(e, 500),
            duration_ms=int((time.time() - t0) * 1000),
        )
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/whole/analyze")
def whole_analyze(req: AnalyzeRequest, request: Request) -> Dict[str, Any]:
    """Analyze styles in the whole document body (beyond the cover).

    This endpoint performs a read-only pass over the DOCX and returns
    an inventory of paragraph styles and special formatting in the
    body section. It does not modify or save the document.
    """
    t0 = time.time()
    _audit_event("whole_analyze.started", request, **_analyze_request_summary(req))
    try:
        cfg = load_config(req.config_path)
        res = analyze_whole_document(
            input_path=req.input,
            config=cfg,
        )
        _audit_event(
            "whole_analyze.completed",
            request,
            ok=True,
            input=_file_ref(req.input),
            summary=(res.get("whole", {}) or {}).get("summary") if isinstance(res, dict) else None,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return res
    except Exception as e:
        _audit_event(
            "whole_analyze.error",
            request,
            input=_file_ref(req.input),
            error_type=type(e).__name__,
            error=_bounded_str(e, 500),
            duration_ms=int((time.time() - t0) * 1000),
        )
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/whole/apply")
def whole_apply(req: ApplyRequest, request: Request) -> Dict[str, Any]:
    """Apply whole-document normalization to the body (beyond the cover)."""
    t0 = time.time()
    _audit_event("whole_apply.started", request, **_apply_request_summary(req))
    print(f"DEBUG: whole_apply called. update_toc={req.update_toc}, input={req.input}")
    try:
        cfg = load_config(req.config_path)
        # Centralized overrides for Body style coming from the UI.
        # Only properties explicitly set in UI are applied - we do NOT merge
        # with existing config.yaml values to preserve original document formatting.
        if req.styles and isinstance(req.styles, dict):  # type: ignore[redundant-expr]
            body_ov = req.styles.get("body")
            if isinstance(body_ov, dict):
                so = (cfg.get("style_overrides") or {}) or {}
                # Start with empty dict - only add properties explicitly set in UI
                new_body: Dict[str, Any] = {}
                fam = body_ov.get("family")
                if isinstance(fam, str) and fam.strip():
                    new_body["font"] = fam.strip()
                size_val = body_ov.get("size_pt")
                if isinstance(size_val, (int, float)) and size_val > 0:
                    new_body["size_pt"] = float(size_val)
                align = body_ov.get("align")
                if isinstance(align, str) and align.strip() and align.strip() != "keep":
                    new_body["align"] = align.strip()
                if "bold" in body_ov:
                    new_body["bold"] = bool(body_ov.get("bold"))
                if "italic" in body_ov:
                    new_body["italic"] = bool(body_ov.get("italic"))
                line_spacing = body_ov.get("line_spacing")
                if isinstance(line_spacing, (int, float)) and line_spacing > 0:
                    new_body["line_spacing"] = float(line_spacing)
                spacing_before = body_ov.get("spacing_before_pt")
                if isinstance(spacing_before, (int, float)) and spacing_before >= 0:
                    new_body["spacing_before_pt"] = float(spacing_before)
                spacing_after = body_ov.get("spacing_after_pt")
                if isinstance(spacing_after, (int, float)) and spacing_after >= 0:
                    new_body["spacing_after_pt"] = float(spacing_after)
                so["Body"] = new_body
                cfg["style_overrides"] = so
            # Headings (chapter titles) style overrides
            headings_ov = req.styles.get("headings")
            if isinstance(headings_ov, dict):
                so = (cfg.get("style_overrides") or {}) or {}
                new_headings: Dict[str, Any] = {}
                fam = headings_ov.get("family")
                if isinstance(fam, str) and fam.strip():
                    new_headings["font"] = fam.strip()
                size_val = headings_ov.get("size_pt")
                if isinstance(size_val, (int, float)) and size_val > 0:
                    new_headings["size_pt"] = float(size_val)
                align = headings_ov.get("align")
                if isinstance(align, str) and align.strip() and align.strip() != "keep":
                    new_headings["align"] = align.strip()
                if "bold" in headings_ov:
                    new_headings["bold"] = bool(headings_ov.get("bold"))
                if "italic" in headings_ov:
                    new_headings["italic"] = bool(headings_ov.get("italic"))
                if "all_caps" in headings_ov:
                    new_headings["all_caps"] = bool(headings_ov.get("all_caps"))
                so["Headings"] = new_headings
                cfg["style_overrides"] = so
            # Footer (page number) style overrides - stored in config for use in cover pipeline
            footer_ov = req.styles.get("footer")
            if isinstance(footer_ov, dict):
                new_footer: Dict[str, Any] = {}
                fam = footer_ov.get("font_family")
                if isinstance(fam, str) and fam.strip():
                    new_footer["font_family"] = fam.strip()
                size_val = footer_ov.get("size_pt")
                if isinstance(size_val, (int, float)) and size_val > 0:
                    new_footer["size_pt"] = float(size_val)
                if "bold" in footer_ov:
                    new_footer["bold"] = bool(footer_ov.get("bold"))
                if "italic" in footer_ov:
                    new_footer["italic"] = bool(footer_ov.get("italic"))
                if new_footer:
                    so = (cfg.get("style_overrides") or {}) or {}
                    so["Footer"] = new_footer
                    cfg["style_overrides"] = so
            specials_ov = req.styles.get("specials")
            if isinstance(specials_ov, dict):
                so_specials = (cfg.get("special_overrides") or {}) or {}
                for name, ov in specials_ov.items():
                    if not isinstance(ov, dict):
                        continue
                    cur = (so_specials.get(name) or {}) or {}
                    new = dict(cur)
                    fam = ov.get("family") or ov.get("font")
                    if isinstance(fam, str) and fam.strip():
                        new["font"] = fam.strip()
                    size_val = ov.get("size_pt")
                    if isinstance(size_val, (int, float)) and size_val > 0:
                        new["size_pt"] = float(size_val)
                    if "bold" in ov:
                        new["bold"] = bool(ov.get("bold"))
                    if "italic" in ov:
                        new["italic"] = bool(ov.get("italic"))
                    if "underline" in ov:
                        new["underline"] = bool(ov.get("underline"))
                    if "strike" in ov:
                        new["strike"] = bool(ov.get("strike"))
                    if "all_caps" in ov:
                        new["all_caps"] = bool(ov.get("all_caps"))
                    if "small_caps" in ov:
                        new["small_caps"] = bool(ov.get("small_caps"))
                    if new:
                        so_specials[name] = new
                cfg["special_overrides"] = so_specials
            _merge_ui_style_overrides(cfg, req.styles)
        # Persist any changes coming from GUI (Body style, layout flags, etc.).
        save_config(cfg, req.config_path)

        batch_files = [p for p in (req.batch_files or []) if p]
        if batch_files:
            results: List[Dict[str, Any]] = []
            zip_items: List[Dict[str, str]] = []
            
            # Prepare TOC settings if needed
            toc_mode = req.toc_mode or "structured"
            toc_cfg = (cfg.get("toc", {}) or {})
            lo_cfg = (toc_cfg.get("libreoffice", {}) or {})
            soffice_bin = lo_cfg.get("binary") or "soffice"
            timeout = int(lo_cfg.get("timeout", 120))
            use_docker = bool(lo_cfg.get("use_docker", True))
            docker_image = lo_cfg.get("docker_image")
            out_cfg = (cfg.get("output", {}) or {})
            base_out = out_cfg.get("dir") or "output"
            
            for path in batch_files:
                r = apply_whole_document(
                    input_path=path,
                    config=cfg,
                )
                
                # Chained TOC update for each file in batch
                if req.update_toc:
                    styled_path = r.get("output_path")
                    if styled_path and os.path.isfile(styled_path):
                        try:
                            print(f"DEBUG batch TOC: processing {path}")
                            toc_res = build_toc(input_path=styled_path, config=cfg, mode=toc_mode)
                            pre_lo_path = toc_res.get("output_path")
                            if pre_lo_path:
                                lo_res = run_libreoffice_convert(
                                    pre_lo_path,
                                    soffice=soffice_bin,
                                    out_dir=base_out,
                                    timeout=timeout,
                                    use_docker=use_docker,
                                    docker_image=docker_image,
                                )
                                if lo_res.get("ok"):
                                    final_path = lo_res.get("output_path")
                                    if final_path:
                                        r["output_path"] = final_path
                                        r["toc_updated"] = True
                                    pdf_path = lo_res.get("pdf_output_path")
                                    if pdf_path:
                                        r["pdf_output_path"] = pdf_path
                                else:
                                    r["toc_error"] = lo_res.get("error") or lo_res.get("stderr")
                        except Exception as e:
                            print(f"DEBUG batch TOC error: {e}")
                            r["toc_error"] = str(e)
                
                results.append({"input_path": path, "result": r})
                out_path = r.get("output_path")
                pdf_path = r.get("pdf_output_path")
                if out_path:
                    zip_items.append({
                        "input_path": path,
                        "output_path": str(out_path),
                        "pdf_path": str(pdf_path) if pdf_path else None,
                    })

            zip_path = _build_batch_zip(zip_items, req.batch_id)
            resp: Dict[str, Any] = {
                "batch": {
                    "id": req.batch_id,
                    "count": len(batch_files),
                    "items": results,
                },
                "output_path": zip_path,
                "debug": {"update_toc": req.update_toc},
            }
            download_meta = _build_download_meta(zip_path)
            if download_meta:
                resp["download"] = download_meta
            _audit_event(
                "whole_apply.completed",
                request,
                ok=True,
                batch_id=req.batch_id,
                batch_count=len(batch_files),
                output=_file_ref(zip_path),
                download=resp.get("download"),
                duration_ms=int((time.time() - t0) * 1000),
            )
            return resp

        res = apply_whole_document(
            input_path=req.input,
            config=cfg,
        )

        # Optional chained TOC update
        if req.update_toc:
            print("DEBUG: Entering chained TOC update block")
            style_out_path = res.get("output_path")
            print(f"DEBUG: style_out_path={style_out_path}")
            if style_out_path and os.path.isfile(style_out_path):
                try:
                    mode = req.toc_mode or "structured"
                    print(f"DEBUG: calling build_toc mode={mode}")
                    
                    # 1. Build/Insert TOC fields in the newly styled doc
                    toc_res = build_toc(input_path=style_out_path, config=cfg, mode=mode)
                    pre_lo_path = toc_res.get("output_path")
                    print(f"DEBUG: build_toc result path={pre_lo_path}")
                    
                    if pre_lo_path:
                        # 2. Update via LibreOffice
                        toc_cfg = (cfg.get("toc", {}) or {})
                        lo_cfg = (toc_cfg.get("libreoffice", {}) or {})
                        
                        soffice_bin = lo_cfg.get("binary") or "soffice"
                        timeout = int(lo_cfg.get("timeout", 120))
                        use_docker = bool(lo_cfg.get("use_docker", True))
                        docker_image = lo_cfg.get("docker_image")
                        
                        print(f"DEBUG: calling run_libreoffice_convert use_docker={use_docker}")
                        
                        out_cfg = (cfg.get("output", {}) or {})
                        base_out = out_cfg.get("dir") or "output"
                        # We use the same base output dir to keep it simple for the user download
                        lo_dir = base_out 
                        
                        lo_res = run_libreoffice_convert(
                            pre_lo_path,
                            soffice=soffice_bin,
                            out_dir=lo_dir,
                            timeout=timeout,
                            use_docker=use_docker,
                            docker_image=docker_image,
                        )
                        
                        print(f"DEBUG: run_libreoffice_convert result: ok={lo_res.get('ok')}")
                        if lo_res.get("ok"):
                            final_path = lo_res.get("output_path")
                            if final_path:
                                res["output_path"] = final_path
                                res["toc_updated"] = True
                                # Include PDF result if available
                                pdf_path = lo_res.get("pdf_output_path")
                                if pdf_path:
                                    res["pdf_output_path"] = pdf_path
                                    pdf_download = _build_download_meta(pdf_path)
                                    if pdf_download:
                                        res["pdf_download"] = pdf_download
                        else:
                            res["toc_error"] = lo_res.get("error") or lo_res.get("stderr")
                except Exception as e:
                    print(f"DEBUG: Exception in chained TOC: {e}")
                    res["toc_error"] = str(e)

        # Build ZIP with both DOCX and PDF for download
        docx_path = res.get("output_path")
        pdf_path = res.get("pdf_output_path")
        if docx_path and pdf_path:
            # Create ZIP with both files
            zip_path = _build_single_zip(docx_path, pdf_path)
            if zip_path:
                res["zip_path"] = zip_path
                download_meta = _build_download_meta(zip_path)
                if download_meta:
                    res["download"] = download_meta
        else:
            # Fallback to just DOCX
            download_meta = _build_download_meta(docx_path)
            if download_meta:
                res["download"] = download_meta
        
        res["debug"] = {"update_toc": req.update_toc, "toc_updated": res.get("toc_updated")}
        _audit_event(
            "whole_apply.completed",
            request,
            ok=True,
            batch_id=req.batch_id,
            output=_file_ref(res.get("output_path")),
            pdf_output=_file_ref(res.get("pdf_output_path")),
            download=res.get("download"),
            duration_ms=int((time.time() - t0) * 1000),
        )
        return res
    except Exception as e:
        _audit_event(
            "whole_apply.error",
            request,
            error_type=type(e).__name__,
            error=_bounded_str(e, 500),
            duration_ms=int((time.time() - t0) * 1000),
        )
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/apply")
def unified_apply(req: ApplyRequest, request: Request) -> Dict[str, Any]:
    """Unified apply endpoint that handles both Cover and Body styles.
    
    This endpoint:
    1. If apply_cover: runs AI detection + cover styles
    2. If apply_body: applies body/headings/footer styles
    3. Applies layout (sections, page numbering)
    4. If update_toc: updates TOC via LibreOffice
    5. Converts to PDF
    6. Returns ZIP with DOCX + PDF
    """
    t0 = time.time()
    _audit_event("apply.started", request, **_apply_request_summary(req))
    print(f"DEBUG: unified_apply called. apply_cover={req.apply_cover}, apply_body={req.apply_body}, update_toc={req.update_toc}")
    
    if not req.apply_cover and not req.apply_body:
        _audit_event("apply.rejected", request, reason="no_scope_selected", **_apply_request_summary(req))
        raise HTTPException(status_code=400, detail="At least one of apply_cover or apply_body must be True")
    
    try:
        cfg = load_config(req.config_path)
        
        # Setup model/confidence for vision
        if req.model:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["model"] = req.model
            c["vision"] = v
            cfg["cover"] = c
        if req.min_confidence is not None:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["min_confidence"] = float(req.min_confidence)
            c["vision"] = v
            cfg["cover"] = c
        
        # Apply cover styles from UI
        if req.styles:
            c = cfg.get("cover", {}) or {}
            s = c.get("styles", {}) or {}
            for role in ("title", "subtitle", "author"):
                ov = (req.styles.get(role) or {}) if isinstance(req.styles, dict) else {}
                if ov:
                    cur = s.get(role, {}) or {}
                    f = cur.get("font", {}) or {}
                    f.update({k: v for k, v in ov.items() if v is not None})
                    cur["font"] = f
                    s[role] = cur
            c["styles"] = s
            cfg["cover"] = c
            
            # Body style overrides
            body_ov = req.styles.get("body")
            if isinstance(body_ov, dict):
                so = (cfg.get("style_overrides") or {}) or {}
                new_body: Dict[str, Any] = {}
                fam = body_ov.get("family")
                if isinstance(fam, str) and fam.strip():
                    new_body["font"] = fam.strip()
                size_val = body_ov.get("size_pt")
                if isinstance(size_val, (int, float)) and size_val > 0:
                    new_body["size_pt"] = float(size_val)
                align = body_ov.get("align")
                if isinstance(align, str) and align.strip() and align.strip() != "keep":
                    new_body["align"] = align.strip()
                if "bold" in body_ov:
                    new_body["bold"] = bool(body_ov.get("bold"))
                if "italic" in body_ov:
                    new_body["italic"] = bool(body_ov.get("italic"))
                line_spacing = body_ov.get("line_spacing")
                if isinstance(line_spacing, (int, float)) and line_spacing > 0:
                    new_body["line_spacing"] = float(line_spacing)
                so["Body"] = new_body
                cfg["style_overrides"] = so
            
            # Headings style overrides
            headings_ov = req.styles.get("headings")
            if isinstance(headings_ov, dict):
                so = (cfg.get("style_overrides") or {}) or {}
                new_headings: Dict[str, Any] = {}
                fam = headings_ov.get("family")
                if isinstance(fam, str) and fam.strip():
                    new_headings["font"] = fam.strip()
                size_val = headings_ov.get("size_pt")
                if isinstance(size_val, (int, float)) and size_val > 0:
                    new_headings["size_pt"] = float(size_val)
                if "bold" in headings_ov:
                    new_headings["bold"] = bool(headings_ov.get("bold"))
                if "italic" in headings_ov:
                    new_headings["italic"] = bool(headings_ov.get("italic"))
                if "all_caps" in headings_ov:
                    new_headings["all_caps"] = bool(headings_ov.get("all_caps"))
                so["Headings"] = new_headings
                cfg["style_overrides"] = so
            
            # Footer style overrides
            footer_ov = req.styles.get("footer")
            if isinstance(footer_ov, dict):
                new_footer: Dict[str, Any] = {}
                fam = footer_ov.get("font_family")
                if isinstance(fam, str) and fam.strip():
                    new_footer["font_family"] = fam.strip()
                size_val = footer_ov.get("size_pt")
                if isinstance(size_val, (int, float)) and size_val > 0:
                    new_footer["size_pt"] = float(size_val)
                if "bold" in footer_ov:
                    new_footer["bold"] = bool(footer_ov.get("bold"))
                if "italic" in footer_ov:
                    new_footer["italic"] = bool(footer_ov.get("italic"))
                if new_footer:
                    so = (cfg.get("style_overrides") or {}) or {}
                    so["Footer"] = new_footer
                    cfg["style_overrides"] = so
            _merge_ui_style_overrides(cfg, req.styles)
        
        save_config(cfg, req.config_path)
        
        out_cfg = (cfg.get("output", {}) or {})
        out_dir = out_cfg.get("dir", "output")
        os.makedirs(out_dir, exist_ok=True)

        ai_totals = _new_ai_totals()

        batch_files = [p for p in (req.batch_files or []) if p]
        if batch_files:
            results: List[Dict[str, Any]] = []
            zip_items: List[Dict[str, str]] = []
            report_rows: List[Dict[str, Any]] = []

            batch_name = req.batch_id or f"batch_{int(time.time())}"
            batch_root: Optional[str] = None
            if req.batch_id:
                candidate = os.path.join(UPLOADS_DIR, req.batch_id)
                if os.path.isdir(candidate):
                    batch_root = os.path.abspath(candidate)

            for path in batch_files:
                inp_abs = os.path.abspath(os.path.join(os.getcwd(), path))
                rel_dir = ""
                if batch_root:
                    try:
                        rel_to_root = os.path.relpath(inp_abs, batch_root)
                    except Exception:
                        rel_to_root = None
                    if rel_to_root and not str(rel_to_root).startswith(".."):
                        rel_dir = os.path.dirname(str(rel_to_root))

                file_out_dir = os.path.join(out_dir, batch_name, rel_dir) if rel_dir else os.path.join(out_dir, batch_name)
                os.makedirs(file_out_dir, exist_ok=True)

                cfg_file = copy.deepcopy(cfg)
                out_cfg_file = (cfg_file.get("output", {}) or {})
                out_cfg_file["dir"] = file_out_dir
                cfg_file["output"] = out_cfg_file

                r: Dict[str, Any] = {}
                current = path

                if req.apply_cover:
                    cover_res = run_cover_pipeline(
                        input_path=current,
                        config=cfg_file,
                        out_dir=file_out_dir,
                        dry_run=False,
                        no_layout=True,
                        vision=bool(req.vision),
                    )
                    r["cover"] = cover_res
                    try:
                        det = (cover_res.get("detection") if isinstance(cover_res, dict) else None) or None
                        if isinstance(det, dict):
                            _add_ai_usage(
                                ai_totals,
                                det.get("ai_usage"),
                                {
                                    "batch_id": req.batch_id,
                                    "input_path": path,
                                    "kind": "cover_vision",
                                },
                            )
                    except Exception:
                        pass
                    if cover_res.get("output_path"):
                        current = cover_res["output_path"]

                if req.apply_body:
                    body_res = apply_whole_document(
                        input_path=current,
                        config=cfg_file,
                    )
                    r["body"] = body_res
                    if body_res.get("output_path"):
                        current = body_res["output_path"]

                r["output_path"] = current

                toc_cfg = (cfg_file.get("toc", {}) or {})
                lo_cfg = (toc_cfg.get("libreoffice", {}) or {})
                soffice_bin = lo_cfg.get("binary") or "soffice"
                timeout = int(lo_cfg.get("timeout", 120))
                use_docker = bool(lo_cfg.get("use_docker", True))
                docker_image = lo_cfg.get("docker_image")

                lo_input = current
                if req.update_toc:
                    toc_mode = req.toc_mode or "structured"
                    toc_res = build_toc(input_path=lo_input, config=cfg_file, mode=toc_mode)
                    pre_lo_path = toc_res.get("output_path")
                    if pre_lo_path:
                        lo_input = pre_lo_path
                    r["toc"] = toc_res

                lo_res = run_libreoffice_convert(
                    lo_input,
                    soffice=soffice_bin,
                    out_dir=file_out_dir,
                    timeout=timeout,
                    use_docker=use_docker,
                    docker_image=docker_image,
                )
                if lo_res.get("ok"):
                    final_path = lo_res.get("output_path")
                    if final_path:
                        r["output_path"] = final_path
                    pdf_out = lo_res.get("pdf_output_path")
                    if pdf_out:
                        r["pdf_output_path"] = pdf_out
                    r["libreoffice_ok"] = True
                else:
                    r["libreoffice_error"] = lo_res.get("error") or lo_res.get("stderr")

                results.append({"input_path": path, "result": r})

                out_path = r.get("output_path")
                pdf_path = r.get("pdf_output_path")
                if out_path:
                    zip_items.append(
                        {
                            "input_path": path,
                            "output_path": str(out_path),
                            "pdf_path": str(pdf_path) if pdf_path else None,
                        }
                    )

                detection = None
                if req.apply_cover:
                    try:
                        cover_part = r.get("cover")
                        if isinstance(cover_part, dict):
                            detection = cover_part.get("detection")
                    except Exception:
                        detection = None
                if not detection:
                    try:
                        det_only = run_cover_pipeline(
                            input_path=path,
                            config=cfg_file,
                            out_dir=file_out_dir,
                            dry_run=True,
                            no_layout=True,
                            vision=bool(req.vision),
                        )
                        detection = det_only.get("detection")
                        try:
                            det = det_only.get("detection") if isinstance(det_only, dict) else None
                            if isinstance(det, dict):
                                _add_ai_usage(
                                    ai_totals,
                                    det.get("ai_usage"),
                                    {
                                        "batch_id": req.batch_id,
                                        "input_path": path,
                                        "kind": "cover_vision_dry_run",
                                    },
                                )
                        except Exception:
                            pass
                    except Exception:
                        detection = None

                texts = _extract_cover_texts_for_report(path, detection)
                report_rows.append(
                    {
                        "author": texts.get("author") or "",
                        "title": texts.get("title") or "",
                        "subtitle": texts.get("subtitle") or "",
                        "pages": _count_pdf_pages(pdf_path),
                        "filename": os.path.basename(path),
                    }
                )

            report_path: Optional[str] = None
            report_error: Optional[str] = None
            extra_files: List[Dict[str, str]] = []
            try:
                report_path = _write_batch_report_xlsx(
                    report_rows,
                    os.path.join(OUTPUT_DIR, f"{batch_name}_report.xlsx"),
                )
                if report_path:
                    extra_files.append({"path": report_path, "arcname": "report.xlsx"})
            except Exception as e:
                report_error = str(e)

            zip_path = _build_batch_zip(
                zip_items,
                (req.batch_id or batch_name),
                extra_files=extra_files or None,
            )
            resp: Dict[str, Any] = {
                "batch": {
                    "id": req.batch_id,
                    "count": len(batch_files),
                    "items": results,
                },
                "output_path": zip_path,
                "report_path": report_path,
                "ai_cost": ai_totals,
            }
            if report_error:
                resp["report_error"] = report_error
            download_meta = _build_download_meta(zip_path)
            if download_meta:
                resp["download"] = download_meta
            _audit_event(
                "apply.completed",
                request,
                ok=True,
                batch_id=req.batch_id,
                batch_count=len(batch_files),
                output=_file_ref(zip_path),
                report=_file_ref(report_path),
                download=resp.get("download"),
                ai_cost=ai_totals,
                report_error=report_error,
                duration_ms=int((time.time() - t0) * 1000),
            )
            return resp

        result: Dict[str, Any] = {}
        current_path = req.input
        
        # Step 1: Apply cover styles if requested
        if req.apply_cover:
            print(f"DEBUG: Applying cover styles with vision={req.vision}")
            cover_res = run_cover_pipeline(
                input_path=current_path,
                config=cfg,
                out_dir=out_dir,
                dry_run=False,
                no_layout=True,  # We'll apply layout after body styles
                vision=bool(req.vision),
            )
            # Debug: log detection result
            detection = cover_res.get("detection", {})
            print(f"DEBUG: cover detection skip={detection.get('skip')}, warnings={detection.get('warnings')}, assignments={detection.get('assignments')}")
            print(f"DEBUG: cover applied={cover_res.get('applied')}")
            result["cover"] = cover_res
            try:
                det = (cover_res.get("detection") if isinstance(cover_res, dict) else None) or None
                if isinstance(det, dict):
                    _add_ai_usage(
                        ai_totals,
                        det.get("ai_usage"),
                        {
                            "batch_id": req.batch_id,
                            "input_path": req.input,
                            "kind": "cover_vision",
                        },
                    )
            except Exception:
                pass
            if cover_res.get("output_path"):
                current_path = cover_res["output_path"]
        
        # Step 2: Apply body styles if requested
        if req.apply_body:
            print(f"DEBUG: Applying body styles")
            body_res = apply_whole_document(
                input_path=current_path,
                config=cfg,
            )
            result["body"] = body_res
            if body_res.get("output_path"):
                current_path = body_res["output_path"]
        
        result["output_path"] = current_path
        
        # Step 3: TOC update + PDF generation via LibreOffice
        if req.update_toc or True:  # Always generate PDF
            print(f"DEBUG: TOC/PDF generation")
            toc_cfg = (cfg.get("toc", {}) or {})
            lo_cfg = (toc_cfg.get("libreoffice", {}) or {})
            soffice_bin = lo_cfg.get("binary") or "soffice"
            timeout = int(lo_cfg.get("timeout", 120))
            use_docker = bool(lo_cfg.get("use_docker", True))
            docker_image = lo_cfg.get("docker_image")
            
            if req.update_toc:
                toc_mode = req.toc_mode or "structured"
                toc_res = build_toc(input_path=current_path, config=cfg, mode=toc_mode)
                pre_lo_path = toc_res.get("output_path")
                if pre_lo_path:
                    current_path = pre_lo_path
                result["toc"] = toc_res
            
            # Convert via LibreOffice (updates TOC + generates PDF)
            lo_res = run_libreoffice_convert(
                current_path,
                soffice=soffice_bin,
                out_dir=out_dir,
                timeout=timeout,
                use_docker=use_docker,
                docker_image=docker_image,
            )
            
            if lo_res.get("ok"):
                final_path = lo_res.get("output_path")
                if final_path:
                    result["output_path"] = final_path
                pdf_path = lo_res.get("pdf_output_path")
                if pdf_path:
                    result["pdf_output_path"] = pdf_path
                result["libreoffice_ok"] = True
            else:
                result["libreoffice_error"] = lo_res.get("error") or lo_res.get("stderr")
        
        # Step 4: Build ZIP with DOCX + PDF
        docx_path = result.get("output_path")
        pdf_path = result.get("pdf_output_path")
        if docx_path and pdf_path:
            zip_path = _build_single_zip(docx_path, pdf_path)
            if zip_path:
                result["zip_path"] = zip_path
                download_meta = _build_download_meta(zip_path)
                if download_meta:
                    result["download"] = download_meta
        elif docx_path:
            download_meta = _build_download_meta(docx_path)
            if download_meta:
                result["download"] = download_meta

        result["ai_cost"] = ai_totals
        _audit_event(
            "apply.completed",
            request,
            ok=True,
            batch_id=req.batch_id,
            output=_file_ref(result.get("output_path")),
            pdf_output=_file_ref(result.get("pdf_output_path")),
            download=result.get("download"),
            ai_cost=ai_totals,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return result
    except Exception as e:
        print(f"DEBUG: unified_apply error: {e}")
        _audit_event(
            "apply.error",
            request,
            error_type=type(e).__name__,
            error=_bounded_str(e, 500),
            duration_ms=int((time.time() - t0) * 1000),
        )
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/files/simples")
def list_simples() -> Dict[str, Any]:
    try:
        base = os.path.join(os.getcwd(), "Simples")
        if not os.path.isdir(base):
            return {"files": []}
        files = []
        for name in sorted(os.listdir(base)):
            n = str(name)
            if n.startswith("~$"):
                continue
            if n.lower().endswith(".docx"):
                files.append(f"Simples/{n}")
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/batch/status/{batch_id}")
def batch_status(batch_id: str, request: Request) -> Dict[str, Any]:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "", str(batch_id or ""))
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid batch id")

    zip_path = os.path.join(OUTPUT_DIR, f"{safe_id}.zip")
    report_path = os.path.join(OUTPUT_DIR, f"{safe_id}_report.xlsx")
    out_dir = os.path.join(OUTPUT_DIR, safe_id)
    upload_dir = os.path.join(UPLOADS_DIR, safe_id)

    outputs: List[Dict[str, Any]] = []
    if os.path.isdir(out_dir):
        try:
            for name in sorted(os.listdir(out_dir)):
                if name.startswith("."):
                    continue
                rel = os.path.join("output", safe_id, name).replace(os.sep, "/")
                outputs.append(_file_ref(rel) or {"path": rel, "name": name})
        except Exception:
            outputs = []

    uploads: List[Dict[str, Any]] = []
    if os.path.isdir(upload_dir):
        try:
            for name in sorted(os.listdir(upload_dir)):
                if name.startswith("."):
                    continue
                rel = os.path.join("Uploads", safe_id, name).replace(os.sep, "/")
                uploads.append(_file_ref(rel) or {"path": rel, "name": name})
        except Exception:
            uploads = []

    resp: Dict[str, Any] = {
        "ok": True,
        "batch_id": safe_id,
        "ready": os.path.exists(zip_path),
        "upload_count": len(uploads),
        "output_count": len(outputs),
        "uploads": uploads,
        "outputs": outputs,
        "zip": _file_ref(os.path.join("output", f"{safe_id}.zip").replace(os.sep, "/")) if os.path.exists(zip_path) else None,
        "report": _file_ref(os.path.join("output", f"{safe_id}_report.xlsx").replace(os.sep, "/")) if os.path.exists(report_path) else None,
    }
    if os.path.exists(zip_path):
        resp["download"] = _build_download_meta(zip_path)

    _audit_event(
        "batch_status.checked",
        request,
        batch_id=safe_id,
        ready=bool(resp.get("ready")),
        upload_count=len(uploads),
        output_count=len(outputs),
        download=resp.get("download"),
    )
    return resp


@app.get("/fonts/list")
def list_fonts() -> Dict[str, Any]:
    """Return list of available font families from the fonts directory."""
    try:
        fonts = _get_available_fonts()
        return {"fonts": fonts, "count": len(fonts)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ResetConfigRequest(BaseModel):
    config_path: Optional[str] = None


@app.post("/config/reset")
def reset_config(req: ResetConfigRequest, request: Request) -> Dict[str, Any]:
    """Reset configuration to default values."""
    t0 = time.time()
    _audit_event("config_reset.started", request, config_path=req.config_path)
    try:
        from gutendocx.core.config import _read_default_config_dict, save_config
        
        # Get default config
        default_cfg = _read_default_config_dict()
        
        # Save it to the config file
        config_path = req.config_path or "config.yaml"
        saved_path = save_config(default_cfg, config_path)
        
        resp = {
            "ok": True,
            "message": "Configuration reset to defaults",
            "config_path": saved_path,
        }
        _audit_event(
            "config_reset.completed",
            request,
            ok=True,
            config_path=saved_path,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return resp
    except Exception as e:
        _audit_event(
            "config_reset.error",
            request,
            error_type=type(e).__name__,
            error=_bounded_str(e, 500),
            duration_ms=int((time.time() - t0) * 1000),
        )
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/cover/apply")
def cover_apply(req: ApplyRequest) -> Dict[str, Any]:
    try:
        cfg = load_config(req.config_path)
        if req.model:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["model"] = req.model
            c["vision"] = v
            cfg["cover"] = c
        if req.min_confidence is not None:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["min_confidence"] = float(req.min_confidence)
            c["vision"] = v
            cfg["cover"] = c
        if req.styles:
            c = cfg.get("cover", {}) or {}
            s = c.get("styles", {}) or {}
            for role in ("title", "subtitle", "author"):
                ov = (req.styles.get(role) or {}) if isinstance(req.styles, dict) else {}
                if ov:
                    cur = s.get(role, {}) or {}
                    f = cur.get("font", {}) or {}
                    f.update({k: v for k, v in ov.items() if v is not None})
                    cur["font"] = f
                    s[role] = cur
            c["styles"] = s
            cfg["cover"] = c
        # Persist any changes coming from GUI (cover styles, vision params, etc.).
        save_config(cfg, req.config_path)

        batch_files = [p for p in (req.batch_files or []) if p]
        if batch_files:
            results: List[Dict[str, Any]] = []
            zip_items: List[Dict[str, str]] = []
            out_dir = (cfg.get("output", {}) or {}).get("dir", "output")
            for path in batch_files:
                r = run_cover_pipeline(
                    input_path=path,
                    config=cfg,
                    out_dir=out_dir,
                    dry_run=False,
                    no_layout=bool(req.no_layout),
                    vision=bool(req.vision),
                )
                results.append({"input_path": path, "result": r})
                out_path = r.get("output_path")
                if out_path:
                    zip_items.append(
                        {"input_path": path, "output_path": str(out_path)}
                    )

            zip_path = _build_batch_zip(zip_items, req.batch_id)
            resp: Dict[str, Any] = {
                "batch": {
                    "id": req.batch_id,
                    "count": len(batch_files),
                    "items": results,
                },
                "output_path": zip_path,
            }
            download_meta = _build_download_meta(zip_path)
            if download_meta:
                resp["download"] = download_meta
            return resp

        res = run_cover_pipeline(
            input_path=req.input,
            config=cfg,
            out_dir=(cfg.get("output", {}) or {}).get("dir", "output"),
            dry_run=False,
            no_layout=bool(req.no_layout),
            vision=bool(req.vision),
        )

        download_meta = _build_download_meta(res.get("output_path"))
        if download_meta:
            res["download"] = download_meta
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class DebugVisionRequest(BaseModel):
    input: str
    config_path: Optional[str] = None
    model: Optional[str] = None
    min_confidence: Optional[float] = None


@app.post("/debug/vision")
def debug_vision(req: DebugVisionRequest) -> Dict[str, Any]:
    try:
        cfg = load_config(req.config_path)
        if req.model:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["model"] = req.model
            c["vision"] = v
            cfg["cover"] = c
        if req.min_confidence is not None:
            c = cfg.get("cover", {}) or {}
            v = c.get("vision", {}) or {}
            v["min_confidence"] = float(req.min_confidence)
            c["vision"] = v
            cfg["cover"] = c
        d = detect_cover_roles_vision(req.input, cfg)
        return {
            "warnings": d.get("warnings"),
            "vision": d.get("vision"),
            "vision_items": d.get("vision_items"),
            "vision_details": d.get("vision_details"),
            "skip": d.get("skip"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
