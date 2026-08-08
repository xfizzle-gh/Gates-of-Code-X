param(
    [string]$ProfileDirectory = "",
    [string]$InstallDirectory = "",
    [string]$TemplateSave = "",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$expected = "14d784de63d58ddbf993d71f95d9f31b8a370cb2"
$branch = "audit/161-wrapper-engine-acceptance"
$workflowPath = ".github/workflows/issue161-wrapper-engine-preflight.yml"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venv = "E:\Steam\steamapps\workshop\content\400750\Gates-of-Code-X-wrapper-test-venv"

Set-Location $root

git fetch origin
git switch -C $branch "origin/$branch"

git merge-base --is-ancestor $expected HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Wrapper test branch does not descend from audited commit $expected"
}

$changed = @(git diff --name-only "$expected...HEAD")
$bad = @($changed | Where-Object { $_ -notlike "audit/issue161/*" -and $_ -ne $workflowPath })
if ($bad.Count -gt 0) {
    throw "Wrapper test branch changes non-audit paths: $($bad -join ', ')"
}

$basePython = (& py -3.11 -c "import platform,sys; assert platform.python_version() == '3.11.9'; print(sys.executable)").Trim()
if (-not $basePython) {
    throw "Python 3.11.9 is required."
}

if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $basePython -m venv $venv
}
$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install -e .

$env:GOH_VANILLA_ROOT = "E:\Steam\steamapps\common\Call to Arms - Gates of Hell"
$env:WEST81_ROOT = "E:\Steam\steamapps\workshop\content\400750\2897299509"
$env:CODEX_ROOT = "E:\Steam\steamapps\workshop\content\400750\3261086933"
$env:CODEX_AI_OVERHAUL_ROOT = "E:\Steam\steamapps\workshop\content\400750\CodeX AI Overhaul Submod"
$env:GATES_CODEX_ROOT = $root

$arguments = @(
    (Join-Path $root "audit\issue161\prepare_wrapper_engine_test.py"),
    "--game", $env:GOH_VANILLA_ROOT,
    "--codex", $env:CODEX_ROOT,
    "--stack-config", (Join-Path $root "config\mod-stack.windows.json"),
    "--work-root", (Join-Path $root "live\issue161"),
    "--backup-root", (Join-Path $root "backups\issue161"),
    "--output", (Join-Path $root "live\issue161\latest-session.json")
)

if ($ProfileDirectory -or $InstallDirectory) {
    if (-not $ProfileDirectory -or -not $InstallDirectory) {
        throw "Pass both -ProfileDirectory and -InstallDirectory."
    }
    $arguments += @("--profile", $ProfileDirectory, "--install-directory", $InstallDirectory)
}
if ($TemplateSave) {
    $arguments += @("--template-save", $TemplateSave)
}

& $python @arguments

if (-not $NoLaunch) {
    & $python -c "from gates_of_codex.launcher import launch_game; launch_game(r'$($env:GOH_VANILLA_ROOT)')"
}

Write-Host ""
Write-Host "The two wrapper test saves are installed."
Write-Host "Load the exact first and second names printed above."
Write-Host "After both tests and screenshots, exit GoH and run:"
Write-Host "  .\audit\issue161\collect-wrapper-evidence.ps1"
