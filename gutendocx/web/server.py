from typing import Optional, Any, Dict
import os
import time

from fastapi import FastAPI, HTTPException
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
    update_fields_on_open: Optional[bool] = None
    config_path: Optional[str] = None
    model: Optional[str] = None
    min_confidence: Optional[float] = None
    styles: Optional[Dict[str, Any]] = None


class ApplyRequest(BaseModel):
    input: str
    vision: bool = True
    no_layout: bool = True
    update_fields_on_open: Optional[bool] = None
    config_path: Optional[str] = None
    model: Optional[str] = None
    min_confidence: Optional[float] = None
    styles: Optional[Dict[str, Any]] = None


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "time": int(time.time())}


@app.post("/cover/analyze")
def cover_analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    try:
        cfg = load_config(req.config_path)
        if req.update_fields_on_open is not None:
            layout_cfg = (cfg.get("layout") or {}) or {}
            layout_cfg["update_fields_on_open"] = bool(req.update_fields_on_open)
            cfg["layout"] = layout_cfg
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
        if req.update_fields_on_open is not None:
            layout_cfg = (cfg.get("layout") or {}) or {}
            layout_cfg["update_fields_on_open"] = bool(req.update_fields_on_open)
            cfg["layout"] = layout_cfg
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
        if req.update_fields_on_open is not None:
            layout_cfg = (cfg.get("layout") or {}) or {}
            layout_cfg["update_fields_on_open"] = bool(req.update_fields_on_open)
            cfg["layout"] = layout_cfg
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
        # Persist any changes coming from GUI (Body style, layout flags, etc.).
        save_config(cfg, req.config_path)
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
        if req.update_fields_on_open is not None:
            layout_cfg = (cfg.get("layout") or {}) or {}
            layout_cfg["update_fields_on_open"] = bool(req.update_fields_on_open)
            cfg["layout"] = layout_cfg
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
