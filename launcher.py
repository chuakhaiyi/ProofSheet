"""
Entry point used to package Proofsheet as a standalone desktop application.

Responsibilities:
  - Works out where the "app" lives whether we're running as a normal
    Python script OR as a frozen PyInstaller executable (sys._MEIPASS points
    at the _internal folder in onedir builds, not the exe's own folder).
  - If a portable JRE and/or Poppler build have been bundled (under
    bin/jre and bin/poppler, wherever PyInstaller actually put them),
    prepends their bin/ folders to PATH *before* importing opendataloader_pdf,
    so the bundled binaries are found ahead of anything already on the
    user's system PATH (e.g. a stale old Java 8 install).
  - Serves the Flask app with waitress (a real WSGI server) in a background
    thread.
  - Opens a native desktop window (pywebview) pointing at the local server —
    this is what makes it feel like a real app instead of "a website that
    happens to run locally". Falls back to the default browser if pywebview
    can't start for some reason.
  - Because packaged "windowed" builds have no console attached, everything
    is also logged to proofsheet.log next to the executable, and sys.stdout/
    sys.stderr are given somewhere safe to write to (in windowed PyInstaller
    builds they are None by default, which crashes on any bare print()).
  - Set PROOFSHEET_NO_GUI=1 to skip the window entirely and just run the
    server — used by the CI smoke test, where there's no guarantee of a
    display/WebView2 runtime being available.
"""
import os
import sys
import re
import socket
import logging
import threading
import time
import webbrowser


def app_dir() -> str:
    """Folder the exe/script is running from (handles PyInstaller onefile & onedir)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    """Folder bundled *data* files (templates/, bin/, etc.) actually live in.

    For PyInstaller onedir builds this is the _internal folder next to the
    exe, NOT the same folder as the exe itself — that's the mistake this
    launcher originally made.
    """
    if getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    return app_dir()


LOG_PATH = os.path.join(app_dir(), "proofsheet.log")


def setup_logging_and_safe_streams():
    """Make print()/logging safe even with no console (PyInstaller --windowed),
    and always keep a log file next to the exe so failures are diagnosable
    without needing a terminal.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("proofsheet")


def prepend_bundled_tools_to_path(log):
    """Locate a bundled JRE/Poppler and put them first on PATH.

    Checks both resource_dir() (where PyInstaller onedir actually puts
    --add-data files, i.e. _internal) and app_dir() (in case someone drops
    a bin/ folder next to the exe by hand instead).
    """
    roots = {app_dir(), resource_dir()}
    candidates = []
    for base in roots:
        candidates += [
            os.path.join(base, "bin", "jre", "bin"),
            os.path.join(base, "bin", "poppler", "bin"),
            os.path.join(base, "bin", "poppler", "Library", "bin"),
        ]
    found = [p for p in candidates if os.path.isdir(p)]
    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")
        log.info("Bundled tools found and prepended to PATH: %s", found)
    else:
        log.info("No bundled bin/jre or bin/poppler found under %s — using system PATH only.", roots)
    return found


def check_dependency(name: str, version_args, log):
    """Run a version command and return (found: bool, version_text: str)."""
    import subprocess
    try:
        proc = subprocess.run(version_args, capture_output=True, text=True, timeout=10)
        text = (proc.stderr or proc.stdout or "").strip()
        log.info("%s check: %s", name, text.splitlines()[0] if text else "(no output)")
        return True, text
    except Exception as e:
        log.warning("%s check failed: %s", name, e)
        return False, ""


def java_major_version(version_text: str):
    """Parse the major version number out of `java -version` output."""
    m = re.search(r'version "(\d+)(?:\.(\d+))?', version_text)
    if not m:
        return None
    major = int(m.group(1))
    # Old scheme: "1.8.0_xxx" means Java 8, reported as major=1, minor=8
    if major == 1 and m.group(2):
        return int(m.group(2))
    return major


def find_free_port(preferred: int = 5050) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def wait_until_up(url: str, timeout: float = 15.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def show_fatal_error(message: str):
    """Best-effort native error dialog for startup failures, since there's
    no console in windowed builds. Falls back to just logging if this
    itself fails for any reason.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Proofsheet — startup error", message)
        root.destroy()
    except Exception:
        pass


def main():
    log = setup_logging_and_safe_streams()
    log.info("=" * 60)
    log.info("Proofsheet starting (frozen=%s)", getattr(sys, "frozen", False))

    prepend_bundled_tools_to_path(log)

    os.environ["PROOFSHEET_RESOURCE_DIR"] = resource_dir()
    os.environ["PROOFSHEET_DATA_DIR"] = app_dir()
    sys.path.insert(0, resource_dir())

    have_java, java_text = check_dependency("java", ["java", "-version"], log)
    have_poppler, _ = check_dependency("pdftoppm", ["pdftoppm", "-v"], log)

    if have_java:
        major = java_major_version(java_text)
        if major is not None and major < 11:
            msg = (
                f"Found Java {major}, but opendataloader-pdf needs Java 11 or newer.\n\n"
                "This usually means an old Java install elsewhere on this PC is being "
                "found ahead of Proofsheet's own bundled Java. Uninstalling or updating "
                "the old Java, or moving Proofsheet's folder so its bundled bin\\jre is "
                "used, will fix this.\n\n"
                f"Details were written to:\n{LOG_PATH}"
            )
            log.error(msg)
    else:
        log.warning("No usable 'java' found on PATH at all.")

    if not have_poppler:
        log.warning("No usable 'pdftoppm' found — page thumbnails/structure map will not render.")

    try:
        import app as flask_app_module
    except Exception:
        log.exception("Failed to import the Flask app module.")
        show_fatal_error(f"Proofsheet failed to start.\n\nDetails were written to:\n{LOG_PATH}")
        sys.exit(1)

    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    log.info("Serving at %s", url)

    from waitress import serve

    server_thread = threading.Thread(
        target=serve,
        kwargs=dict(app=flask_app_module.app, host="127.0.0.1", port=port),
        daemon=True,
    )
    server_thread.start()

    if not wait_until_up(url):
        log.error("Server did not come up in time.")
        show_fatal_error(f"Proofsheet's server did not start.\n\nDetails were written to:\n{LOG_PATH}")
        sys.exit(1)

    no_gui = os.environ.get("PROOFSHEET_NO_GUI") == "1"
    if no_gui:
        log.info("PROOFSHEET_NO_GUI set — running headless (used for automated smoke tests).")
        server_thread.join()
        return

    try:
        import webview
        window_kwargs = dict(
            title="Proofsheet",
            url=url,
            width=1280,
            height=860,
            min_size=(900, 600),
        )
        webview.create_window(**window_kwargs)
        log.info("Opening native window.")
        webview.start()
    except Exception:
        log.exception("pywebview failed to start a native window — falling back to the default browser.")
        webbrowser.open(url)
        print(f"Proofsheet is running at {url} — this window will keep it alive. Close it to stop Proofsheet.")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
