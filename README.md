# Proofsheet PDF Studio

Proofsheet PDF Studio is a local desktop app for turning PDFs into structured
Markdown, JSON, and visual structure maps.

It is built on top of
[`opendataloader-pdf`](https://github.com/opendataloader-project/opendataloader-pdf),
the Apache-2.0 licensed PDF layout parser from the OpenDataLoader project.

Everything runs locally. Your PDFs stay on your machine.

## What It Does

- Converts PDFs into clean Markdown.
- Exports structured JSON with headings, paragraphs, lists, tables, captions,
  images, text blocks, and bounding boxes.
- Shows a structure map with rendered page thumbnails and detected layout boxes.
- Can use an existing PDF structure tree when available.
- Can generate a tagged PDF for accessibility workflows.
- Runs as a standalone Windows desktop application, not as a browser tab.

## Standalone Windows App

The recommended build is the full standalone app:

```bat
build_windows_full.bat
```

This creates:

```text
dist\Proofsheet\Proofsheet.exe
```

Ship the entire `dist\Proofsheet` folder together. The `.exe` needs the
`_internal` folder beside it.

The full build includes:

- the Proofsheet desktop window
- bundled Java 21
- bundled Poppler tools for PDF page rendering
- the app icon in `assets\app_icon.ico` and `assets\app_icon.png`

End users do not need to install Java, Poppler, or Python when using the full
standalone build.

## Desktop Icon

The app icon lives in:

```text
assets\app_icon.ico
assets\app_icon.png
```

The `.ico` file is embedded into `Proofsheet.exe`.
The `.png` file is used for the top-left icon in the app window.

If you replace the icon later, keep the same filenames and rebuild the app.

## Build Options

### Full Build

Use this for the version you share with other people:

```bat
build_windows_full.bat
```

This calls `build_windows_full.ps1`, downloads the portable Java and Poppler
runtimes if needed, and bundles them into the app.

### Lite Build

Use this only if Java 11+ and Poppler are already installed on the target PC:

```bat
build_windows_lite.bat
```

The lite build is smaller, but it depends on the user's system PATH having:

- `java`
- `pdftoppm`
- `pdfinfo`

## GitHub Actions Build

The workflow at:

```text
.github\workflows\build-windows-exe.yml
```

builds the full standalone Windows app on GitHub.

To use it:

1. Push the project to GitHub.
2. Open the repo's Actions tab.
3. Run the `Build Windows exe` workflow, or push to `main`.
4. Download the `Proofsheet-windows` artifact when it finishes.

That artifact contains the ready-to-run `dist\Proofsheet` folder.

## Local Development

For development, you can run the Flask app directly:

```bash
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5050
```

When running this way, your machine must have Java 11+ and Poppler available on
PATH unless you are launching through the packaged desktop app.

## Project Layout

```text
pdfapp/
  app.py                         Flask backend and PDF conversion logic
  launcher.py                    Desktop app launcher used by PyInstaller
  templates/index.html           Main UI
  assets/app_icon.ico            Windows executable icon
  assets/app_icon.png            App window icon
  build_windows_full.bat         Friendly full-build launcher
  build_windows_full.ps1         Full standalone build script
  build_windows_lite.bat         Smaller build for machines with dependencies
  requirements.txt               Python dependencies
  uploads/                       Runtime uploads, gitignored except .gitkeep
  outputs/                       Runtime outputs, gitignored except .gitkeep
```

## What Not To Commit

These are generated locally and should stay out of GitHub:

```text
bin/
build/
dist/
__pycache__/
Proofsheet.spec
proofsheet.log
uploads/*
outputs/*
```

They are already covered by `.gitignore`.

Do commit:

```text
assets/
app.py
launcher.py
templates/
requirements.txt
build_windows_full.bat
build_windows_full.ps1
build_windows_lite.bat
.github/workflows/build-windows-exe.yml
README.md
```

## Troubleshooting

### App Opens But Conversion Fails

Check:

```text
dist\Proofsheet\proofsheet.log
```

The packaged app writes startup and dependency checks there.

### Java Error

If you see `UnsupportedClassVersionError`, the app is using an old Java runtime.
Use the full standalone build so Proofsheet uses its bundled Java 21.

### Structure Map Has No Page Images

The structure map needs Poppler's `pdftoppm` and `pdfinfo`.

The full standalone app bundles Poppler. If thumbnails still fail, check
`proofsheet.log` for the Poppler version and any `pdftoppm` error message.

### Windows Icon Does Not Update Immediately

Windows Explorer sometimes caches `.exe` icons. If the old icon still appears:

- rename the rebuilt folder or `.exe`
- refresh Explorer
- pin/unpin the app again if it was pinned to the taskbar

## License Notes

Proofsheet uses `opendataloader-pdf`, which is Apache-2.0 licensed.
Check that project's license and dependency notices before distributing a
public release.
