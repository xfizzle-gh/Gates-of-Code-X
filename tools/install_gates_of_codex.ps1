param(
    [string]$Python = "py -3.11",
    [switch]$BuildExecutable
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"

Write-Host "Creating Gates of CodeX environment at $Venv"
Invoke-Expression "$Python -m venv `"$Venv`""
$PythonExe = Join-Path $Venv "Scripts\python.exe"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install $Root

if ($BuildExecutable) {
    & $PythonExe -m pip install pyinstaller
    Push-Location $Root
    try {
        & $PythonExe -m PyInstaller --noconfirm --clean --onefile --windowed --name GatesOfCodeX run_gates_of_codex.py
    }
    finally {
        Pop-Location
    }
}

Write-Host "Installed. Run:"
Write-Host "  $Venv\Scripts\gates-of-codex.exe doctor"
Write-Host "  $Venv\Scripts\gates-of-codex.exe ui"
