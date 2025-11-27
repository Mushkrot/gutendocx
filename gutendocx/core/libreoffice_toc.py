from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, Optional


def run_libreoffice_convert(

    input_path: str,
    soffice: str = "soffice",
    out_dir: Optional[str] = None,
    timeout: int = 120,
    use_docker: bool = False,
) -> Dict[str, Any]:
    """Convert a DOCX via LibreOffice in headless mode (DOCX -> DOCX).

    When use_docker is False, LibreOffice is invoked directly on the host
    using the "--convert-to docx" CLI. When use_docker is True, the
    linuxserver/libreoffice Docker image is used and a pre-installed Basic
    macro (Standard.Module1.UpdateTocAndExport) is called to update TOC and
    export a PDF alongside the DOCX.
    """

    abs_input = os.path.abspath(input_path)
    if not os.path.isfile(abs_input):
        raise FileNotFoundError(f"Input DOCX not found for LibreOffice: {abs_input}")

    if out_dir is None:
        out_dir = os.path.dirname(abs_input) or os.getcwd()
    abs_out_dir = os.path.abspath(out_dir)
    os.makedirs(abs_out_dir, exist_ok=True)

    base_name = os.path.basename(abs_input)
    base_root, _ = os.path.splitext(base_name)

    project_root = os.path.abspath(os.getcwd())

    if use_docker:
        # Persist LibreOffice user profile (including macros) under
        # <project_root>/.config-libreoffice and mount it as /config.
        config_dir = os.path.join(project_root, ".config-libreoffice")
        try:
            os.makedirs(config_dir, exist_ok=True)
        except Exception:
            # Best-effort; if it fails, Docker will simply get an empty /config.
            pass

        # Copy the input DOCX into /config/input.docx so that the macro,
        # which is hard-coded to use that path, can open/update/export it.
        config_input = os.path.join(config_dir, "input.docx")
        config_pdf = os.path.join(config_dir, "input.pdf")
        try:
            shutil.copy2(abs_input, config_input)
            if os.path.exists(config_pdf):
                os.remove(config_pdf)
        except Exception as e:
            return {
                "ok": False,
                "error": f"Failed to prepare DOCX for LibreOffice in {config_dir}: {e}",
                "command": None,
            }

        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{project_root}:/data",
            "-v",
            f"{config_dir}:/config",
            "-w",
            "/data",
            "lscr.io/linuxserver/libreoffice:latest",
            soffice,
            "--headless",
            "--invisible",
            "macro:///Standard.Module1.UpdateTocAndExport",
        ]
    else:
        # Host-mode fallback: keep the old --convert-to docx behaviour.
        cmd = [
            soffice,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            abs_out_dir,
            abs_input,
        ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        binary = "docker" if use_docker else soffice
        return {
            "ok": False,
            "error": f"{binary} binary not found: {e}",
            "command": cmd,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": f"LibreOffice timed out after {timeout}s: {e}",
            "command": cmd,
        }

    stdout = proc.stdout.decode("utf-8", errors="ignore") if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else ""

    if use_docker:
        # In Docker mode the macro writes results to /config/input.docx/.pdf.
        config_dir = os.path.join(project_root, ".config-libreoffice")
        src_docx = os.path.join(config_dir, "input.docx")
        src_pdf = os.path.join(config_dir, "input.pdf")
        target_docx = os.path.join(abs_out_dir, f"{base_root}.docx")
        target_pdf = os.path.join(abs_out_dir, f"{base_root}.pdf")
        try:
            if os.path.isfile(src_docx):
                os.makedirs(abs_out_dir, exist_ok=True)
                shutil.copy2(src_docx, target_docx)
            if os.path.isfile(src_pdf):
                os.makedirs(abs_out_dir, exist_ok=True)
                shutil.copy2(src_pdf, target_pdf)
        except Exception as e:
            extra = f"[run_libreoffice_convert] Failed to copy results from {config_dir}: {e}"
            stderr = (stderr + "\n" + extra).strip()

    docx_path = os.path.join(abs_out_dir, f"{base_root}.docx")
    pdf_path = os.path.join(abs_out_dir, f"{base_root}.pdf")

    docx_exists = os.path.isfile(docx_path)
    pdf_exists = os.path.isfile(pdf_path)
    if not pdf_exists:
        alt_pdf = os.path.join(abs_out_dir, f"{base_root}.PDF")
        if os.path.isfile(alt_pdf):
            pdf_path = alt_pdf
            pdf_exists = True

    return {
        "ok": proc.returncode == 0 and docx_exists,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "output_path": docx_path if docx_exists else None,
        "pdf_output_path": pdf_path if pdf_exists else None,
        "command": cmd,
    }
