from typing import Optional, Any, Dict
import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gutendocx.core.config import load_config
from gutendocx.core.cover import run_cover_pipeline


app = FastAPI(title="GutenDocx Web API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    input: str
    vision: bool = True
    no_layout: bool = True
    dry_run: bool = True
    config_path: Optional[str] = None


class ApplyRequest(BaseModel):
    input: str
    vision: bool = True
    no_layout: bool = True
    config_path: Optional[str] = None


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "time": int(time.time())}


@app.post("/cover/analyze")
def cover_analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    try:
        cfg = load_config(req.config_path)
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


@app.post("/cover/apply")
def cover_apply(req: ApplyRequest) -> Dict[str, Any]:
    try:
        cfg = load_config(req.config_path)
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
