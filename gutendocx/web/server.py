from typing import Optional, Any, Dict, List
from datetime import datetime, timezone
import hashlib
import json
import os
import copy
import re
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
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
JOBS_DIR = os.path.join(OUTPUT_DIR, "jobs")
try:
    os.makedirs(JOBS_DIR, exist_ok=True)
except Exception:
    pass


def _env_int(name: str, default: int, minimum: Optional[int] = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(str(raw).strip()) if raw is not None else int(default)
    except Exception:
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    return value


ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("GUTENDOCX_ADMIN_EMAILS", "highmac@gmail.com").split(",")
    if e.strip()
}
RETENTION_DAYS = _env_int("GUTENDOCX_RETENTION_DAYS", 15, 1)
SCHEDULED_CLEANUP_ENABLED = os.environ.get("GUTENDOCX_SCHEDULED_CLEANUP", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
SCHEDULED_CLEANUP_INTERVAL_SECONDS = _env_int("GUTENDOCX_CLEANUP_INTERVAL_SECONDS", 24 * 60 * 60, 60)
SCHEDULED_CLEANUP_INITIAL_DELAY_SECONDS = _env_int("GUTENDOCX_CLEANUP_INITIAL_DELAY_SECONDS", 60, 0)


AI_PRICES_PER_1M = {
    "gpt-5.4-nano": {"in": 0.20, "out": 1.25},
    "gpt-4o": {"in": 2.50, "out": 10.00},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4.1": {"in": 2.00, "out": 8.00},
    "gpt-4.1-mini": {"in": 0.40, "out": 1.60},
    "gpt-4.1-nano": {"in": 0.10, "out": 0.40},
    "gpt-5": {"in": 1.25, "out": 10.00},
    "gpt-5-mini": {"in": 0.25, "out": 2.00},
    "gpt-5-nano": {"in": 0.05, "out": 0.40},
    "gpt-5.1": {"in": 1.25, "out": 10.00},
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


def _request_user_email(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    email = request.headers.get("cf-access-authenticated-user-email")
    if not email:
        return None
    email = email.strip().lower()
    return email or None


def _is_admin_request(request: Optional[Request]) -> bool:
    email = _request_user_email(request)
    return bool(email and email in ADMIN_EMAILS)


def _require_admin(request: Request) -> str:
    email = _request_user_email(request)
    if not email:
        _audit_event("admin.access.denied", request, reason="missing_cloudflare_access_email")
        raise HTTPException(status_code=401, detail="Cloudflare Access identity is required")
    if email not in ADMIN_EMAILS:
        _audit_event("admin.access.denied", request, reason="email_not_allowed", email=email)
        raise HTTPException(status_code=403, detail="Admin access is restricted")
    return email


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
            if request.url.path == "/static/admin.html":
                email = _request_user_email(request)
                if not email or email not in ADMIN_EMAILS:
                    _audit_event(
                        "admin.access.denied",
                        request,
                        reason="static_admin_html",
                        email=email,
                    )
                    return JSONResponse({"detail": "Admin access is restricted"}, status_code=403)
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


JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gutendocx-job")
JOB_LOCK = threading.RLock()
JOB_INDEX: Dict[str, Dict[str, Any]] = {}
JOB_CONTEXT = threading.local()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _job_path(job_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(job_id))
    return os.path.join(JOBS_DIR, f"{safe}.json")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return _bounded_str(value, 1000)


def _apply_job_signature(req: "ApplyRequest") -> str:
    data = {
        "batch_id": req.batch_id,
        "batch_files": [p for p in (req.batch_files or []) if p],
        "input": req.input,
        "config_path": req.config_path,
        "vision": bool(req.vision),
        "no_layout": bool(req.no_layout),
        "model": req.model,
        "min_confidence": req.min_confidence,
        "update_toc": bool(req.update_toc),
        "toc_mode": req.toc_mode,
        "apply_body": bool(req.apply_body),
        "apply_cover": bool(req.apply_cover),
        "styles": req.styles or {},
    }
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _save_job(job: Dict[str, Any]) -> None:
    job_id = str(job.get("id") or "")
    if not job_id:
        return
    job["updated_at"] = _now_ms()
    tmp = _job_path(job_id) + ".tmp"
    path = _job_path(job_id)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _load_job_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _load_jobs_index() -> None:
    with JOB_LOCK:
        JOB_INDEX.clear()
        try:
            names = sorted(os.listdir(JOBS_DIR))
        except Exception:
            names = []
        for name in names:
            if not name.endswith(".json"):
                continue
            job = _load_job_file(os.path.join(JOBS_DIR, name))
            if not job or not job.get("id"):
                continue
            if job.get("status") in ("queued", "running"):
                job["status"] = "queued"
                job["resume_after_restart"] = True
                job["resumed_at"] = _now_ms()
                files = job.get("files")
                if isinstance(files, list):
                    for f in files:
                        if isinstance(f, dict) and f.get("status") == "running":
                            f["status"] = "queued"
                _save_job(job)
            JOB_INDEX[str(job["id"])] = job


def _job_public(job: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in job.items() if k not in ("request_payload", "traceback")}
    req_payload = job.get("request_payload") or {}
    batch_files = req_payload.get("batch_files") if isinstance(req_payload, dict) else None
    if isinstance(batch_files, list):
        out["batch_count"] = len(batch_files)
    progress = _job_progress(job)
    if progress:
        out["progress"] = progress
    return out


def _job_progress(job: Dict[str, Any]) -> Dict[str, Any]:
    files = job.get("files")
    if isinstance(files, list) and files:
        total = len(files)
        processed = len([f for f in files if isinstance(f, dict) and f.get("status") in ("completed", "failed", "skipped", "cancelled")])
        failed = len([f for f in files if isinstance(f, dict) and f.get("status") == "failed"])
        current = next((f for f in files if isinstance(f, dict) and f.get("status") == "running"), None)
        return {
            "total": total,
            "processed": processed,
            "succeeded": len([f for f in files if isinstance(f, dict) and f.get("status") == "completed"]),
            "failed": failed,
            "current_file": current.get("name") if isinstance(current, dict) else None,
            "ready": bool(job.get("status") == "completed" and job.get("download")),
        }
    payload = job.get("request_payload") or {}
    batch_files = payload.get("batch_files") if isinstance(payload, dict) else []
    total = len(batch_files) if isinstance(batch_files, list) else 0
    batch_id = payload.get("batch_id") if isinstance(payload, dict) else None
    output_path = None
    result = job.get("result")
    if isinstance(result, dict):
        output_path = result.get("output_path")
    ready = bool(output_path and os.path.exists(str(output_path)))
    processed = 0
    output_count = 0
    current_file = None
    if batch_id:
        batch_dir = os.path.join(OUTPUT_DIR, str(batch_id))
        try:
            if os.path.isdir(batch_dir):
                names = []
                for root, _, files in os.walk(batch_dir):
                    for fn in files:
                        if fn.lower().endswith((".docx", ".pdf")):
                            output_count += 1
                            names.append(os.path.relpath(os.path.join(root, fn), batch_dir))
                if total:
                    docx_done = {
                        os.path.splitext(os.path.basename(n))[0]
                        for n in names
                        if n.lower().endswith(".docx")
                    }
                    processed = min(total, len(docx_done))
                    if processed < total and isinstance(batch_files, list):
                        current_file = os.path.basename(str(batch_files[processed]))
        except Exception:
            pass
    if ready:
        processed = total or processed
    return {
        "total": total,
        "processed": processed,
        "succeeded": processed,
        "failed": 0,
        "output_count": output_count,
        "current_file": current_file,
        "ready": ready,
    }


def _current_job_id() -> Optional[str]:
    return getattr(JOB_CONTEXT, "job_id", None)


def _init_job_files(job_id: str, batch_files: List[str]) -> None:
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        if not job:
            return
        if not isinstance(job.get("files"), list) or len(job.get("files") or []) != len(batch_files):
            job["files"] = [
                {
                    "index": i,
                    "path": path,
                    "name": os.path.basename(str(path)),
                    "status": "queued",
                }
                for i, path in enumerate(batch_files)
            ]
        _save_job(job)


def _update_job_file(job_id: Optional[str], index: int, **fields: Any) -> None:
    if not job_id:
        return
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        if not job:
            return
        files = job.get("files")
        if not isinstance(files, list) or index < 0 or index >= len(files):
            return
        rec = files[index]
        if not isinstance(rec, dict):
            return
        rec.update(fields)
        rec["updated_at"] = _now_ms()
        _save_job(job)


def _get_job_file_record(index: int) -> Optional[Dict[str, Any]]:
    job_id = _current_job_id()
    if not job_id:
        return None
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        files = job.get("files") if isinstance(job, dict) else None
        if not isinstance(files, list) or index < 0 or index >= len(files):
            return None
        rec = files[index]
        return copy.deepcopy(rec) if isinstance(rec, dict) else None


def _job_file_started(index: int, path: str, total: int) -> None:
    job_id = _current_job_id()
    _update_job_file(job_id, index, status="running", started_at=_now_ms())
    _audit_event(
        "job.file.started",
        None,
        job_id=job_id,
        index=index,
        total=total,
        input=_file_ref(path),
    )


def _job_file_completed(index: int, path: str, result: Dict[str, Any], total: int) -> None:
    job_id = _current_job_id()
    _update_job_file(
        job_id,
        index,
        status="completed",
        finished_at=_now_ms(),
        output=_file_ref(result.get("output_path")),
        pdf_output=_file_ref(result.get("pdf_output_path")),
    )
    _audit_event(
        "job.file.completed",
        None,
        job_id=job_id,
        index=index,
        total=total,
        input=_file_ref(path),
        output=_file_ref(result.get("output_path")),
        pdf_output=_file_ref(result.get("pdf_output_path")),
    )


def _job_file_failed(index: int, path: str, error: BaseException, total: int) -> None:
    job_id = _current_job_id()
    _update_job_file(
        job_id,
        index,
        status="failed",
        finished_at=_now_ms(),
        error_type=type(error).__name__,
        error=_bounded_str(error, 1000),
    )
    _audit_event(
        "job.file.failed",
        None,
        job_id=job_id,
        index=index,
        total=total,
        input=_file_ref(path),
        error_type=type(error).__name__,
        error=_bounded_str(error, 1000),
    )


def _job_cancel_requested() -> bool:
    job_id = _current_job_id()
    if not job_id:
        return False
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        return bool(job and job.get("cancel_requested"))


def _mark_job_remaining_cancelled(start_index: int, total: int) -> None:
    job_id = _current_job_id()
    if not job_id:
        return
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        if not job:
            return
        files = job.get("files")
        if not isinstance(files, list):
            return
        for index in range(start_index, min(total, len(files))):
            rec = files[index]
            if isinstance(rec, dict) and rec.get("status") == "queued":
                rec["status"] = "cancelled"
                rec["finished_at"] = _now_ms()
                rec["updated_at"] = _now_ms()
        _save_job(job)


def _find_running_job(signature: str) -> Optional[Dict[str, Any]]:
    for job in JOB_INDEX.values():
        if job.get("signature") == signature and job.get("status") in ("queued", "running"):
            return job
    return None


def _run_apply_job(job_id: str) -> None:
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["started_at"] = _now_ms()
        _save_job(job)
    try:
        payload = copy.deepcopy(job.get("request_payload") or {})
        req = ApplyRequest(**payload)
        JOB_CONTEXT.job_id = job_id
        try:
            result = unified_apply(req, None)
        finally:
            JOB_CONTEXT.job_id = None
        with JOB_LOCK:
            job = JOB_INDEX.get(job_id) or job
            job["status"] = "cancelled" if isinstance(result, dict) and result.get("cancelled") else "completed"
            job["finished_at"] = _now_ms()
            job["result"] = _json_safe(result)
            if isinstance(result, dict):
                job["download"] = result.get("download")
                job["output_path"] = result.get("output_path")
                job["ai_cost"] = result.get("ai_cost")
            _save_job(job)
        _audit_event("job.completed", None, job_id=job_id, result_summary=_job_public(job))
    except Exception as e:
        status_code = getattr(e, "status_code", None)
        detail = getattr(e, "detail", None)
        with JOB_LOCK:
            job = JOB_INDEX.get(job_id) or {"id": job_id}
            job["status"] = "failed"
            job["finished_at"] = _now_ms()
            job["error_type"] = type(e).__name__
            job["error"] = _bounded_str(detail or e, 1000)
            if status_code:
                job["status_code"] = status_code
            job["traceback"] = traceback.format_exc(limit=20)
            JOB_INDEX[job_id] = job
            _save_job(job)
        _audit_event(
            "job.failed",
            None,
            job_id=job_id,
            error_type=type(e).__name__,
            error=_bounded_str(detail or e, 1000),
        )


_load_jobs_index()


@app.on_event("startup")
def _resume_jobs_on_startup() -> None:
    with JOB_LOCK:
        resumable = [
            str(job_id)
            for job_id, job in JOB_INDEX.items()
            if job.get("status") == "queued" and job.get("resume_after_restart")
        ]
        for job_id in resumable:
            job = JOB_INDEX.get(job_id)
            if not job:
                continue
            job["resume_after_restart"] = False
            job["resumed_at"] = _now_ms()
            _save_job(job)
            JOB_EXECUTOR.submit(_run_apply_job, job_id)
            _audit_event("job.resume.submitted", None, job_id=job_id)


def _scheduled_cleanup_loop() -> None:
    if SCHEDULED_CLEANUP_INITIAL_DELAY_SECONDS:
        time.sleep(SCHEDULED_CLEANUP_INITIAL_DELAY_SECONDS)
    while True:
        try:
            _admin_cleanup_impl(
                AdminFilesCleanupRequest(
                    older_than_days=RETENTION_DAYS,
                    dry_run=False,
                    include_uploads=True,
                    include_outputs=True,
                    include_job_records=True,
                ),
                None,
            )
            _audit_event("scheduled_cleanup.completed", None, older_than_days=RETENTION_DAYS)
        except Exception as e:
            _audit_event(
                "scheduled_cleanup.failed",
                None,
                older_than_days=RETENTION_DAYS,
                error_type=type(e).__name__,
                error=_bounded_str(e, 500),
            )
        time.sleep(SCHEDULED_CLEANUP_INTERVAL_SECONDS)


@app.on_event("startup")
def _start_scheduled_cleanup() -> None:
    if not SCHEDULED_CLEANUP_ENABLED:
        return
    thread = threading.Thread(target=_scheduled_cleanup_loop, name="gutendocx-cleanup", daemon=True)
    thread.start()
    _audit_event(
        "scheduled_cleanup.started",
        None,
        older_than_days=RETENTION_DAYS,
        interval_seconds=SCHEDULED_CLEANUP_INTERVAL_SECONDS,
        initial_delay_seconds=SCHEDULED_CLEANUP_INITIAL_DELAY_SECONDS,
    )


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
    ws.append(["Filename", "Title", "Subtitle", "Author", "Pages", "Status", "Error"])

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
                str(r.get("status") or "completed"),
                str(r.get("error") or ""),
            ]
        )

    # Center-align Pages column values (E)
    pages_alignment = Alignment(horizontal="center", vertical="center")
    for row in ws.iter_rows(min_row=2, min_col=5, max_col=5, max_row=ws.max_row):
        row[0].alignment = pages_alignment

    # Autofilter on header row for all populated rows
    ws.auto_filter.ref = f"A1:G{ws.max_row}"
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


@app.get("/admin")
def admin_panel(request: Request):
    _require_admin(request)
    path = os.path.join(STATIC_DIR, "admin.html")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Admin panel not found")


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


class JobsCleanupRequest(BaseModel):
    older_than_days: int = 30
    dry_run: bool = True
    include_uploads: bool = False
    include_outputs: bool = True


class AdminFilesCleanupRequest(BaseModel):
    older_than_days: int = RETENTION_DAYS
    dry_run: bool = True
    include_uploads: bool = True
    include_outputs: bool = True
    include_job_records: bool = True


class AdminModelRequest(BaseModel):
    model: str
    config_path: Optional[str] = None


def _configured_ai_model(config_path: Optional[str] = None) -> str:
    cfg = load_config(config_path)
    cover = cfg.get("cover", {}) if isinstance(cfg.get("cover"), dict) else {}
    vision = cover.get("vision", {}) if isinstance(cover.get("vision"), dict) else {}
    model = vision.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return "gpt-4o-mini"


def _model_label(model: str) -> str:
    labels = {
        "gpt-5.4-nano": "GPT-5.4 Nano",
        "gpt-5.1": "GPT-5.1",
        "gpt-5": "GPT-5",
        "gpt-5-mini": "GPT-5 Mini",
        "gpt-5-nano": "GPT-5 Nano",
        "gpt-4.1": "GPT-4.1",
        "gpt-4.1-mini": "GPT-4.1 Mini",
        "gpt-4.1-nano": "GPT-4.1 Nano",
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o Mini",
    }
    return labels.get(model, model)


def _model_options() -> List[Dict[str, Any]]:
    preferred = [
        "gpt-5.4-nano",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
    ]
    out = []
    for model in preferred:
        prices = AI_PRICES_PER_1M.get(model)
        if not prices:
            continue
        out.append(
            {
                "model": model,
                "label": _model_label(model),
                "input_per_1m": prices.get("in"),
                "output_per_1m": prices.get("out"),
                "estimated_request_usd": _calc_ai_cost_usd(model, 1500, 250),
            }
        )
    return out


def _force_configured_model(req: Any) -> str:
    model = _configured_ai_model(getattr(req, "config_path", None))
    try:
        req.model = model
    except Exception:
        pass
    return model


def _save_admin_model(model: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    model = str(model or "").strip()
    if model not in AI_PRICES_PER_1M:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    cfg = load_config(config_path)
    cover = cfg.get("cover", {}) if isinstance(cfg.get("cover"), dict) else {}
    vision = cover.get("vision", {}) if isinstance(cover.get("vision"), dict) else {}
    old_model = vision.get("model")
    vision["model"] = model
    cover["vision"] = vision
    cfg["cover"] = cover
    saved_path = save_config(cfg, config_path)
    return {"old_model": old_model, "model": model, "config_path": saved_path}


def _is_safe_child(path: str, parent: str) -> bool:
    try:
        abs_path = os.path.abspath(path)
        abs_parent = os.path.abspath(parent)
        return os.path.commonpath([abs_path, abs_parent]) == abs_parent
    except Exception:
        return False


def _cleanup_remove(path: str, dry_run: bool) -> Dict[str, Any]:
    item: Dict[str, Any] = {"path": path, "removed": False}
    try:
        if os.path.isdir(path):
            item["kind"] = "dir"
        elif os.path.isfile(path):
            item["kind"] = "file"
            item["size_bytes"] = os.path.getsize(path)
        else:
            item["kind"] = "missing"
            return item
        if not dry_run:
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            else:
                os.remove(path)
            item["removed"] = True
    except Exception as e:
        item["error"] = _bounded_str(e, 500)
    return item


def _job_cleanup_candidates(job: Dict[str, Any], include_outputs: bool, include_uploads: bool) -> List[str]:
    paths: List[str] = []
    job_id = job.get("id")
    if job_id:
        paths.append(_job_path(str(job_id)))

    payload = job.get("request_payload") if isinstance(job.get("request_payload"), dict) else {}
    batch_id = payload.get("batch_id") or job.get("batch_id")
    result = job.get("result") if isinstance(job.get("result"), dict) else {}

    if include_outputs:
        for key in ("output_path", "report_path"):
            val = result.get(key) or job.get(key)
            if isinstance(val, str) and _is_safe_child(val, OUTPUT_DIR):
                paths.append(val)
        if batch_id:
            for candidate in (
                os.path.join(OUTPUT_DIR, str(batch_id)),
                os.path.join(OUTPUT_DIR, f"{batch_id}.zip"),
                os.path.join(OUTPUT_DIR, f"{batch_id}_report.xlsx"),
            ):
                if _is_safe_child(candidate, OUTPUT_DIR):
                    paths.append(candidate)

    if include_uploads and batch_id:
        up = os.path.join(UPLOADS_DIR, str(batch_id))
        if _is_safe_child(up, UPLOADS_DIR):
            paths.append(up)

    seen = set()
    out = []
    for p in paths:
        ap = os.path.abspath(str(p))
        if ap in seen:
            continue
        seen.add(ap)
        out.append(ap)
    return out


def _cleanup_jobs_impl(req: JobsCleanupRequest, request: Optional[Request] = None) -> Dict[str, Any]:
    days = max(1, int(req.older_than_days or 30))
    cutoff_ms = _now_ms() - days * 24 * 60 * 60 * 1000
    eligible_statuses = {"completed", "failed", "interrupted", "cancelled"}
    items: List[Dict[str, Any]] = []
    jobs_seen = 0

    with JOB_LOCK:
        try:
            names = sorted(os.listdir(JOBS_DIR))
        except Exception:
            names = []
        for name in names:
            if not name.endswith(".json"):
                continue
            job = _load_job_file(os.path.join(JOBS_DIR, name))
            if not job:
                continue
            if job.get("status") not in eligible_statuses:
                continue
            finished = job.get("finished_at") or job.get("updated_at") or job.get("created_at") or 0
            try:
                finished_ms = int(finished)
            except Exception:
                finished_ms = 0
            if finished_ms > cutoff_ms:
                continue
            jobs_seen += 1
            for path in _job_cleanup_candidates(job, bool(req.include_outputs), bool(req.include_uploads)):
                if not (_is_safe_child(path, OUTPUT_DIR) or _is_safe_child(path, UPLOADS_DIR)):
                    continue
                items.append(_cleanup_remove(path, bool(req.dry_run)))
            if not req.dry_run and job.get("id"):
                JOB_INDEX.pop(str(job["id"]), None)

    summary = {
        "ok": True,
        "dry_run": bool(req.dry_run),
        "older_than_days": days,
        "jobs_matched": jobs_seen,
        "items_count": len(items),
        "items": items,
    }
    _audit_event("jobs.cleanup", request, **{k: v for k, v in summary.items() if k != "items"}, items=items[:100])
    return summary


@app.post("/jobs/cleanup")
def cleanup_jobs(req: JobsCleanupRequest, request: Request) -> Dict[str, Any]:
    return _cleanup_jobs_impl(req, request)


def _storage_excluded(path: str) -> bool:
    abs_path = os.path.abspath(path)
    if _is_safe_child(abs_path, JOBS_DIR):
        return True
    protected = {
        os.path.abspath(AUDIT_EVENTS_JSONL),
        os.path.abspath(AI_COSTS_JSONL),
    }
    if abs_path in protected:
        return True
    name = os.path.basename(abs_path)
    return name in {".gitkeep", ".gitignore"}


def _storage_cleanup_candidates(root: str, cutoff_ts: float) -> List[str]:
    root_abs = os.path.abspath(root)
    if not os.path.isdir(root_abs):
        return []
    candidates: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [
            d
            for d in dirnames
            if not _storage_excluded(os.path.join(dirpath, d))
        ]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if _storage_excluded(path):
                continue
            try:
                if os.path.getmtime(path) <= cutoff_ts:
                    candidates.append(path)
            except Exception:
                continue
    return sorted(candidates)


def _prune_empty_dirs(root: str, dry_run: bool) -> List[Dict[str, Any]]:
    root_abs = os.path.abspath(root)
    if not os.path.isdir(root_abs):
        return []
    items: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root_abs, topdown=False):
        if os.path.abspath(dirpath) == root_abs:
            continue
        if _storage_excluded(dirpath):
            continue
        try:
            if dirnames or filenames or os.listdir(dirpath):
                continue
            item: Dict[str, Any] = {"path": dirpath, "kind": "dir", "removed": False, "empty": True}
            if not dry_run:
                os.rmdir(dirpath)
                item["removed"] = True
            items.append(item)
        except Exception as e:
            items.append({"path": dirpath, "kind": "dir", "removed": False, "error": _bounded_str(e, 500)})
    return items


def _cleanup_storage_files(
    older_than_days: int,
    dry_run: bool,
    include_uploads: bool,
    include_outputs: bool,
) -> Dict[str, Any]:
    days = max(1, int(older_than_days or RETENTION_DAYS))
    cutoff_ts = time.time() - days * 24 * 60 * 60
    roots: List[str] = []
    if include_uploads:
        roots.append(UPLOADS_DIR)
    if include_outputs:
        roots.append(OUTPUT_DIR)

    items: List[Dict[str, Any]] = []
    for root in roots:
        for path in _storage_cleanup_candidates(root, cutoff_ts):
            if not _is_safe_child(path, root):
                continue
            items.append(_cleanup_remove(path, dry_run))
        if not dry_run:
            items.extend(_prune_empty_dirs(root, dry_run))

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "older_than_days": days,
        "cutoff_ts": int(cutoff_ts),
        "items_count": len(items),
        "items": items,
    }


def _admin_cleanup_impl(req: AdminFilesCleanupRequest, request: Optional[Request] = None) -> Dict[str, Any]:
    storage = _cleanup_storage_files(
        older_than_days=req.older_than_days,
        dry_run=bool(req.dry_run),
        include_uploads=bool(req.include_uploads),
        include_outputs=bool(req.include_outputs),
    )
    jobs = {"ok": True, "items_count": 0, "items": []}
    if req.include_job_records:
        jobs = _cleanup_jobs_impl(
            JobsCleanupRequest(
                older_than_days=max(1, int(req.older_than_days or RETENTION_DAYS)),
                dry_run=bool(req.dry_run),
                include_uploads=bool(req.include_uploads),
                include_outputs=bool(req.include_outputs),
            ),
            request,
        )
    summary = {
        "ok": True,
        "dry_run": bool(req.dry_run),
        "older_than_days": max(1, int(req.older_than_days or RETENTION_DAYS)),
        "storage": storage,
        "jobs": jobs,
        "items_count": int(storage.get("items_count") or 0) + int(jobs.get("items_count") or 0),
    }
    _audit_event(
        "admin.files.cleanup",
        request,
        dry_run=summary["dry_run"],
        older_than_days=summary["older_than_days"],
        storage_items=storage.get("items_count"),
        job_items=jobs.get("items_count"),
    )
    return summary


def _iter_jsonl(path: str, max_lines: Optional[int] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                    if max_lines and len(rows) >= max_lines:
                        break
    except FileNotFoundError:
        return []
    except Exception:
        return rows
    return rows


def _day_key(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "unknown"


def _cost_summary(days: int = 30, recent_limit: int = 200) -> Dict[str, Any]:
    now = int(time.time())
    days = max(1, int(days or 30))
    cutoff = now - days * 24 * 60 * 60
    rows = [r for r in _iter_jsonl(AI_COSTS_JSONL) if int(r.get("ts") or 0) >= cutoff]
    total = {
        "calls": len(rows),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    by_model: Dict[str, Dict[str, Any]] = {}
    by_day: Dict[str, Dict[str, Any]] = {}
    by_kind: Dict[str, Dict[str, Any]] = {}

    def add(bucket: Dict[str, Dict[str, Any]], key: str, row: Dict[str, Any]) -> None:
        rec = bucket.setdefault(
            key or "unknown",
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
        )
        rec["calls"] += 1
        rec["input_tokens"] += int(row.get("input_tokens") or 0)
        rec["output_tokens"] += int(row.get("output_tokens") or 0)
        rec["total_tokens"] += int(row.get("total_tokens") or 0)
        try:
            rec["cost_usd"] += float(row.get("cost_usd") or 0.0)
        except Exception:
            pass

    for row in rows:
        total["input_tokens"] += int(row.get("input_tokens") or 0)
        total["output_tokens"] += int(row.get("output_tokens") or 0)
        total["total_tokens"] += int(row.get("total_tokens") or 0)
        try:
            total["cost_usd"] += float(row.get("cost_usd") or 0.0)
        except Exception:
            pass
        add(by_model, str(row.get("model") or "unknown"), row)
        add(by_day, _day_key(int(row.get("ts") or 0)), row)
        add(by_kind, str(row.get("kind") or row.get("endpoint") or "unknown"), row)

    recent = sorted(rows, key=lambda r: int(r.get("ts") or 0), reverse=True)[: max(1, int(recent_limit or 200))]
    return {
        "ok": True,
        "days": days,
        "total": total,
        "by_model": by_model,
        "by_day": dict(sorted(by_day.items(), reverse=True)),
        "by_kind": by_kind,
        "recent": recent,
    }


def _storage_summary() -> Dict[str, Any]:
    def scan(root: str) -> Dict[str, Any]:
        total_files = 0
        total_bytes = 0
        oldest_ts = None
        newest_ts = None
        if os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not _storage_excluded(os.path.join(dirpath, d))]
                for name in filenames:
                    path = os.path.join(dirpath, name)
                    if _storage_excluded(path):
                        continue
                    try:
                        st = os.stat(path)
                    except Exception:
                        continue
                    total_files += 1
                    total_bytes += int(st.st_size)
                    mtime = int(st.st_mtime)
                    oldest_ts = mtime if oldest_ts is None else min(oldest_ts, mtime)
                    newest_ts = mtime if newest_ts is None else max(newest_ts, mtime)
        return {
            "path": root,
            "files": total_files,
            "bytes": total_bytes,
            "oldest_ts": oldest_ts,
            "newest_ts": newest_ts,
        }

    return {
        "uploads": scan(UPLOADS_DIR),
        "output": scan(OUTPUT_DIR),
        "retention_days": RETENTION_DAYS,
        "scheduled_cleanup_enabled": SCHEDULED_CLEANUP_ENABLED,
    }


@app.get("/admin/api/summary")
def admin_summary(request: Request, days: int = 30) -> Dict[str, Any]:
    email = _require_admin(request)
    resp = {
        "ok": True,
        "admin_email": email,
        "model": _configured_ai_model(),
        "model_options": _model_options(),
        "costs": _cost_summary(days=days),
        "storage": _storage_summary(),
    }
    _audit_event("admin.summary.viewed", request, days=days)
    return resp


@app.post("/admin/api/files/cleanup")
def admin_files_cleanup(req: AdminFilesCleanupRequest, request: Request) -> Dict[str, Any]:
    _require_admin(request)
    return _admin_cleanup_impl(req, request)


@app.get("/settings/model")
def get_model_setting(request: Request, config_path: Optional[str] = None) -> Dict[str, Any]:
    model = _configured_ai_model(config_path)
    return {
        "ok": True,
        "model": model,
        "label": _model_label(model),
        "admin_controlled": True,
        "is_admin": _is_admin_request(request),
        "options": _model_options(),
    }


@app.post("/admin/api/model")
def admin_set_model(req: AdminModelRequest, request: Request) -> Dict[str, Any]:
    email = _require_admin(request)
    result = _save_admin_model(req.model, req.config_path)
    _audit_event(
        "admin.model.updated",
        request,
        admin_email=email,
        old_model=result.get("old_model"),
        model=result.get("model"),
        config_path=result.get("config_path"),
    )
    return {"ok": True, **result, "options": _model_options()}


@app.get("/admin/api/files/cleanup/preview")
def admin_files_cleanup_preview(request: Request, older_than_days: int = RETENTION_DAYS) -> Dict[str, Any]:
    _require_admin(request)
    return _admin_cleanup_impl(
        AdminFilesCleanupRequest(
            older_than_days=max(1, int(older_than_days or RETENTION_DAYS)),
            dry_run=True,
            include_uploads=True,
            include_outputs=True,
            include_job_records=True,
        ),
        request,
    )


@app.post("/jobs/apply")
def start_apply_job(req: ApplyRequest, request: Request) -> Dict[str, Any]:
    batch_files = [p for p in (req.batch_files or []) if p]
    if not batch_files:
        raise HTTPException(status_code=400, detail="Background jobs currently require batch_files")
    if not req.apply_cover and not req.apply_body:
        raise HTTPException(status_code=400, detail="At least one of apply_cover or apply_body must be True")
    requested_model = req.model
    effective_model = _force_configured_model(req)
    if requested_model and requested_model != effective_model:
        _audit_event(
            "model.override_ignored",
            request,
            requested_model=requested_model,
            effective_model=effective_model,
            endpoint="/jobs/apply",
        )

    signature = _apply_job_signature(req)
    with JOB_LOCK:
        existing = _find_running_job(signature)
        if existing:
            _audit_event(
                "job.apply.duplicate_reused",
                request,
                job_id=existing.get("id"),
                signature=signature,
                **_apply_request_summary(req),
            )
            return {"job": _job_public(existing), "reused": True}

        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:10]}"
        payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
        job: Dict[str, Any] = {
            "id": job_id,
            "type": "apply",
            "status": "queued",
            "signature": signature,
            "created_at": _now_ms(),
            "updated_at": _now_ms(),
            "request_summary": _apply_request_summary(req),
            "request_payload": payload,
            "files": [
                {
                    "index": i,
                    "path": path,
                    "name": os.path.basename(str(path)),
                    "status": "queued",
                }
                for i, path in enumerate(batch_files)
            ],
        }
        JOB_INDEX[job_id] = job
        _save_job(job)
        JOB_EXECUTOR.submit(_run_apply_job, job_id)

    _audit_event(
        "job.apply.created",
        request,
        job_id=job_id,
        signature=signature,
        **_apply_request_summary(req),
    )
    return {"job": _job_public(job), "reused": False}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> Dict[str, Any]:
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        if not job:
            job = _load_job_file(_job_path(job_id))
            if job and job.get("id"):
                JOB_INDEX[str(job["id"])] = job
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        public = _job_public(job)
    _audit_event(
        "job.checked",
        request,
        job_id=job_id,
        status=public.get("status"),
        progress=public.get("progress"),
    )
    return {"job": public}


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> Dict[str, Any]:
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        if not job:
            job = _load_job_file(_job_path(job_id))
            if job and job.get("id"):
                JOB_INDEX[str(job["id"])] = job
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.get("status") not in ("queued", "running"):
            return {"job": _job_public(job), "cancel_requested": False, "reason": "not_running"}
        job["cancel_requested"] = True
        job["cancel_requested_at"] = _now_ms()
        if job.get("status") == "queued":
            job["status"] = "cancelled"
            job["finished_at"] = _now_ms()
        _save_job(job)
        public = _job_public(job)
    _audit_event("job.cancel_requested", request, job_id=job_id, status=public.get("status"))
    return {"job": public, "cancel_requested": True}


@app.post("/jobs/{job_id}/retry_failed")
def retry_failed_job(job_id: str, request: Request) -> Dict[str, Any]:
    with JOB_LOCK:
        job = JOB_INDEX.get(job_id)
        if not job:
            job = _load_job_file(_job_path(job_id))
            if job and job.get("id"):
                JOB_INDEX[str(job["id"])] = job
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        files = job.get("files")
        failed_paths = [
            str(f.get("path"))
            for f in (files or [])
            if isinstance(f, dict) and f.get("status") == "failed" and f.get("path")
        ]
        if not failed_paths:
            raise HTTPException(status_code=400, detail="No failed files to retry")
        payload = copy.deepcopy(job.get("request_payload") or {})
        payload["batch_files"] = failed_paths
        base_batch = payload.get("batch_id") or f"retry_{int(time.time())}"
        payload["batch_id"] = f"{base_batch}_retry_{int(time.time())}"
        req = ApplyRequest(**payload)

    result = start_apply_job(req, request)
    retry_job = result.get("job") if isinstance(result, dict) else None
    if isinstance(retry_job, dict):
        with JOB_LOCK:
            stored = JOB_INDEX.get(str(retry_job.get("id")))
            if stored:
                stored["retry_of"] = job_id
                _save_job(stored)
                retry_job = _job_public(stored)
    _audit_event(
        "job.retry_failed.created",
        request,
        job_id=job_id,
        retry_job_id=retry_job.get("id") if isinstance(retry_job, dict) else None,
        failed_count=len(failed_paths),
    )
    return {"job": retry_job, "failed_count": len(failed_paths), "reused": result.get("reused") if isinstance(result, dict) else False}


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


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


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
def cover_analyze(req: AnalyzeRequest, request: Request) -> Dict[str, Any]:
    try:
        requested_model = req.model
        effective_model = _force_configured_model(req)
        if requested_model and requested_model != effective_model:
            _audit_event(
                "model.override_ignored",
                request,
                requested_model=requested_model,
                effective_model=effective_model,
                endpoint="/cover/analyze",
            )
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
    requested_model = req.model
    effective_model = _force_configured_model(req)
    t0 = time.time()
    if requested_model and requested_model != effective_model:
        _audit_event(
            "model.override_ignored",
            request,
            requested_model=requested_model,
            effective_model=effective_model,
            endpoint="/apply",
        )
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

            cancelled = False
            _init_job_files(_current_job_id() or "", batch_files)
            for file_index, path in enumerate(batch_files):
                existing_file = _get_job_file_record(file_index)
                if isinstance(existing_file, dict) and existing_file.get("status") == "completed":
                    out_ref = existing_file.get("output") if isinstance(existing_file.get("output"), dict) else {}
                    pdf_ref = existing_file.get("pdf_output") if isinstance(existing_file.get("pdf_output"), dict) else {}
                    out_path_existing = out_ref.get("path")
                    pdf_path_existing = pdf_ref.get("path")
                    if isinstance(out_path_existing, str) and os.path.exists(out_path_existing):
                        resumed_result = {
                            "output_path": out_path_existing,
                            "resumed": True,
                        }
                        if isinstance(pdf_path_existing, str) and os.path.exists(pdf_path_existing):
                            resumed_result["pdf_output_path"] = pdf_path_existing
                        results.append({"input_path": path, "status": "completed", "result": resumed_result})
                        zip_items.append(
                            {
                                "input_path": path,
                                "output_path": out_path_existing,
                                "pdf_path": pdf_path_existing if isinstance(pdf_path_existing, str) else None,
                            }
                        )
                        report_rows.append(
                            {
                                "author": "",
                                "title": "",
                                "subtitle": "",
                                "pages": _count_pdf_pages(pdf_path_existing if isinstance(pdf_path_existing, str) else None),
                                "filename": os.path.basename(path),
                                "status": "completed",
                            }
                        )
                        _audit_event(
                            "job.file.resumed",
                            None,
                            job_id=_current_job_id(),
                            index=file_index,
                            total=len(batch_files),
                            input=_file_ref(path),
                            output=_file_ref(out_path_existing),
                        )
                        continue
                if _job_cancel_requested():
                    cancelled = True
                    _mark_job_remaining_cancelled(file_index, len(batch_files))
                    _audit_event(
                        "job.cancelled",
                        None,
                        job_id=_current_job_id(),
                        batch_id=req.batch_id,
                        processed=file_index,
                        total=len(batch_files),
                    )
                    break
                _job_file_started(file_index, path, len(batch_files))
                r: Dict[str, Any] = {}
                pdf_path = None
                try:
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

                    results.append({"input_path": path, "status": "completed", "result": r})

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
                    # Body-only batches should not spend AI tokens just to fill XLSX cover metadata.
                    if req.apply_cover and not detection:
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
                            "status": "completed",
                        }
                    )
                    _job_file_completed(file_index, path, r, len(batch_files))
                except Exception as file_error:
                    r = {
                        "error": _bounded_str(file_error, 1000),
                        "error_type": type(file_error).__name__,
                    }
                    results.append({"input_path": path, "status": "failed", "result": r})
                    report_rows.append(
                        {
                            "author": "",
                            "title": "",
                            "subtitle": "",
                            "pages": None,
                            "filename": os.path.basename(path),
                            "status": "failed",
                            "error": _bounded_str(file_error, 1000),
                        }
                    )
                    _job_file_failed(file_index, path, file_error, len(batch_files))
                    continue

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
            if cancelled:
                resp["cancelled"] = True
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
def cover_apply(req: ApplyRequest, request: Request) -> Dict[str, Any]:
    try:
        requested_model = req.model
        effective_model = _force_configured_model(req)
        if requested_model and requested_model != effective_model:
            _audit_event(
                "model.override_ignored",
                request,
                requested_model=requested_model,
                effective_model=effective_model,
                endpoint="/cover/apply",
            )
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
def debug_vision(req: DebugVisionRequest, request: Request) -> Dict[str, Any]:
    try:
        requested_model = req.model
        effective_model = _force_configured_model(req)
        if requested_model and requested_model != effective_model:
            _audit_event(
                "model.override_ignored",
                request,
                requested_model=requested_model,
                effective_model=effective_model,
                endpoint="/debug/vision",
            )
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
