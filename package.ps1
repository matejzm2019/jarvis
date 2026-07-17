[CmdletBinding()]
param([switch]$InstallTools)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Virtual environment not found. Run .\install.ps1 first." }

if ($InstallTools) {
    & $Python -m pip install -e ".[packaging]"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }
}
& $Python -c "import PyInstaller; print(PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller is missing. Run: .\package.ps1 -InstallTools'
}

$Arguments = @(
    "--noconfirm", "--clean", "--onedir", "--console", "--name", "Jarvis",
    "--paths", $Root,
    "--add-data", "config.example.yaml;.",
    "--add-data", "assets;assets",
    "--collect-all", "faster_whisper",
    "--hidden-import", "winrt.windows.media.control",
    "--hidden-import", "winrt.windows.media",
    "--hidden-import", "winrt.windows.foundation",
    "--hidden-import", "pycaw.pycaw",
    "main.py"
)

& $Python -m PyInstaller @Arguments
if ($LASTEXITCODE -ne 0) { throw "Jarvis package build failed." }
$Dist = Join-Path $Root "dist\Jarvis"
if (Test-Path "config.yaml") { Copy-Item "config.yaml" (Join-Path $Dist "config.yaml") -Force }
Write-Host "Built $Dist\Jarvis.exe"
Write-Host "Review packaged config.yaml paths before moving the folder to another computer."
