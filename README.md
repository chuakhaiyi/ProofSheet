# Proofsheet — a PDF structure studio

A small local web app built on top of
[`opendataloader-pdf`](https://github.com/opendataloader-project/opendataloader-pdf),
the Apache-2.0 licensed PDF layout parser from the OpenDataLoader project.

Drop in a PDF and you get:

- **Markdown** — clean text, good for feeding an LLM or a RAG pipeline
- **JSON** — every detected element (heading, paragraph, table, list, image…)
  with its bounding box, font, and semantic type
- **A structure map** — the page rendered as an image with the JSON elements
  drawn on top as color-coded boxes, so you can see exactly what the parser found
- **Tagged, accessible PDF** — optional PDF/UA-style auto-tagging for accessibility

Everything runs locally: the PDF never leaves your machine.

## How it works

`opendataloader-pdf` is a Java-based parser exposed as a Python library
(it ships the JAR inside the pip package and calls it under the hood — hence
the Java requirement below). This app is a thin Flask server that:

1. Accepts an uploaded PDF
2. Calls `opendataloader_pdf.convert(...)` to produce Markdown + JSON
   (and optionally a tagged PDF)
3. Renders each page to a PNG with Poppler's `pdftoppm`, so the JSON's
   bounding boxes (in PDF points) can be drawn as an overlay in the browser
4. Serves the results back to a single-page frontend

## Requirements

- Python 3.9+
- **Java 11+** on your PATH (the parser is JVM-based) — check with `java -version`
- **Poppler utils** (`pdftoppm`, `pdfinfo`) for page thumbnails:
  - macOS: `brew install poppler`
  - Ubuntu/Debian: `sudo apt install poppler-utils`
  - Windows: install a poppler binary build and add it to PATH

## Setup

```bash
cd pdfapp
python3 -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
python3 app.py
```

Then open **http://127.0.0.1:5050** in your browser.

## Modes

- **Fast (local, deterministic)** — the default layout-analysis pipeline, no network calls
- **Use existing tags** — trusts the PDF's own structure tree (`use_struct_tree`) when the file already has one, instead of re-deriving layout from scratch
- **Auto-tag for accessibility** — also emits a tagged PDF (`tagged-pdf` format) suitable for accessibility remediation workflows
- **Sanitize (redact PII)** — passes `sanitize=True` through to the library

`opendataloader-pdf` also supports a **hybrid mode** that calls an external
OCR/vision service for scanned documents (`hybrid=...`, `hybrid_url=...`).
That's not wired into this UI, but `app.py`'s `convert()` call is the only
place you'd need to add it — see the library's own README for the parameters.

## Project layout

```
pdfapp/
  app.py                 Flask backend (upload, convert, thumbnail, download)
  templates/index.html   Single-page frontend (drop zone, structure map, output tabs)
  uploads/                per-job uploaded PDFs (gitignored)
  outputs/                per-job Markdown/JSON/tagged-PDF/thumbnails (gitignored)
```

## Extending it

- Swap the Flask dev server for `gunicorn`/`waitress` if you want to actually
  deploy this rather than run it locally.
- The `/api/convert` route is the seam for adding more of the library's
  options (page ranges, image extraction, OCR hybrid mode, per-language
  reading order, etc.) — they all map directly onto `opendataloader_pdf.convert()` kwargs.
- Job folders under `uploads/` and `outputs/` aren't cleaned up automatically;
  add a cron/cleanup job or a TTL if you run this somewhere long-lived.

## Packaging as a Windows desktop app (.exe)

`launcher.py` + PyInstaller turn this into a real double-clickable desktop
app. The app still runs its PDF engine locally with `waitress`, but the UI is
shown inside a bundled Qt WebEngine window, not Microsoft Edge or a browser tab.
That makes it feel like normal Windows software: double-click `Proofsheet.exe`,
use the app window, close the app window when you are done. **PyInstaller can't
cross-compile** -- you build the `.exe` by running these scripts *on* Windows
(or via the included GitHub Actions workflow, which builds it for you in the
cloud).
Two build tiers, depending on what you want to ship:

**1. Lite (`build_windows_lite.bat`)** — small exe, but the end user's PC
needs Java 11+ and Poppler already installed and on PATH. Good for your own
machine or a team that already has these.

**2. Fully self-contained (`build_windows_full.bat`)** — downloads a portable
Eclipse Temurin JRE and a Poppler-for-Windows build into `bin/jre` and
`bin/poppler`, and bundles them into the exe's folder. `launcher.py` puts
those folders first on PATH before anything else runs, so end users need
nothing pre-installed. This is ~200–300 MB but "just works."

To build either, **on a Windows machine**, from the `pdfapp` folder:

```bat
build_windows_lite.bat
REM or
build_windows_full.bat
```

The result is `dist\Proofsheet\Proofsheet.exe` — ship the whole
`dist\Proofsheet` folder (the exe needs its `_internal` folder next to it,
and `bin` too if you built the self-contained version).

### Don't have a Windows machine? Use GitHub Actions

`.github/workflows/build-windows-exe.yml` builds the fully self-contained
version on a real Windows runner in GitHub's cloud:

1. Push this project to a GitHub repo.
2. Go to the repo's **Actions** tab → **Build Windows exe** → **Run workflow**
   (or just push to `main`; it also runs automatically).
3. When it finishes, download the **Proofsheet-windows** artifact — that's
   your `dist\Proofsheet` folder, ready to run on any Windows 10/11 PC.

The workflow verifies the bundled JRE and Poppler actually extracted
correctly (checking for `java.exe`/`pdftoppm.exe` and failing loudly if not,
instead of silently shipping a broken bundle), then smoke-tests the built
exe headlessly before uploading.

### Troubleshooting a packaged exe

Because the windowed build has no console, **everything is logged to
`proofsheet.log`**, written next to `Proofsheet.exe` itself. If the app
won't start, or a conversion fails oddly, check that file first — dependency
checks (Java/Poppler found, and their versions) are logged on every startup.

A specific error worth calling out: if `proofsheet.log` (or a conversion
error in the UI) mentions **`UnsupportedClassVersionError`** or "this
version of the Java Runtime only recognizes class file versions up to
NN.0", that means an **old Java install elsewhere on the PC is being found
before Proofsheet's own bundled Java 21** — usually a leftover Java 8 from
some other software. `launcher.py` puts the bundled JRE first on PATH, but
if the bundle itself failed to package correctly, it silently falls through
to whatever's already on the system. Check `proofsheet.log` for the "java
check" line to see which Java is actually being used, and rebuild if the
bundled one is missing.
