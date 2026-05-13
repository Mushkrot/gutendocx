import os
import tempfile
import shutil
import subprocess
import base64
import json
import time
import re
import unicodedata
from typing import Any, Dict, Optional, List
from docx import Document
from .cover import _collect_cover_paragraphs, _has_page_or_section_break, _is_empty_para, _is_decorative_line


def _extract_openai_usage(resp: Any) -> Optional[Dict[str, int]]:
    usage = None
    try:
        usage = getattr(resp, "usage", None)
    except Exception:
        usage = None

    def _get(obj: Any, key: str) -> Optional[int]:
        if obj is None:
            return None
        try:
            if isinstance(obj, dict):
                v = obj.get(key)
            else:
                v = getattr(obj, key, None)
        except Exception:
            v = None
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return int(v)
        return None

    prompt_tokens = _get(usage, "prompt_tokens")
    completion_tokens = _get(usage, "completion_tokens")
    input_tokens = _get(usage, "input_tokens")
    output_tokens = _get(usage, "output_tokens")

    if prompt_tokens is None and completion_tokens is None and input_tokens is None and output_tokens is None:
        try:
            data = resp.model_dump() if hasattr(resp, "model_dump") else {}
        except Exception:
            data = {}
        u2 = data.get("usage") if isinstance(data, dict) else None
        prompt_tokens = prompt_tokens if prompt_tokens is not None else _get(u2, "prompt_tokens")
        completion_tokens = completion_tokens if completion_tokens is not None else _get(u2, "completion_tokens")
        input_tokens = input_tokens if input_tokens is not None else _get(u2, "input_tokens")
        output_tokens = output_tokens if output_tokens is not None else _get(u2, "output_tokens")

    in_tok = prompt_tokens if prompt_tokens is not None else input_tokens
    out_tok = completion_tokens if completion_tokens is not None else output_tokens
    if in_tok is None and out_tok is None:
        return None
    return {
        "input_tokens": int(in_tok or 0),
        "output_tokens": int(out_tok or 0),
        "total_tokens": int((in_tok or 0) + (out_tok or 0)),
    }


def _which_soffice() -> Optional[str]:
    candidates = [
        shutil.which("soffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _render_docx_to_pdf(docx_path: str, out_dir: str) -> str:
    soffice = _which_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice 'soffice' not found. Please install via Homebrew: brew install --cask libreoffice")
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


def _render_pdf_page1_to_png(pdf_path: str, out_dir: str, dpi: int) -> str:
    try:
        from pdf2image import convert_from_path  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("pdf2image is required. Please install 'pdf2image' and 'poppler'.") from e

    os.makedirs(out_dir, exist_ok=True)
    images = convert_from_path(pdf_path, dpi=dpi, first_page=1, last_page=1)
    if not images:
        raise RuntimeError("No pages rendered from PDF")
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    png_path = os.path.join(out_dir, f"{base}_page1.png")
    images[0].save(png_path, format="PNG")
    return png_path


def detect_cover_roles_vision(input_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    cover_cfg = (config.get("cover", {}) or {})
    vision_cfg = (cover_cfg.get("vision", {}) or {})
    model = vision_cfg.get("model", "gpt-5-mini")
    render_dpi = int(vision_cfg.get("render_dpi", 220))
    out_dir = vision_cfg.get("out_dir", "output/vision")
    keep_rendered = bool(vision_cfg.get("keep_rendered", True))
    fallback_enabled = bool(vision_cfg.get("fallback_enabled", False))
    t0 = time.time()
    details: Dict[str, Any] = {"used_path": "responses" if str(model).lower().startswith("gpt-5") else "chat"}

    os.makedirs(out_dir, exist_ok=True)

    rendered_png: Optional[str] = None
    warnings = []

    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = _render_docx_to_pdf(input_path, tmp)
            rendered_png = _render_pdf_page1_to_png(pdf_path, out_dir, render_dpi)
    except Exception as e:
        warnings.extend(["vision_render_failed", str(e)])
        return {
            "cover_paragraph_indices": [],
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
            "vision": {
                "model": model,
                "rendered_png": rendered_png,
            },
            "vision_items": [],
            "vision_details": {**details, "elapsed_ms": int((time.time() - t0) * 1000)},
        }

    env_path = vision_cfg.get("env_path")
    if env_path:
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv(os.path.expanduser(env_path))
        except Exception:
            pass

    api_key_present = bool(os.getenv("OPENAI_API_KEY"))
    if not api_key_present:
        warnings.append("missing_api_key")

    def _prepare_api_image(p: str, max_px: int = 1600, quality: int = 85) -> str:
        from PIL import Image  # type: ignore
        im = Image.open(p)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        scale = 1.0
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
        except Exception:
            pass
        return "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")

    def _call_openai_items(png_path: str, mdl: str) -> (List[Dict[str, Any]], str, Optional[Dict[str, int]]):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError("openai_client_missing") from e
        client = OpenAI()
        data_url = _prepare_api_image(png_path)
        prompt = (
            "Detect book cover roles strictly as JSON. "
            "Return: {\"items\":[{\"role\":\"title|subtitle|author\",\"bbox\":[x,y,w,h],\"confidence\":0.0,\"text\":\"...\"}...]} "
            "Coordinates bbox are normalized in [0,1]. Provide text when readable. "
            "If the title spans multiple lines, return it as ONE item with role=title and text containing all title lines (use \\n between lines). "
            "Only return role=subtitle if it is clearly separate from the title block (different visual block). "
            "Do not invent Subtitle if absent."
        )
        last_err = None
        txt = ""
        used_model = mdl
        candidates = [mdl]
        if fallback_enabled and str(mdl).lower().startswith("gpt-5"):
            for alt in ("gpt-5-vision", "gpt-5.1-mini", "gpt-5.0-mini", "gpt-4o-mini"):
                if alt not in candidates:
                    candidates.append(alt)
        details["attempted_models"] = list(candidates)
        last_usage: Optional[Dict[str, int]] = None
        for model_try in candidates:
            resp = None
            use_responses = str(model_try).lower().startswith("gpt-5")
            last_err = None
            for attempt in range(3):
                try:
                    if use_responses:
                        try:
                            resp = client.responses.create(
                                model=model_try,
                                input=[
                                    {
                                        "role": "user",
                                        "content": [
                                            {"type": "input_text", "text": prompt},
                                            {"type": "input_image", "image_url": data_url},
                                        ],
                                    }
                                ],
                                temperature=0,
                                response_format={"type": "json_object"},
                            )
                        except TypeError:
                            resp = client.responses.create(
                                model=model_try,
                                input=[
                                    {
                                        "role": "user",
                                        "content": [
                                            {"type": "input_text", "text": prompt},
                                            {"type": "input_image", "image_url": data_url},
                                        ],
                                    }
                                ],
                                temperature=0,
                            )
                    else:
                        resp = client.chat.completions.create(
                            model=model_try,
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {"type": "image_url", "image_url": {"url": data_url}},
                                    ],
                                }
                            ],
                            temperature=0,
                            timeout=60,
                        )
                    last_err = None
                    last_usage = _extract_openai_usage(resp)
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(2 ** attempt)
            if last_err is not None and use_responses:
                try:
                    resp = client.chat.completions.create(
                        model=model_try,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": data_url}},
                                ],
                            }
                        ],
                        temperature=0,
                        timeout=60,
                    )
                    last_err = None
                    last_usage = _extract_openai_usage(resp)
                except Exception as e:
                    last_err = e
            if last_err is not None:
                continue
            used_model = model_try
            txt = ""
            if use_responses:
                # Try convenience property first
                try:
                    txt = getattr(resp, "output_text", None) or ""
                except Exception:
                    txt = ""
                # Fallback: traverse the output structure for text
                if not txt:
                    try:
                        out = getattr(resp, "output", None)
                        if out:
                            parts = []
                            for item in out:
                                try:
                                    contents = getattr(item, "content", None) or []
                                    for c in contents:
                                        t = getattr(getattr(c, "text", None), "value", None)
                                        if not t:
                                            t = getattr(c, "text", None)
                                        if isinstance(t, str) and t.strip():
                                            parts.append(t)
                                except Exception:
                                    continue
                            if parts:
                                txt = "\n".join(parts)
                    except Exception:
                        pass
                # Last resort: model_dump dict walk
                if not txt:
                    try:
                        data = resp.model_dump()
                        # common path: data['output'][0]['content'][0]['text']
                        outs = data.get("output") or []
                        parts = []
                        for it in outs:
                            for c in (it.get("content") or []):
                                t = None
                                txt_obj = c.get("text") if isinstance(c, dict) else None
                                if isinstance(txt_obj, dict):
                                    t = txt_obj.get("value") or txt_obj.get("text")
                                elif isinstance(txt_obj, str):
                                    t = txt_obj
                                if isinstance(t, str) and t.strip():
                                    parts.append(t)
                        if parts:
                            txt = "\n".join(parts)
                    except Exception:
                        pass
            if not txt:
                try:
                    txt = resp.choices[0].message.content or ""
                except Exception:
                    txt = ""
            if txt:
                break
        if not txt:
            raise RuntimeError("openai_call_failed")
        if not txt:
            raise RuntimeError("empty_response")
        s = txt.strip()
        if s.startswith("```"):
            s = s.strip("`\n ")
            if s.startswith("json"):
                s = s[4:].lstrip()
        obj = json.loads(s)
        items = obj.get("items", []) if isinstance(obj, dict) else []
        if not isinstance(items, list):
            raise RuntimeError("bad_items")
        return items, used_model, last_usage

    items: List[Dict[str, Any]] = []
    used_model = model
    usage: Optional[Dict[str, int]] = None
    try:
        items, used_model, usage = _call_openai_items(rendered_png, model)
        details["used_model"] = used_model
        if usage:
            details["usage"] = usage
    except Exception as e:
        warnings.extend(["vision_call_failed", str(e)])
        return {
            "cover_paragraph_indices": [],
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
            "vision": {
                "model": details.get("used_model") or model,
                "rendered_png": rendered_png,
                "keep_rendered": keep_rendered,
            },
            "vision_items": [],
            "vision_details": {**details, "error": str(e), "elapsed_ms": int((time.time() - t0) * 1000)},
        }

    min_conf = float(vision_cfg.get("min_confidence", 0.6))
    norm_items: List[Dict[str, Any]] = []
    for it in items:
        try:
            role = str(it.get("role", "")).strip().lower()
            bbox = it.get("bbox")
            conf = float(it.get("confidence", 0.0))
            if role in ("title", "subtitle", "author") and isinstance(bbox, (list, tuple)) and len(bbox) == 4 and conf >= min_conf:
                y = float(bbox[1])
                txt = str(it.get("text", "") or "")
                t_uc = txt.strip().upper()
                norm_items.append({"role": role, "bbox": [float(b) for b in bbox], "confidence": conf, "y": y, "t_uc": t_uc})
        except Exception:
            continue
    if used_model != model:
        warnings.append("model_fallback_used:" + used_model)
    if not norm_items:
        warnings.append("no_confident_detections")
        return {
            "cover_paragraph_indices": [],
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
            "vision": {
                "model": model,
                "rendered_png": rendered_png,
                "keep_rendered": keep_rendered,
            },
            "vision_items": [],
            "vision_details": {**details, "elapsed_ms": int((time.time() - t0) * 1000)},
        }

    doc = Document(input_path)
    cover_paras, found_break = _collect_cover_paragraphs(doc)
    if not cover_paras or not found_break:
        warnings.append("no_page_break_found_or_empty_cover")
        return {
            "cover_paragraph_indices": [],
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
            "vision": {
                "model": model,
                "rendered_png": rendered_png,
                "keep_rendered": keep_rendered,
            },
            "vision_items": norm_items,
            "vision_details": {**details, "elapsed_ms": int((time.time() - t0) * 1000)},
        }
    cand_idxs = [i for i, p in enumerate(cover_paras) if not _is_empty_para(p) and not _is_decorative_line(p.text)]
    if not cand_idxs:
        warnings.append("no_candidate_paragraphs")
        return {
            "cover_paragraph_indices": list(range(len(cover_paras))),
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
            "vision": {
                "model": model,
                "rendered_png": rendered_png,
                "keep_rendered": keep_rendered,
            },
            "vision_items": norm_items,
            "vision_details": {**details, "elapsed_ms": int((time.time() - t0) * 1000)},
        }

    norm_items.sort(key=lambda d: d["y"])
    role_name = {"title": "Cover Title", "subtitle": "Cover Subtitle", "author": "Cover Author"}
    assignments: Dict[int, str] = {}
    items_assigned: List[tuple[int, Dict[str, Any]]] = []

    def _fold_text(s: str) -> str:
        t = (s or "").replace("’", "'").replace("‘", "'").replace("`", "'").replace("´", "'")
        t = unicodedata.normalize("NFKD", t)
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        t = re.sub(r"\s+", " ", t).strip().upper()
        return t

    cand_text = {i: _fold_text(cover_paras[i].text) for i in cand_idxs}
    items_mapped: Dict[int, List[Dict[str, Any]]] = {i: [] for i in cand_idxs}
    used_text_mapping = False
    for it in norm_items:
        it_txt = _fold_text(str(it.get("t_uc", "") or ""))
        best_idx = None
        best_score = -1.0
        for idx in cand_idxs:
            ptxt = cand_text.get(idx, "")
            if not ptxt:
                continue
            score = 0.0
            if it_txt and it_txt in ptxt:
                score = 100.0 + min(1.0, float(len(it_txt)) / max(1.0, float(len(ptxt))))
            elif it_txt:
                itoks = set(re.findall(r"[A-Z0-9]+", it_txt))
                ptoks = set(re.findall(r"[A-Z0-9]+", ptxt))
                if itoks:
                    score = 10.0 * (float(len(itoks & ptoks)) / float(len(itoks)))
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx is not None and best_score >= 3.0:
            items_mapped[best_idx].append(it)
            used_text_mapping = True

    if used_text_mapping:
        for idx in cand_idxs:
            its = items_mapped.get(idx) or []
            if not its:
                continue
            roles = {str(x.get("role", "") or "").strip().lower() for x in its}
            if "title" in roles:
                assignments[idx] = "Cover Title"
            elif "subtitle" in roles:
                assignments[idx] = "Cover Subtitle"
            elif "author" in roles:
                assignments[idx] = "Cover Author"
        for idx in list(assignments.keys()):
            if assignments.get(idx) == "Cover Subtitle":
                its = items_mapped.get(idx) or []
                roles = {str(x.get("role", "") or "").strip().lower() for x in its}
                if "title" in roles:
                    assignments[idx] = "Cover Title"
        for idx in cand_idxs:
            for it in (items_mapped.get(idx) or []):
                items_assigned.append((idx, it))
    else:
        j = 0
        for it in norm_items:
            while j < len(cand_idxs) and cand_idxs[j] in assignments:
                j += 1
            if j >= len(cand_idxs):
                break
            idx = cand_idxs[j]
            assignments[idx] = role_name[it["role"]]
            items_assigned.append((idx, it))
            j += 1

    if not assignments:
        warnings.append("mapping_empty")
        return {
            "cover_paragraph_indices": list(range(len(cover_paras))),
            "assignments": {},
            "clusters": [],
            "warnings": warnings,
            "skip": True,
            "vision": {
                "model": used_model,
                "rendered_png": rendered_png,
                "keep_rendered": keep_rendered,
            },
            "vision_items": norm_items,
            "vision_details": {**details, "elapsed_ms": int((time.time() - t0) * 1000)},
        }

    have_author = any(v == "Cover Author" for v in assignments.values())

    # If the model labeled everything as 'title', infer the author block from layout:
    # split items by the largest vertical gap and demote the lower group to Cover Author.
    if not have_author and len(items_assigned) >= 2:
        items_sorted = sorted(items_assigned, key=lambda t: float((t[1] or {}).get("y", 0.0)))
        ys = [float((it or {}).get("y", 0.0)) for _, it in items_sorted]
        best_gap = 0.0
        best_k = None
        for k in range(len(ys) - 1):
            gap = ys[k + 1] - ys[k]
            if gap > best_gap:
                best_gap = gap
                best_k = k
        # Require a meaningful visual separation between title block and author block.
        if best_k is not None and best_gap >= 0.10:
            lower = items_sorted[best_k + 1 :]
            changed_any = False
            for idx, it in lower:
                if assignments.get(idx) == "Cover Title":
                    assignments[idx] = "Cover Author"
                    changed_any = True
            if changed_any:
                warnings.append("author_inferred_from_layout")

    have_author = any(v == "Cover Author" for v in assignments.values())
    if not have_author and items_assigned:
        detect_cfg = (cover_cfg.get("detect", {}) or {})
        author_markers = [str(m).upper() for m in detect_cfg.get("author_markers", [])]
        year_rx = re.compile(detect_cfg.get("year_regex", r"\\b(1[5-9]\\d{2}|20\\d{2}|21\\d{2})\\b"))
        best = (None, -1)
        for idx, it in items_assigned:
            if assignments.get(idx) == "Cover Title":
                continue
            t_uc = str(it.get("t_uc", "") or "")
            score = 0
            if t_uc and any(m in t_uc for m in author_markers):
                score += 3
            if t_uc and bool(year_rx.search(t_uc)):
                score += 1
            if t_uc and (bool(re.match(r"^[A-Z][A-Za-z .,'\\-]+$", t_uc)) or bool(re.match(r"^[A-Z .,'\\-]+$", t_uc))) and len(t_uc) <= 60:
                score += 1
            if score > best[1]:
                best = (idx, score)
        if best[0] is not None and best[1] >= 2:
            assignments[best[0]] = "Cover Author"
            warnings.append("author_promoted_by_text")

    detect_cfg = (cover_cfg.get("detect", {}) or {})
    author_markers = [_fold_text(str(m)) for m in (detect_cfg.get("author_markers", []) or [])]
    have_author = any(v == "Cover Author" for v in assignments.values())
    if have_author and author_markers:
        author_idxs = sorted([idx for idx, v in assignments.items() if v == "Cover Author"])
        if author_idxs:
            first_author = author_idxs[0]
            for idx in cand_idxs:
                if idx >= first_author:
                    continue
                if first_author - idx > 2:
                    continue
                if assignments.get(idx) == "Cover Title":
                    continue
                t = _fold_text(cover_paras[idx].text)
                if not t:
                    continue
                if any((m == t) or t.startswith(m + " ") or (m + " ") in t for m in author_markers if m):
                    assignments[idx] = "Cover Author"

    # Attach a standalone year line to the Author block when Author is present.
    # This helps cases like "BY" + author name + year where the model may not label the year.
    year_rx = re.compile(detect_cfg.get("year_regex", r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b"))
    have_author = any(v == "Cover Author" for v in assignments.values())
    if have_author:
        author_idxs = sorted([idx for idx, v in assignments.items() if v == "Cover Author"])
        if author_idxs:
            last_author = author_idxs[-1]
            for idx in range(last_author + 1, min(last_author + 4, len(cover_paras))):
                if idx not in cand_idxs:
                    continue
                if assignments.get(idx):
                    continue
                t = _fold_text(cover_paras[idx].text)
                if not t:
                    continue
                digits = re.sub(r"\D", "", t)
                if len(digits) == 4 and bool(year_rx.search(t)):
                    assignments[idx] = "Cover Author"
                    break

    return {
        "cover_paragraph_indices": list(range(len(cover_paras))),
        "assignments": {int(k): v for k, v in assignments.items()},
        "clusters": [],
        "warnings": warnings,
        "skip": False,
        "ai_usage": ({"model": used_model, **usage} if usage else None),
        "vision": {
            "model": used_model,
            "rendered_png": rendered_png,
            "keep_rendered": keep_rendered,
        },
        "vision_items": norm_items,
        "vision_details": {**details, "elapsed_ms": int((time.time() - t0) * 1000), "min_confidence": float(vision_cfg.get("min_confidence", 0.6))},
    }
