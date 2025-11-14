from typing import Optional, Any, Dict
import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gutendocx.core.config import load_config
from gutendocx.core.cover import run_cover_pipeline
from gutendocx.core.vision import detect_cover_roles_vision


app = FastAPI(title="GutenDocx Web API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            dry_run=bool(req.dry_run),
            no_layout=bool(req.no_layout),
            vision=bool(req.vision),
        )
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
