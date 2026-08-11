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

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install --upgrade $Root

if ($BuildExecutable) {
    & $VenvPython -m pip install --upgrade pyinstaller
    Push-Location $Root
    try {
        & $VenvPython -m PyInstaller --noconfirm --clean --onefile --windowed --name GatesOfCodeX run_gates_of_codex.py
        & $VenvPython -m PyInstaller --noconfirm --clean --onefile --name GatesOfCodeXLive run_gates_of_codex_live.py
    }
    finally {
        Pop-Location
    }
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

# P6 provenance stamp: exact source commit for the installed tree.
$SourceCommit = ""
try {
    $SourceCommit = (& git -C $Root rev-parse HEAD 2>$null | Select-Object -Last 1)
}
catch {
    $SourceCommit = ""
}
if (-not [string]::IsNullOrWhiteSpace($SourceCommit) -and $SourceCommit -match '^[0-9a-fA-F]{40}$') {
    $StampPath = Join-Path $Root "SOURCE_COMMIT"
    Set-Content -LiteralPath $StampPath -Value $SourceCommit.Trim().ToLowerInvariant() -Encoding ascii
    Write-Host "Stamped package provenance: $SourceCommit"
    if ($BuildExecutable) {
        $DistStamp = Join-Path $Root "dist\SOURCE_COMMIT"
        if (Test-Path -LiteralPath (Join-Path $Root "dist") -PathType Container) {
            Set-Content -LiteralPath $DistStamp -Value $SourceCommit.Trim().ToLowerInvariant() -Encoding ascii
        }
    }
}

Write-Host "Installed. Run:"
Write-Host "  $Venv\Scripts\gates-of-codex.exe doctor"
Write-Host "  $Venv\Scripts\gates-of-codex.exe play --new --stack-config config\mod-stack.windows.json"
Write-Host "  $Venv\Scripts\gates-of-codex-live.exe validate --help"
if (-not $NoWorkshopDeploy) {
    Write-Host "Workshop test deployment: $WorkshopTestTarget"
}
