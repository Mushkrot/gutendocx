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
from gutendocx.core.cover import run_cover_pipeline
from gutendocx.core.vision import detect_cover_roles_vision
from gutendocx.core.whole import analyze_whole_document, apply_whole_document


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
            if not out_path:
                continue
            abs_out = os.path.abspath(out_path)
            if not os.path.exists(abs_out):
                continue
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


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "time": int(time.time())}


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
    """Apply whole-document normalization to the body (beyond the cover).

    This endpoint collapses non-protected paragraph styles in the body to
    Normal and maps special run-level formatting combinations (bold/italic
    etc.) to named character styles. It does not touch cover layout, TOC,
    headers, or footers.
    """
    try:
        cfg = load_config(req.config_path)
        # Centralized overrides for Body style coming from the UI.
        # These are merged into style_overrides.Body and persisted to
        # config.yaml so that subsequent runs reuse the same settings.
        if req.styles and isinstance(req.styles, dict):  # type: ignore[redundant-expr]
            body_ov = req.styles.get("body")
            if isinstance(body_ov, dict):
                so = (cfg.get("style_overrides") or {}) or {}
                cur_body = (so.get("Body") or {}) or {}
                new_body = dict(cur_body)
                fam = body_ov.get("family")
                if isinstance(fam, str) and fam.strip():
                    new_body["font"] = fam.strip()
                size_val = body_ov.get("size_pt")
                if isinstance(size_val, (int, float)) and size_val > 0:
                    new_body["size_pt"] = float(size_val)
                align = body_ov.get("align")
                if isinstance(align, str) and align.strip():
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
            for path in batch_files:
                r = apply_whole_document(
                    input_path=path,
                    config=cfg,
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

        res = apply_whole_document(
            input_path=req.input,
            config=cfg,
        )

        download_meta = _build_download_meta(res.get("output_path"))
        if download_meta:
            res["download"] = download_meta
        return res
    except Exception as e:
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
