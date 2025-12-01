from __future__ import annotations

import os
import shutil
import subprocess
import uuid
import time
from typing import Any, Dict, Optional

from .layout import fix_theme_fonts


# Default Docker image with fonts - can be overridden via config
# Use custom image with pre-installed fonts for consistent rendering
DEFAULT_DOCKER_IMAGE = "gutendocx/libreoffice:latest"


def run_libreoffice_convert(
    input_path: str,
    soffice: str = "soffice",
    out_dir: Optional[str] = None,
    timeout: int = 120,
    use_docker: bool = False,
    docker_image: Optional[str] = None,
    theme_font: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a DOCX via LibreOffice in headless mode (DOCX -> DOCX + PDF).

    When use_docker is False, LibreOffice is invoked directly on the host
    using the "--convert-to docx" CLI.
    
    When use_docker is True, the linuxserver/libreoffice Docker image is used.
    We use a 'pipe-exec-pipe' strategy to avoid volume mount and docker cp issues:
      1. Start a detached container.
      2. Pipe input DOCX and script into container using 'docker exec -i ... tee'.
      3. Exec the script inside the container (via UNO).
      4. Read the result (DOCX + PDF) via 'docker exec ... cat' -> local file.
      5. Remove the container.
    
    Args:
        theme_font: Optional font name to use for theme fonts. If None, theme fonts
                    are left unchanged (preserving user's font choices).
    """

    abs_input = os.path.abspath(input_path)
    if not os.path.isfile(abs_input):
        raise FileNotFoundError(f"Input DOCX not found for LibreOffice: {abs_input}")

    # Only fix theme fonts if explicitly requested
    # This preserves user's font choices from the UI
    if theme_font:
        try:
            theme_fix_result = fix_theme_fonts(abs_input, major_font=theme_font, minor_font=theme_font)
            if theme_fix_result.get("changed"):
                print(f"[LibreOffice] Fixed theme fonts: {theme_fix_result.get('original_major')} -> {theme_font}")
        except Exception as e:
            print(f"[LibreOffice] Warning: Could not fix theme fonts: {e}")

    if out_dir is None:
        out_dir = os.path.dirname(abs_input) or os.getcwd()
    abs_out_dir = os.path.abspath(out_dir)
    os.makedirs(abs_out_dir, exist_ok=True)

    base_name = os.path.basename(abs_input)
    base_root, _ = os.path.splitext(base_name)

    project_root = os.path.abspath(os.getcwd())

    docx_output_path = os.path.join(abs_out_dir, f"{base_root}.docx")
    pdf_output_path = os.path.join(abs_out_dir, f"{base_root}.pdf")

    if use_docker:
        # PyUNO script path on host
        script_path = os.path.join(project_root, "gutendocx", "scripts", "lo_convert.py")
        if not os.path.isfile(script_path):
            return {
                "ok": False,
                "error": f"PyUNO script not found at {script_path}",
                "command": None,
            }

        container_name = f"lo_worker_{uuid.uuid4().hex}"
        image = docker_image or DEFAULT_DOCKER_IMAGE

        # Optional: mount local fonts directory into container, if present
        fonts_dir = os.path.join(project_root, "fonts")

        # 1. Start container
        run_cmd = [
            "docker", "run", "-d", "--rm",
            "--name", container_name,
        ]
        if os.path.isdir(fonts_dir):
            run_cmd.extend([
                "-v", f"{fonts_dir}:/usr/share/fonts/custom:ro",
            ])
        run_cmd.append(image)
        
        try:
            subprocess.run(run_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            return {
                "ok": False,
                "error": f"Failed to start Docker container: {e.stderr.decode()}",
                "command": run_cmd
            }

        container_running = True
        stdout_log = ""
        stderr_log = ""
        
        try:
            # Give it a moment to initialize services
            time.sleep(5)

            # 2. Pipe files to container
            remote_script = "/tmp/lo_convert.py"
            remote_input = "/tmp/input.docx"
            remote_output_pdf = "/tmp/output.pdf"
            
            # Helper to pipe file content
            def pipe_to_container(local_path, remote_path):
                with open(local_path, "rb") as f_in:
                    # docker exec -i CONTAINER tee REMOTE_PATH > /dev/null
                    cmd = ["docker", "exec", "-i", container_name, "tee", remote_path]
                    subprocess.run(cmd, stdin=f_in, stdout=subprocess.DEVNULL, check=True)

            pipe_to_container(script_path, remote_script)
            pipe_to_container(abs_input, remote_input)

            # 3. Exec command
            # Refresh font cache (in case /usr/share/fonts/custom is mounted),
            # then start soffice background (listening on port 2002), wait, run python
            exec_cmd_str = (
                "fc-cache -f -v >/dev/null 2>&1 || true; "
                "soffice --headless --accept='socket,host=localhost,port=2002;urp;' > /dev/null 2>&1 & "
                "sleep 5 && "
                f"python3 {remote_script} {remote_input} {remote_output_pdf}"
            )
            
            exec_cmd = [
                "docker", "exec", container_name,
                "/bin/bash", "-c", exec_cmd_str
            ]
            
            proc = subprocess.run(
                exec_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout
            )
            
            stdout_log = proc.stdout.decode("utf-8", errors="ignore")
            stderr_log = proc.stderr.decode("utf-8", errors="ignore")
            
            if proc.returncode == 0:
                # 4. Read results back
                # Helper to read file content from container
                def read_from_container(remote_path, local_path):
                    with open(local_path, "wb") as f_out:
                        # docker exec CONTAINER cat REMOTE_PATH
                        cmd = ["docker", "exec", container_name, "cat", remote_path]
                        subprocess.run(cmd, stdout=f_out, check=True)

                # Read DOCX
                read_from_container(remote_input, docx_output_path)
                
                # Read PDF
                read_from_container(remote_output_pdf, pdf_output_path)
            else:
                pass

            return_code = proc.returncode

        except subprocess.TimeoutExpired:
            return_code = -1
            stderr_log += f"\nOperation timed out after {timeout}s"
        except Exception as e:
            return_code = 1
            stderr_log += f"\nException during Docker operation: {e}"
        finally:
            # 5. Cleanup
            if container_running:
                subprocess.run(
                    ["docker", "kill", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )

        docx_exists = os.path.isfile(docx_output_path)
        pdf_exists = os.path.isfile(pdf_output_path)

        return {
            "ok": return_code == 0 and docx_exists and pdf_exists,
            "returncode": return_code,
            "stdout": stdout_log,
            "stderr": stderr_log,
            "output_path": docx_output_path if docx_exists else None,
            "pdf_output_path": pdf_output_path if pdf_exists else None,
            "command": exec_cmd if 'exec_cmd' in locals() else run_cmd,
        }

    else:
        # Host-mode fallback
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
            return {
                "ok": False,
                "error": f"{soffice} binary not found: {e}",
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

        docx_exists = os.path.isfile(docx_output_path)
        
        # Check for PDF
        pdf_exists = os.path.isfile(pdf_output_path)
        if not pdf_exists:
            alt_pdf = os.path.join(abs_out_dir, f"{base_root}.PDF")
            if os.path.isfile(alt_pdf):
                pdf_output_path = alt_pdf
                pdf_exists = True

        return {
            "ok": proc.returncode == 0 and docx_exists,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output_path": docx_output_path if docx_exists else None,
            "pdf_output_path": pdf_output_path if pdf_exists else None,
            "command": cmd,
        }
