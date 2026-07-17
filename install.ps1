[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($env:OS -ne "Windows_NT") {
    throw "Jarvis requires Windows 11."
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $Launcher) {
        throw "Python launcher not found. Install 64-bit Python 3.13 from python.org, including the py launcher."
    }
    & py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.13 is required. Install it and rerun .\install.ps1."
    }
}

$Version = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0 -or -not $Version.StartsWith("3.13.")) {
    throw "The project virtual environment must use Python 3.13; detected $Version. Remove .venv and rerun .\install.ps1."
}
Write-Host "Python $Version"

$Activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
& $Activate
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt

if (-not (Test-Path "config.yaml")) {
    Copy-Item "config.example.yaml" "config.yaml"
    Write-Host "Created config.yaml"
}

try {
    $VersionResponse = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 5
    Write-Host "Ollama $($VersionResponse.version) is running."
    $Tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 10
    $HasModel = @($Tags.models | Where-Object { $_.name.Split(':')[0] -eq 'gemma64' }).Count -gt 0
    if ($HasModel) {
        Write-Host "gemma64 is available."
    } else {
        Write-Warning "gemma64 is unavailable. Run: ollama list"
    }
} catch {
    Write-Warning "Ollama is not reachable at http://localhost:11434. Start Ollama; no model will be downloaded automatically."
}

try {
    & $Python -c "from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager; from pycaw.pycaw import AudioUtilities; print('Windows media and Core Audio dependencies are ready.')"
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 media dependency import failed." }
} catch {
    Write-Warning "Phase 5 media dependencies are unavailable: $($_.Exception.Message)"
}

Write-Host "PortAudio microphone inputs:"
try {
    & $Python -m audio.recorder
    $MicrophoneExit = $LASTEXITCODE
} catch {
    $MicrophoneExit = 1
}
if ($MicrophoneExit -ne 0) {
    Write-Warning "Microphone enumeration failed. Check Windows microphone privacy permissions."
}

try {
    & $Python -m audio.speech_to_text --check-model --config config.yaml
    $WhisperExit = $LASTEXITCODE
} catch {
    $WhisperExit = 1
}
if ($WhisperExit -ne 0) {
    Write-Warning "The configured faster-whisper model is not cached. Download it explicitly after reviewing the size."
    Write-Host "  .\.venv\Scripts\python.exe -m audio.speech_to_text --download-model medium"
}

$PiperPaths = & $Python -c "from config import load_config; c=load_config(); print(c.text_to_speech.executable_path); print(c.text_to_speech.voice_model_path)"
if ($PiperPaths.Count -ge 2 -and (Test-Path $PiperPaths[0]) -and (Test-Path $PiperPaths[1])) {
    Write-Host "Piper executable and voice model are configured."
} else {
    Write-Warning "Piper is not configured. Text mode works, but Phase 2 voice output needs piper.exe and a voice model."
}

try {
    & $Python -m audio.wake_word --check-model --config config.yaml
    $WakeWordExit = $LASTEXITCODE
} catch {
    $WakeWordExit = 1
}
if ($WakeWordExit -ne 0) {
    Write-Warning "The local Hey Jarvis wake-word assets are missing. Download only these assets explicitly with:"
    Write-Host "  .\.venv\Scripts\python.exe -m audio.wake_word --download-model --config config.yaml"
}

try {
    $MonitorCount = & $Python -c "import mss; from PIL import Image; s=mss.MSS(); print(len(s.monitors)-1); s.close()"
    if ($LASTEXITCODE -ne 0) { throw "Vision dependency check failed." }
    Write-Host "mss and Pillow are ready; detected $MonitorCount physical monitor(s)."
} catch {
    Write-Warning "Phase 4 vision dependencies are unavailable: $($_.Exception.Message)"
}

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "FFmpeg is available (not required by faster-whisper 1.2.x)."
} else {
    Write-Host "FFmpeg not found; faster-whisper uses bundled PyAV decoding and does not require it."
}

& $Python -m pytest
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed. Review the output above."
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Review config.yaml searchable directories and application allowlist."
Write-Host "  2. Verify the model: ollama show gemma64"
Write-Host "  3. Check runtime: .\run.ps1 -Check"
Write-Host "  4. Start text mode: .\run.ps1"
Write-Host "  5. Configure Whisper/Piper, then start voice mode: .\run.ps1 -Voice"
Write-Host "  6. Start tray mode: .\run.ps1 -Tray"
Write-Host "  7. Start without a terminal window: .\run.ps1 -Background"
Write-Host "  8. Optional local package: .\package.ps1 -InstallTools"
