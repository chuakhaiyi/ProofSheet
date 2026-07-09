@echo off
REM Builds Proofsheet.exe for Windows — LITE version.
REM Assumes Java 11+ and Poppler (pdftoppm/pdfinfo) are already installed
REM and on PATH on THIS machine. The resulting exe will look for them on
REM PATH at runtime too, so it stays small but isn't fully self-contained.
REM
REM Run this on a Windows machine (PyInstaller cannot cross-compile).

setlocal

echo === Installing Python build dependencies ===
pip install -r requirements.txt
pip install pyinstaller waitress

echo.
echo === Checking for Java and Poppler on this machine ===
where java >nul 2>nul
if errorlevel 1 (
    echo   WARNING: 'java' not found on PATH. Install a JRE from https://adoptium.net
) else (
    echo   Found java. Checking version:
    java -version
)
where pdftoppm >nul 2>nul
if errorlevel 1 (
    echo   WARNING: 'pdftoppm' not found on PATH. Install Poppler for Windows:
    echo   https://github.com/oschwartz10612/poppler-windows/releases
) else (
    echo   Found pdftoppm.
)

echo.
echo === Building Proofsheet.exe (windowed desktop app) ===
pyinstaller --noconfirm --clean --onedir --name Proofsheet ^
  --add-data "templates;templates" ^
  --add-data "assets;assets" ^
  --icon "assets\app_icon.ico" ^
  --collect-data opendataloader_pdf ^
  --hidden-import PySide6.QtWebEngineWidgets ^
  --hidden-import PySide6.QtWebEngineCore ^
  --exclude-module PyQt5 ^
  --exclude-module PyQt6 ^
  --exclude-module PySide2 ^
  --hidden-import waitress ^
  --windowed ^
  launcher.py

echo.
echo === Done ===
echo Your app is in dist\Proofsheet\Proofsheet.exe
echo Ship the whole dist\Proofsheet folder together — the exe needs the
echo _internal folder next to it.
endlocal
