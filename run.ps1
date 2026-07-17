[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Voice,
    [switch]$Tray,
    [switch]$Background
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\install.ps1 first."
}
& (Join-Path $Root ".venv\Scripts\Activate.ps1")
if (-not (Test-Path "config.yaml")) {
    throw "config.yaml not found. Copy config.example.yaml to config.yaml or run .\install.ps1."
}
$ModeCount = @($Check, $Voice, $Tray, $Background).Where({ $_.IsPresent }).Count
if ($ModeCount -gt 1) {
    throw "Choose only one mode: -Check, -Voice, -Tray, or -Background."
}

try {
    if ($Background) {
        $PythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"
        if (-not (Test-Path $PythonW)) {
            throw "pythonw.exe is missing from the Python 3.13 virtual environment."
        }
        $Process = Start-Process -FilePath $PythonW `
            -ArgumentList @("main.py", "--config", "config.yaml", "--tray") `
            -WorkingDirectory $Root -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 2
        if ($Process.HasExited) {
            throw "Jarvis background startup exited with code $($Process.ExitCode). Check .\logs\error.log."
        }
        Write-Host "Jarvis started in the background (PID $($Process.Id))."
        exit 0
    } elseif ($Check) {
        & $Python main.py --config config.yaml --check
    } elseif ($Voice) {
        & $Python main.py --config config.yaml --voice
    } elseif ($Tray) {
        & $Python main.py --config config.yaml --tray
    } else {
        & $Python main.py --config config.yaml --text
    }
    exit $LASTEXITCODE
} catch {
    Write-Error "Jarvis startup failed: $($_.Exception.Message). Logs are preserved in .\logs."
    exit 1
}
