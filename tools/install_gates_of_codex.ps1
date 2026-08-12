param(
    [string]$Python = "",
    [switch]$BuildExecutable,
    [switch]$NoPythonInstall,
    [string]$WorkshopTestTarget = $env:GATES_CODEX_DEPLOY_ROOT,
    [switch]$NoWorkshopDeploy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$StampScript = Join-Path $PSScriptRoot "stamp_package_provenance.ps1"

function Test-SupportedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    try {
        $version = (& $Executable @Arguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null | Select-Object -Last 1)
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
            return $null
        }

        $parts = $version.Trim().Split(".")
        if ($parts.Count -lt 2) {
            return $null
        }
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
            return $null
        }

        return [pscustomobject]@{
            Executable = $Executable
            Arguments = $Arguments
            Version = $version.Trim()
        }
    }
    catch {
        return $null
    }
}

function Get-PythonCandidates {
    $candidates = [System.Collections.Generic.List[object]]::new()

    if (-not [string]::IsNullOrWhiteSpace($Python)) {
        if (Test-Path -LiteralPath $Python -PathType Leaf) {
            $candidates.Add(@{ Executable = (Resolve-Path -LiteralPath $Python).Path; Arguments = @() })
        }
        elseif ($Python -match '^\s*py(?:\.exe)?\s+(.+?)\s*$') {
            $candidates.Add(@{ Executable = "py"; Arguments = @($Matches[1] -split '\s+') })
        }
        else {
            $candidates.Add(@{ Executable = $Python; Arguments = @() })
        }
    }

    foreach ($version in @("3.13", "3.12", "3.11")) {
        $candidates.Add(@{ Executable = "py"; Arguments = @("-$version") })
    }
    foreach ($command in @("python3.13", "python3.12", "python3.11", "python", "python3")) {
        $candidates.Add(@{ Executable = $command; Arguments = @() })
    }

    $knownPaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe")
    )
    foreach ($path in $knownPaths) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $candidates.Add(@{ Executable = $path; Arguments = @() })
        }
    }

    return $candidates
}

function Find-SupportedPython {
    foreach ($candidate in Get-PythonCandidates) {
        $runtime = Test-SupportedPython -Executable $candidate.Executable -Arguments $candidate.Arguments
        if ($null -ne $runtime) {
            return $runtime
        }
    }
    return $null
}

function Install-PythonWithWinget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw @"
Python 3.11 or newer is required, and Windows Package Manager (winget) was not found.
Install Python 3.11+ from python.org, reopen PowerShell, and run this installer again.
"@
    }

    Write-Host "No supported Python runtime was found. Installing Python 3.11 with winget..."
    & $winget.Source install `
        --id Python.Python.3.11 `
        --exact `
        --source winget `
        --accept-package-agreements `
        --accept-source-agreements `
        --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install Python 3.11 (exit code $LASTEXITCODE). Install Python 3.11+ manually and rerun the installer."
    }
}

$runtime = $null
if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    $runtime = Test-SupportedPython -Executable $VenvPython
    if ($null -ne $runtime) {
        Write-Host "Reusing existing Gates of CodeX environment at $Venv"
    }
    else {
        Write-Host "Removing incomplete or unsupported environment at $Venv"
        Remove-Item -LiteralPath $Venv -Recurse -Force
    }
}

if ($null -eq $runtime) {
    $runtime = Find-SupportedPython
    if ($null -eq $runtime) {
        if ($NoPythonInstall) {
            throw "Python 3.11 or newer was not found. Install it, or rerun without -NoPythonInstall to allow winget bootstrap."
        }
        Install-PythonWithWinget
        $runtime = Find-SupportedPython
    }
    if ($null -eq $runtime) {
        throw "Python installation completed, but no Python 3.11+ runtime could be resolved. Reopen PowerShell and rerun this installer."
    }

    Write-Host "Using Python $($runtime.Version): $($runtime.Executable) $($runtime.Arguments -join ' ')"
    Write-Host "Creating Gates of CodeX environment at $Venv"
    & $runtime.Executable @($runtime.Arguments + @("-m", "venv", $Venv))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "Virtual-environment creation failed. Expected Python at $VenvPython"
    }
}

$StampPath = $null
try {
    $Stamp = & $StampScript -Root $Root
    $StampPath = (Resolve-Path -LiteralPath $Stamp.StampPath).Path
    $SourceCommit = $Stamp.Commit
    $SourceCommitPath = (Resolve-Path -LiteralPath $StampPath).Path
    Write-Host "Stamped package provenance: $SourceCommit"

    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install --upgrade $Root

    $SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gates-of-codex-provenance-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $SmokeRoot | Out-Null
    $PreviousHome = $env:GATES_OF_CODEX_HOME
    try {
        $env:GATES_OF_CODEX_HOME = $SmokeRoot
        $SmokeCampaign = Join-Path $SmokeRoot "campaign.json"
        $SmokeOutput = & (Join-Path $Venv "Scripts\gates-of-codex.exe") play --new --scenario legacy_goe_europe --campaign $SmokeCampaign --no-launch --json
        if ($LASTEXITCODE -ne 0) {
            throw "Installed CLI provenance smoke failed."
        }
        $SmokeResult = ($SmokeOutput | Out-String) | ConvertFrom-Json
        $Snapshot = Get-Content -Raw -LiteralPath $SmokeResult.snapshot_path | ConvertFrom-Json
        if ($Snapshot.application.source_commit -ne $SourceCommit) {
            throw "Installed CLI snapshot provenance mismatch: expected $SourceCommit, got $($Snapshot.application.source_commit)."
        }
    }
    finally {
        if ($null -eq $PreviousHome) {
            Remove-Item Env:GATES_OF_CODEX_HOME -ErrorAction SilentlyContinue
        }
        else {
            $env:GATES_OF_CODEX_HOME = $PreviousHome
        }
        Remove-Item -LiteralPath $SmokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($BuildExecutable) {
        & $VenvPython -m pip install --upgrade pyinstaller
        $ArchiveViewer = Join-Path $Venv "Scripts\pyi-archive_viewer.exe"
        Push-Location $Root
        try {
            & $VenvPython -m PyInstaller --noconfirm --clean --onefile --windowed --name GatesOfCodeX --add-data "src\gates_of_codex\SOURCE_COMMIT;gates_of_codex" run_gates_of_codex.py
            & $VenvPython -m PyInstaller --noconfirm --clean --onefile --name GatesOfCodeXLive --add-data "src\gates_of_codex\SOURCE_COMMIT;gates_of_codex" run_gates_of_codex_live.py
        }
        finally {
            Pop-Location
        }
        foreach ($Executable in @("dist\GatesOfCodeX.exe", "dist\GatesOfCodeXLive.exe")) {
            $ExecutablePath = Join-Path $Root $Executable
            $Archive = (& $ArchiveViewer -l $ExecutablePath | Out-String)
            if ($LASTEXITCODE -ne 0 -or $Archive -notmatch 'SOURCE_COMMIT') {
                throw "Frozen executable is missing embedded provenance: $Executable"
            }
            $Verified = $false
            foreach ($Entry in @("gates_of_codex\SOURCE_COMMIT", "gates_of_codex/SOURCE_COMMIT")) {
                $Extracted = (@("X $Entry", "", "Q") | & $ArchiveViewer $ExecutablePath | Out-String)
                if ($LASTEXITCODE -eq 0 -and $Extracted -match [regex]::Escape($SourceCommit)) {
                    $Verified = $true
                    break
                }
            }
            if (-not $Verified) {
                throw "Frozen executable provenance does not match $SourceCommit`: $Executable"
            }
        }
        $ProbeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gates-of-codex-frozen-probe-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $ProbeRoot | Out-Null
        try {
            $ProbeScript = Join-Path $ProbeRoot "provenance_probe.py"
            $ProbeBody = @'
import sys

from gates_of_codex.packaging import package_identity

expected = sys.argv[1]
actual = package_identity().source_commit
if actual != expected:
    raise SystemExit(f"Frozen runtime provenance mismatch: expected {expected}, got {actual}")
print(actual)
'@
            [System.IO.File]::WriteAllText(
                $ProbeScript,
                $ProbeBody,
                [System.Text.UTF8Encoding]::new($false)
            )
            $ProbeDist = Join-Path $ProbeRoot "dist"
            $ProbeWork = Join-Path $ProbeRoot "build"
            Push-Location $Root
            try {
                & $VenvPython -m PyInstaller --noconfirm --clean --onefile --console --name GatesOfCodeXProvenanceProbe --distpath $ProbeDist --workpath $ProbeWork --specpath $ProbeRoot --add-data "$SourceCommitPath;gates_of_codex" $ProbeScript
                if ($LASTEXITCODE -ne 0) { throw "Unable to build frozen provenance probe." }
            }
            finally {
                Pop-Location
            }
            $PreviousCommitEnvironment = $env:GATES_OF_CODEX_SOURCE_COMMIT
            try {
                Remove-Item Env:GATES_OF_CODEX_SOURCE_COMMIT -ErrorAction SilentlyContinue
                & (Join-Path $ProbeDist "GatesOfCodeXProvenanceProbe.exe") $SourceCommit | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Frozen runtime provenance mismatch." }
            }
            finally {
                if ($null -ne $PreviousCommitEnvironment) {
                    $env:GATES_OF_CODEX_SOURCE_COMMIT = $PreviousCommitEnvironment
                }
            }
        }
        finally {
            Remove-Item -LiteralPath $ProbeRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        & (Join-Path $Root "dist\GatesOfCodeXLive.exe") --help | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Frozen live executable smoke failed." }
    }

    if (-not $NoWorkshopDeploy) {
        if ([string]::IsNullOrWhiteSpace($WorkshopTestTarget)) {
            throw "A dedicated Workshop test target is required. Pass -WorkshopTestTarget, set GATES_CODEX_DEPLOY_ROOT, or use -NoWorkshopDeploy."
        }
        $DeployScript = Join-Path $PSScriptRoot "deploy_workshop_test.ps1"
        if (-not (Test-Path -LiteralPath $DeployScript -PathType Leaf)) {
            throw "Workshop deployment script not found: $DeployScript"
        }
        Write-Host "Synchronizing Gates of CodeX test item to $WorkshopTestTarget"
        & $DeployScript -SourceRoot $Root -TargetRoot $WorkshopTestTarget
    }

    Write-Host "Installed. Run:"
    Write-Host "  $Venv\Scripts\gates-of-codex.exe doctor"
    Write-Host "  $Venv\Scripts\gates-of-codex.exe play --new --stack-config config\mod-stack.windows.json"
    Write-Host "  $Venv\Scripts\gates-of-codex-live.exe validate --help"
    if (-not $NoWorkshopDeploy) {
        Write-Host "Workshop test deployment: $WorkshopTestTarget"
    }
}
finally {
    if ($null -ne $StampPath -and (Test-Path -LiteralPath $StampPath -PathType Leaf)) {
        Remove-Item -LiteralPath $StampPath -Force
    }
}
