import os
import tempfile
import shutil
import subprocess
from typing import Any, Dict, Optional


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
    png_path = os.path.join(out_dir, "cover_page1.png")
    images[0].save(png_path, format="PNG")
    return png_path


def detect_cover_roles_vision(input_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    cover_cfg = (config.get("cover", {}) or {})
    vision_cfg = (cover_cfg.get("vision", {}) or {})
    model = vision_cfg.get("model", "gpt-5-mini")
    render_dpi = int(vision_cfg.get("render_dpi", 220))
    out_dir = vision_cfg.get("out_dir", "output/vision")
    keep_rendered = bool(vision_cfg.get("keep_rendered", True))

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

    warnings.append("vision_not_implemented")

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
    }
