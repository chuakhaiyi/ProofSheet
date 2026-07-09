@echo off
REM Builds Proofsheet.exe for Windows — FULLY SELF-CONTAINED version.
REM Bundles a portable JRE and Poppler binaries so end users don't need to
REM install anything. Produces a larger dist folder (~200-300 MB) but it
REM just works out of the box.
REM
REM Run this on a Windows machine (PyInstaller cannot cross-compile).
REM Requires: curl and tar (both ship with modern Windows 10/11), and
REM PowerShell's Expand-Archive as a fallback for the JRE zip.

setlocal

echo === Installing Python build dependencies ===
pip install -r requirements.txt
pip install pyinstaller waitress

if not exist bin mkdir bin

REM ---- 1. Portable JRE (Eclipse Temurin) ----
if not exist bin\jre (
    echo.
    echo === Downloading a portable JRE (Eclipse Temurin 21) ===
    REM Update this URL to the latest Temurin JRE "jdk" or "jre" Windows x64 zip from:
    REM https://adoptium.net/temurin/releases/?package=jre
    curl -L -o jre.zip "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse"
    powershell -Command "Expand-Archive -Path jre.zip -DestinationPath bin_jre_tmp -Force"
    powershell -Command "$inner = Get-ChildItem bin_jre_tmp -Directory | Select-Object -First 1; if (-not $inner) { throw 'JRE zip had no top-level folder' }; Move-Item $inner.FullName bin\jre"
    rmdir /s /q bin_jre_tmp
    del jre.zip
    if not exist "bin\jre\bin\java.exe" (
        echo   WARNING: java.exe not found after extraction — JRE zip layout may have changed.
    ) else (
        bin\jre\bin\java.exe -version
    )
) else (
    echo Found existing bin\jre, skipping download.
)

REM ---- 2. Poppler for Windows (pdftoppm / pdfinfo) ----
if not exist bin\poppler (
    echo.
    echo === Downloading Poppler for Windows ===
    powershell -Command "$r = Invoke-RestMethod -Uri 'https://api.github.com/repos/oschwartz10612/poppler-windows/releases/latest'; $a = $r.assets | Where-Object { $_.name -like 'Release-*.zip' } | Select-Object -First 1; if (-not $a) { throw 'No poppler release asset found' }; Write-Host \"Downloading $($a.name)\"; Invoke-WebRequest -Uri $a.browser_download_url -OutFile poppler.zip"
    powershell -Command "Expand-Archive -Path poppler.zip -DestinationPath bin_poppler_tmp -Force"
    powershell -Command "$inner = Get-ChildItem bin_poppler_tmp -Directory | Select-Object -First 1; if (-not $inner) { throw 'poppler zip had no top-level folder' }; Move-Item $inner.FullName bin\poppler"
    rmdir /s /q bin_poppler_tmp
    del poppler.zip
    if not exist "bin\poppler\bin\pdftoppm.exe" if not exist "bin\poppler\Library\bin\pdftoppm.exe" (
        echo   WARNING: pdftoppm.exe not found after extraction — poppler zip layout may have changed.
    )
) else (
    echo Found existing bin\poppler, skipping download.
)

echo.
echo === Building Proofsheet.exe (self-contained, windowed) ===
pyinstaller --noconfirm --clean --onedir --name Proofsheet ^
  --add-data "templates;templates" ^
  --add-data "bin;bin" ^
  --collect-data opendataloader_pdf ^
  --hidden-import waitress ^
  --windowed ^
  launcher.py

echo.
echo === Done ===
echo Your fully self-contained app is in dist\Proofsheet\Proofsheet.exe
echo Ship the whole dist\Proofsheet folder — it includes the bundled JRE
echo and Poppler, so end users need nothing pre-installed.
endlocal
