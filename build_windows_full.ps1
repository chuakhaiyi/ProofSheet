$ErrorActionPreference = "Stop"

Write-Host "=== Installing Python build dependencies ==="
python -m pip install -r requirements.txt
python -m pip install pyinstaller waitress

$binDir = Join-Path $PSScriptRoot "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

$jreDir = Join-Path $binDir "jre"
$javaExe = Join-Path $jreDir "bin\java.exe"
if (-not (Test-Path $javaExe)) {
    Write-Host ""
    Write-Host "=== Downloading portable Java runtime (Eclipse Temurin 21) ==="
    $jreZip = Join-Path $PSScriptRoot "jre.zip"
    $jreTmp = Join-Path $PSScriptRoot "bin_jre_tmp"
    if (Test-Path $jreTmp) { Remove-Item -LiteralPath $jreTmp -Recurse -Force }
    if (Test-Path $jreZip) { Remove-Item -LiteralPath $jreZip -Force }

    Invoke-WebRequest `
        -Uri "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse" `
        -OutFile $jreZip
    Expand-Archive -Path $jreZip -DestinationPath $jreTmp -Force
    $inner = Get-ChildItem $jreTmp -Directory | Select-Object -First 1
    if (-not $inner) { throw "JRE zip did not contain a top-level folder." }
    Move-Item -LiteralPath $inner.FullName -Destination $jreDir
    Remove-Item -LiteralPath $jreTmp -Recurse -Force
    Remove-Item -LiteralPath $jreZip -Force
}
if (-not (Test-Path $javaExe)) { throw "java.exe was not found at $javaExe" }
$javaVersion = cmd /c "`"$javaExe`" -version 2>&1"
Write-Host "Bundled Java version:"
Write-Host $javaVersion

$popplerDir = Join-Path $binDir "poppler"
$pdftoppmCandidates = @(
    (Join-Path $popplerDir "bin\pdftoppm.exe"),
    (Join-Path $popplerDir "Library\bin\pdftoppm.exe")
)
$pdftoppmExe = $pdftoppmCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pdftoppmExe) {
    Write-Host ""
    Write-Host "=== Downloading Poppler for Windows ==="
    $popplerZip = Join-Path $PSScriptRoot "poppler.zip"
    $popplerTmp = Join-Path $PSScriptRoot "bin_poppler_tmp"
    if (Test-Path $popplerTmp) { Remove-Item -LiteralPath $popplerTmp -Recurse -Force }
    if (Test-Path $popplerZip) { Remove-Item -LiteralPath $popplerZip -Force }

    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/oschwartz10612/poppler-windows/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -like "Release-*.zip" } | Select-Object -First 1
    if (-not $asset) { throw "Could not find a poppler-windows release asset." }
    Write-Host "Downloading $($asset.name)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $popplerZip
    Expand-Archive -Path $popplerZip -DestinationPath $popplerTmp -Force
    $inner = Get-ChildItem $popplerTmp -Directory | Select-Object -First 1
    if (-not $inner) { throw "Poppler zip did not contain a top-level folder." }
    Move-Item -LiteralPath $inner.FullName -Destination $popplerDir
    Remove-Item -LiteralPath $popplerTmp -Recurse -Force
    Remove-Item -LiteralPath $popplerZip -Force
}
$pdftoppmExe = $pdftoppmCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pdftoppmExe) { throw "pdftoppm.exe was not found in $popplerDir" }
Write-Host "Bundled Poppler found at $pdftoppmExe"

Write-Host ""
Write-Host "=== Building Proofsheet.exe (full standalone app) ==="
pyinstaller --noconfirm --clean --noupx --onedir --name Proofsheet `
  --add-data "templates;templates" `
  --add-data "assets;assets" `
  --add-data "bin;bin" `
  --icon "assets\app_icon.ico" `
  --collect-data opendataloader_pdf `
  --hidden-import PySide6.QtWebEngineWidgets `
  --hidden-import PySide6.QtWebEngineCore `
  --exclude-module PyQt5 `
  --exclude-module PyQt6 `
  --exclude-module PySide2 `
  --hidden-import waitress `
  --windowed `
  launcher.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "=== Done ==="
Write-Host "Your full standalone app is in dist\Proofsheet\Proofsheet.exe"
Write-Host "Keep the whole dist\Proofsheet folder together when moving the app."
