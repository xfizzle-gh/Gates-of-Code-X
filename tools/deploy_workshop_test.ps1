param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TargetRoot = "E:\Steam\steamapps\workshop\content\400750\3700832981",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ManifestName = ".goc-deployment-manifest.json"

function Resolve-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [switch]$Create
    )

    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    if ($Create -and -not (Test-Path -LiteralPath $expanded)) {
        New-Item -ItemType Directory -Path $expanded -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $expanded -PathType Container)) {
        throw "Directory not found: $expanded"
    }
    return (Resolve-Path -LiteralPath $expanded).Path
}

function Test-SafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $false
    }
    foreach ($segment in ($Path -split '[\\/]')) {
        if ($segment -eq ".." -or $segment -eq "") {
            return $false
        }
    }
    return $true
}

$Source = Resolve-Directory -Path $SourceRoot
$Target = Resolve-Directory -Path $TargetRoot -Create

$sourceFull = [System.IO.Path]::GetFullPath($Source).TrimEnd('\', '/')
$targetFull = [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
if ($sourceFull.Equals($targetFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Source and target directories must be different."
}
if ($targetFull.StartsWith($sourceFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Target directory cannot be inside the source repository."
}

$git = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $git) {
    throw "Git is required to enumerate tracked deployment files."
}

$tracked = @(& $git.Source -C $Source ls-files --cached --others --exclude-standard 2>$null)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to enumerate repository files with git ls-files."
}

# Only tracked files are deployed. Untracked runtime state such as .venv, live,
# backups, dist, build, and local logs is never copied.
$tracked = @(& $git.Source -C $Source ls-files 2>$null | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
if ($LASTEXITCODE -ne 0 -or $tracked.Count -eq 0) {
    throw "The source repository contains no tracked files."
}

$tracked = @($tracked | Sort-Object -Unique)
foreach ($relative in $tracked) {
    if (-not (Test-SafeRelativePath -Path $relative)) {
        throw "Unsafe tracked path returned by git: $relative"
    }
}

$manifestPath = Join-Path $Target $ManifestName
$previousFiles = @()
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    try {
        $previous = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($null -ne $previous.files) {
            $previousFiles = @($previous.files)
        }
    }
    catch {
        throw "Deployment manifest is unreadable: $manifestPath"
    }
}

$trackedSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($relative in $tracked) {
    [void]$trackedSet.Add(($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar))
}

$removed = 0
foreach ($relative in $previousFiles) {
    if (-not (Test-SafeRelativePath -Path $relative)) {
        throw "Unsafe path in deployment manifest: $relative"
    }
    $normalized = $relative -replace '/', [System.IO.Path]::DirectorySeparatorChar
    if ($trackedSet.Contains($normalized)) {
        continue
    }
    $destination = Join-Path $Target $normalized
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        Write-Host "Removing stale deployed file: $normalized"
        if (-not $DryRun) {
            Remove-Item -LiteralPath $destination -Force
        }
        $removed++
    }
}

$copied = 0
foreach ($relative in $tracked) {
    $normalized = $relative -replace '/', [System.IO.Path]::DirectorySeparatorChar
    $sourcePath = Join-Path $Source $normalized
    $destination = Join-Path $Target $normalized
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Tracked source file is missing: $sourcePath"
    }
    Write-Host "Deploying: $relative"
    if (-not $DryRun) {
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $sourcePath -Destination $destination -Force
    }
    $copied++
}

$commit = (& $git.Source -C $Source rev-parse HEAD 2>$null | Select-Object -First 1)
if ($LASTEXITCODE -ne 0) {
    $commit = "unknown"
}

$manifest = [ordered]@{
    schema_version = 1
    source_root = $Source
    source_commit = $commit
    target_root = $Target
    deployed_at_utc = [DateTime]::UtcNow.ToString("o")
    files = @($tracked)
}

if (-not $DryRun) {
    $temporaryManifest = "$manifestPath.tmp"
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporaryManifest -Encoding UTF8
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force

    $requiredModInfo = Join-Path $Target "mod.info"
    $requiredResource = Join-Path $Target "resource"
    if (-not (Test-Path -LiteralPath $requiredModInfo -PathType Leaf)) {
        throw "Deployment validation failed: missing $requiredModInfo"
    }
    if (-not (Test-Path -LiteralPath $requiredResource -PathType Container)) {
        throw "Deployment validation failed: missing $requiredResource"
    }
}

$result = [ordered]@{
    ok = $true
    dry_run = [bool]$DryRun
    source = $Source
    target = $Target
    commit = $commit
    copied_files = $copied
    removed_stale_files = $removed
    manifest = $manifestPath
}
$result | ConvertTo-Json -Depth 3
