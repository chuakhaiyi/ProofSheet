"""
PDF Structure Studio — a small web app built on top of the
opendataloader-pdf library (https://github.com/opendataloader-project/opendataloader-pdf).

Upload a PDF, choose a mode, and get back:
  - Markdown (clean text for LLMs / RAG)
  - JSON (every element + bounding box + semantic type)
  - Tagged PDF (accessibility auto-tagging)
  - A visual "structure map": the original page render with the
    detected elements (headings, paragraphs, tables, lists, images)
    drawn as color-coded boxes on top, built from the JSON output.

Everything runs locally — no data leaves the machine.
"""
import os
import ctypes
import json
import re
import sys
import threading
import uuid
import shutil
import subprocess
import traceback
import time
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template

import opendataloader_pdf

RENDER_DPI = 120  # resolution used for page thumbnails shown under the structure overlay

# When launched via launcher.py (packaged exe), these env vars point at the
# right folders whether we're a plain script or a frozen PyInstaller build.
# When run directly with `python3 app.py`, both simply default to this file's folder.
_RESOURCE_DIR = Path(os.environ.get("PROOFSHEET_RESOURCE_DIR", Path(__file__).parent))
_DATA_DIR = Path(os.environ.get("PROOFSHEET_DATA_DIR", Path(__file__).parent))

BASE_DIR = _DATA_DIR
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_EXT = {".pdf"}
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

app = Flask(__name__, template_folder=str(_RESOURCE_DIR / "templates"))
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

_DLL_SEARCH_LOCK = threading.Lock()


def tool_path(env_name: str, executable: str) -> str:
    configured = os.environ.get(env_name)
    if configured and Path(configured).exists():
        return configured
    return executable


def tool_run_kwargs(env_name: str):
    configured = os.environ.get(env_name)
    if not configured:
        return {}

    tool_dir = str(Path(configured).parent)
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    safe_path = os.pathsep.join([
        tool_dir,
        str(Path(system_root) / "System32"),
        system_root,
    ])
    env = os.environ.copy()
    env["PATH"] = safe_path
    return {"env": env, "cwd": tool_dir}


@contextmanager
def external_tool_dll_search():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        yield
        return

    kernel32 = ctypes.windll.kernel32
    with _DLL_SEARCH_LOCK:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetDllDirectoryW(len(buffer), buffer)
        previous = buffer.value if length else None
        kernel32.SetDllDirectoryW(None)
        try:
            yield
        finally:
            kernel32.SetDllDirectoryW(previous)


def run_external_tool(args, *, env_name: str, timeout: int):
    kwargs = tool_run_kwargs(env_name)
    with external_tool_dll_search():
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            **kwargs,
        )


def java_ready_error():
    if os.environ.get("PROOFSHEET_JAVA_OK") == "0":
        return (
            "Proofsheet found an old or missing Java runtime. "
            "Use the full standalone build so Proofsheet includes its own Java 11+ "
            "under bin\\jre, and keep the whole Proofsheet folder together."
        )
    return None


def job_dirs(job_id: str):
    in_dir = UPLOAD_DIR / job_id
    out_dir = OUTPUT_DIR / job_id
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    return in_dir, out_dir


def get_page_sizes(pdf_path: Path):
    """Return a dict {page_number(1-indexed): {"w": pts, "h": pts}} using pdfinfo."""
    sizes = {}
    for attempt in range(1, 4):
        try:
            proc = run_external_tool(
                [tool_path("PROOFSHEET_PDFINFO_EXE", "pdfinfo"), "-l", "0", str(pdf_path.resolve())],
                env_name="PROOFSHEET_PDFINFO_EXE",
                timeout=30,
            )
            out = proc.stdout
            if proc.returncode != 0:
                app.logger.warning(
                    "pdfinfo failed on attempt %s with code %s: %s",
                    attempt, proc.returncode, (proc.stderr or proc.stdout or "").strip()
                )
                time.sleep(0.5)
                continue
            m = re.search(r"Page size:\s+([\d.]+)\s+x\s+([\d.]+)", out)
            pages_m = re.search(r"Pages:\s+(\d+)", out)
            n_pages = int(pages_m.group(1)) if pages_m else 1
            if m:
                w, h = float(m.group(1)), float(m.group(2))
                for p in range(1, n_pages + 1):
                    sizes[p] = {"w": w, "h": h}
            break
        except Exception as e:
            app.logger.warning("pdfinfo failed on attempt %s: %s", attempt, e)
            time.sleep(0.5)
    return sizes


def render_page_thumbnails(pdf_path: Path, out_dir: Path, max_pages: int = 15):
    """Render page PNGs with pdftoppm. Returns (filenames, error_text)."""
    thumbs_dir = out_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    for old_thumb in thumbs_dir.glob("page-*.png"):
        try:
            old_thumb.unlink()
        except OSError:
            pass

    rendered = []
    last_error = ""
    try:
        for page_num in range(1, max_pages + 1):
            prefix = thumbs_dir / f"page-{page_num:03d}"
            output = thumbs_dir / f"page-{page_num:03d}.png"
            for attempt in range(1, 5):
                proc = run_external_tool(
                    [
                        tool_path("PROOFSHEET_PDFTOPPM_EXE", "pdftoppm"),
                        "-png",
                        "-r", str(RENDER_DPI),
                        "-f", str(page_num),
                        "-l", str(page_num),
                        "-singlefile",
                        str(pdf_path.resolve()),
                        str(prefix.resolve()),
                    ],
                    env_name="PROOFSHEET_PDFTOPPM_EXE",
                    timeout=60,
                )
                if proc.returncode == 0 and output.exists():
                    last_error = ""
                    break

                last_error = (proc.stderr or proc.stdout or "").strip()
                if not last_error:
                    last_error = f"pdftoppm exited with code {proc.returncode} and did not create {output.name}"
                app.logger.warning(
                    "pdftoppm failed on page %s attempt %s: %s",
                    page_num, attempt, last_error
                )
                time.sleep(0.75)

            if not output.exists():
                if rendered and "Wrong page range" in last_error:
                    last_error = ""
                break
            rendered.append(f"thumbs/{output.name}")
    except Exception as e:
        last_error = str(e)
        app.logger.warning("Thumbnail rendering failed: %s", last_error)

    return rendered, last_error


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/convert", methods=["POST"])
def convert():
    java_error = java_ready_error()
    if java_error:
        return jsonify({"error": java_error}), 500

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected."}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "Only .pdf files are supported."}), 400

    mode = request.form.get("mode", "fast")  # fast | tagged | sanitize
    job_id = uuid.uuid4().hex[:12]
    in_dir, out_dir = job_dirs(job_id)

    safe_name = "input.pdf"
    in_path = in_dir / safe_name
    f.save(in_path)

    try:
        formats = "markdown,json"
        kwargs = dict(
            input_path=[str(in_path)],
            output_dir=str(out_dir),
            format=formats,
            quiet=True,
        )
        if mode == "tagged":
            kwargs["format"] = "markdown,json,tagged-pdf"
        if mode == "sanitize":
            kwargs["sanitize"] = True
        if mode == "structure":
            # use native PDF structure tags when present
            kwargs["use_struct_tree"] = True

        opendataloader_pdf.convert(**kwargs)

        stem = Path(safe_name).stem
        md_path = out_dir / f"{stem}.md"
        json_path = out_dir / f"{stem}.json"
        tagged_path = out_dir / f"{stem}_tagged.pdf"
        if not tagged_path.exists():
            # library may name it differently; search for any pdf output
            candidates = list(out_dir.glob("*.pdf"))
            tagged_path = candidates[0] if candidates else None

        result = {"job_id": job_id}

        page_sizes = get_page_sizes(in_path)
        thumbs, thumb_error = render_page_thumbnails(in_path, out_dir)
        result["page_sizes"] = page_sizes
        result["thumbnails"] = thumbs
        if thumb_error:
            result["thumbnail_error"] = thumb_error
        result["thumbnail_limit"] = 15

        if md_path.exists():
            result["markdown"] = md_path.read_text(encoding="utf-8", errors="replace")
            result["markdown_file"] = md_path.name

        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
            result["structure"] = data
            result["json_file"] = json_path.name

        if tagged_path and tagged_path.exists():
            result["tagged_pdf_file"] = tagged_path.name

        return jsonify(result)

    except subprocess.CalledProcessError as e:
        traceback.print_exc()
        detail = (e.stderr or e.stdout or e.output or "").strip()
        msg = detail if detail else str(e)
        return jsonify({"error": f"opendataloader-pdf failed: {msg}"}), 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Conversion failed: {e}"}), 500


@app.route("/api/download/<job_id>/<filename>")
def download(job_id, filename):
    out_dir = OUTPUT_DIR / job_id
    if not out_dir.exists():
        return jsonify({"error": "Job not found."}), 404
    return send_from_directory(out_dir, filename, as_attachment=True)


@app.route("/api/thumb/<job_id>/<path:filename>")
def thumb(job_id, filename):
    out_dir = OUTPUT_DIR / job_id
    if not out_dir.exists():
        return jsonify({"error": "Job not found."}), 404
    return send_from_directory(out_dir, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
