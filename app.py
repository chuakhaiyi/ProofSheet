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
import json
import re
import uuid
import shutil
import subprocess
import traceback
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


def job_dirs(job_id: str):
    in_dir = UPLOAD_DIR / job_id
    out_dir = OUTPUT_DIR / job_id
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    return in_dir, out_dir


def get_page_sizes(pdf_path: Path):
    """Return a dict {page_number(1-indexed): {"w": pts, "h": pts}} using pdfinfo."""
    sizes = {}
    try:
        out = subprocess.run(
            ["pdfinfo", "-l", "0", str(pdf_path)],
            capture_output=True, text=True, timeout=30,
        ).stdout
        m = re.search(r"Page size:\s+([\d.]+)\s+x\s+([\d.]+)", out)
        pages_m = re.search(r"Pages:\s+(\d+)", out)
        n_pages = int(pages_m.group(1)) if pages_m else 1
        if m:
            w, h = float(m.group(1)), float(m.group(2))
            for p in range(1, n_pages + 1):
                sizes[p] = {"w": w, "h": h}
    except Exception:
        pass
    return sizes


def render_page_thumbnails(pdf_path: Path, out_dir: Path, max_pages: int = 15):
    """Render each page to a PNG using pdftoppm. Returns list of filenames (relative to out_dir)."""
    thumbs_dir = out_dir / "thumbs"
    thumbs_dir.mkdir(exist_ok=True)
    prefix = thumbs_dir / "page"
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(RENDER_DPI), "-l", str(max_pages),
             str(pdf_path), str(prefix)],
            capture_output=True, text=True, timeout=120, check=True,
        )
    except Exception:
        return []
    files = sorted(thumbs_dir.glob("page-*.png"))
    return [f"thumbs/{f.name}" for f in files]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/convert", methods=["POST"])
def convert():
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
        thumbs = render_page_thumbnails(in_path, out_dir)
        result["page_sizes"] = page_sizes
        result["thumbnails"] = thumbs

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
