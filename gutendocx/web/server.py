from typing import Optional, Any, Dict, List
import os
import time
import zipfile

from fastapi import FastAPI, HTTPException, UploadFile, File
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

FONTS_DIR = os.path.join(os.getcwd(), "fonts")


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


def _build_batch_zip(items: List[Dict[str, str]], batch_id: Optional[str]) -> Optional[str]:
    """Create a ZIP archive for a batch of processed DOCX files.

    Each item must have keys:
      - input_path: original input path (relative to project root)
      - output_path: saved DOCX path on disk
      - pdf_path: (optional) saved PDF path on disk

    When batch_id is provided and the corresponding Uploads/batch_id directory
    exists, we preserve the original folder structure inside the ZIP by
    computing paths relative to that directory.
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

    return zip_path


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
async def upload_files(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    """Upload one or more DOCX files (or folders) and store them under Uploads/.

    The client is expected to send each file with its relative path as the
    filename (e.g. using file.webkitRelativePath on the web). We preserve this
    structure under a generated batch directory.
    """

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    batch_id = f"batch_{int(time.time())}"
    batch_dir = os.path.join(UPLOADS_DIR, batch_id)
    os.makedirs(batch_dir, exist_ok=True)

    saved: List[Dict[str, str]] = []

    for f in files:
        rel = f.filename or f.filename or "document.docx"
        rel = rel.replace("\\", "/").strip("/")
        base_name = os.path.basename(rel) or "document.docx"
        # Skip Word lock/owner files (~$...) and any non-DOCX files entirely.
        if base_name.startswith("~$") or not base_name.lower().endswith(".docx"):
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
            }
        )

    return {
        "batch_id": batch_id,
        "root": os.path.relpath(batch_dir, os.getcwd()).replace(os.sep, "/"),
        "files": saved,
    }


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
def config_learn_cover_styles(req: LearnCoverStylesRequest) -> Dict[str, Any]:
    """Learn cover styles from an existing document and optionally save to config.
    
    This endpoint:
    1. Uses AI vision (or heuristics) to detect Title/Subtitle/Author paragraphs
    2. Extracts their font/style parameters
    3. Optionally saves to config.yaml
    
    Useful for creating a baseline config from an already-formatted document.
    """
    print(f"DEBUG learn_cover_styles: input={req.input}, vision={req.vision}, save_config={req.save_config}")
    try:
        cfg = load_config(req.config_path)
        
        result = learn_cover_styles(
            input_path=req.input,
            config=cfg,
            vision=req.vision,
        )
        
        print(f"DEBUG learn_cover_styles result: ok={result.get('ok')}, styles={result.get('styles')}")
        print(f"DEBUG learn_cover_styles config_update: {result.get('config_update')}")
        
        if not result.get("ok"):
            print(f"DEBUG learn_cover_styles: NOT OK, returning early. error={result.get('error')}")
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
def toc_apply(req: TocApplyRequest) -> Dict[str, Any]:
    """Apply TOC (Table of Contents) to one or more files."""
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

        # Batch mode
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

        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/whole/analyze")
def whole_analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    """Analyze styles in the whole document body (beyond the cover).

    This endpoint performs a read-only pass over the DOCX and returns
    an inventory of paragraph styles and special formatting in the
    body section. It does not modify or save the document.
    """
    try:
        cfg = load_config(req.config_path)
        res = analyze_whole_document(
            input_path=req.input,
            config=cfg,
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/whole/apply")
def whole_apply(req: ApplyRequest) -> Dict[str, Any]:
    """Apply whole-document normalization to the body (beyond the cover)."""
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
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/apply")
def unified_apply(req: ApplyRequest) -> Dict[str, Any]:
    """Unified apply endpoint that handles both Cover and Body styles.
    
    This endpoint:
    1. If apply_cover: runs AI detection + cover styles
    2. If apply_body: applies body/headings/footer styles
    3. Applies layout (sections, page numbering)
    4. If update_toc: updates TOC via LibreOffice
    5. Converts to PDF
    6. Returns ZIP with DOCX + PDF
    """
    print(f"DEBUG: unified_apply called. apply_cover={req.apply_cover}, apply_body={req.apply_body}, update_toc={req.update_toc}")
    
    if not req.apply_cover and not req.apply_body:
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
        
        save_config(cfg, req.config_path)
        
        out_cfg = (cfg.get("output", {}) or {})
        out_dir = out_cfg.get("dir", "output")
        os.makedirs(out_dir, exist_ok=True)
        
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
        
        return result
    except Exception as e:
        print(f"DEBUG: unified_apply error: {e}")
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
def reset_config(req: ResetConfigRequest) -> Dict[str, Any]:
    """Reset configuration to default values."""
    try:
        from gutendocx.core.config import _read_default_config_dict, save_config
        
        # Get default config
        default_cfg = _read_default_config_dict()
        
        # Save it to the config file
        config_path = req.config_path or "config.yaml"
        saved_path = save_config(default_cfg, config_path)
        
        return {
            "ok": True,
            "message": "Configuration reset to defaults",
            "config_path": saved_path,
        }
    except Exception as e:
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
