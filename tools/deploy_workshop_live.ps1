param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [Parameter(Mandatory = $true)]
    [string]$TargetRoot,

    [Parameter(Mandatory = $true)]
    [string]$BackupRoot,

    [string]$SourceCommit = "",

    [switch]$AcceptWorkshopMutation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# PowerShell 7.6 + StrictMode may try to read this automatic variable before a
# native command has created it in the current scope. Initialize it explicitly
# so the guarded git checks below remain deterministic.
$global:LASTEXITCODE = 0

$ManifestName = ".goc-deployment-manifest.json"
$BackupMetadataName = ".goc-live-workshop-backup.json"
$RuntimeRoots = @("mod.info", "resource", "localizations")

# Native GoH v1.065 acceptance has only proven bounded custom-faction picker
# registration. Do not deploy the committed all-faction registration surfaces
# into the default live Workshop layer: they expose dozens of GOC armies at
# once and can crash the Dynamic Conquest army selector. The explicit
# native_dc_safe_profile stages a selected pair transactionally after this
# Core-safe base deployment.
$ExcludedNativeDcRegistration = @(
    "resource/set/dynamic_campaign/values.set",
    "resource/set/multiplayer/games/campaign_capture_the_flag.set",
    "resource/set/multiplayer/games/presets/alliances_generic.inc"
)

function Resolve-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
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

function Test-CommitSha {
    param([string]$Value)
    return -not [string]::IsNullOrWhiteSpace($Value) -and $Value -match '^[0-9a-fA-F]{40}$'
}

function Test-ExcludedNativeDcRegistration {
    param([Parameter(Mandatory = $true)][string]$Relative)

    $normalized = $Relative -replace '\\', '/'
    if ($ExcludedNativeDcRegistration -contains $normalized) {
        return $true
    }
    if ($normalized -match '^resource/set/multiplayer/armies/goc_[^/]+\.set$') {
        return $true
    }
    return $false
}

function Get-RelativeRuntimeFiles {
    param([Parameter(Mandatory = $true)][string]$Source)

    $git = Get-Command git -ErrorAction Stop
    $tracked = @(& $git.Source -C $Source ls-files -- mod.info resource localizations 2>$null |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique)
    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed for live Workshop runtime roots."
    }
    if ($tracked.Count -eq 0) {
        throw "No tracked GoH runtime files were found under mod.info/resource/localizations."
    }

    $safe = @(
        $tracked | Where-Object {
            -not (Test-ExcludedNativeDcRegistration -Relative $_)
        }
    )
    if ($safe.Count -eq 0) {
        throw "Core-safe Workshop deployment filter removed every tracked runtime file."
    }
    return $safe
}

if (-not $AcceptWorkshopMutation) {
    throw "Live Workshop deployment is destructive by design. Re-run with -AcceptWorkshopMutation after reviewing TargetRoot and BackupRoot."
}

$Source = Resolve-Directory -Path $SourceRoot
$Target = Resolve-Directory -Path $TargetRoot
$Backups = Resolve-Directory -Path $BackupRoot -Create

$sourceFull = [System.IO.Path]::GetFullPath($Source).TrimEnd('\', '/')
$targetFull = [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
$backupFull = [System.IO.Path]::GetFullPath($Backups).TrimEnd('\', '/')

if ($sourceFull.Equals($targetFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "SourceRoot and TargetRoot must differ."
}
if ($targetFull.StartsWith($sourceFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Live Workshop target cannot be inside the source checkout."
}
if ($backupFull.Equals($targetFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    $backupFull.StartsWith($targetFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BackupRoot must be outside the live Workshop target."
}

$requiredModInfo = Join-Path $Source "mod.info"
$requiredResource = Join-Path $Source "resource"
if (-not (Test-Path -LiteralPath $requiredModInfo -PathType Leaf)) {
    throw "Source checkout is not a Gates of CodeX mod: missing $requiredModInfo"
}
if (-not (Test-Path -LiteralPath $requiredResource -PathType Container)) {
    throw "Source checkout is not a Gates of CodeX mod: missing $requiredResource"
}
$modInfoText = Get-Content -LiteralPath $requiredModInfo -Raw
if ($modInfoText -notmatch 'Gates of CodeX|Gates of Code:X') {
    throw "Source mod.info does not identify Gates of CodeX."
}

$git = Get-Command git -ErrorAction Stop
$gitCommit = (& $git.Source -C $Source rev-parse --verify HEAD 2>$null | Select-Object -First 1)
if ($LASTEXITCODE -ne 0 -or -not (Test-CommitSha -Value $gitCommit)) {
    throw "Unable to authenticate SourceRoot with git rev-parse HEAD."
}
$gitCommit = $gitCommit.Trim().ToLowerInvariant()
if (Test-CommitSha -Value $SourceCommit) {
    $expected = $SourceCommit.Trim().ToLowerInvariant()
    if ($gitCommit -ne $expected) {
        throw "Live Workshop source commit mismatch: expected $expected, SourceRoot is $gitCommit."
    }
    $commit = $expected
}
elseif (-not [string]::IsNullOrWhiteSpace($SourceCommit)) {
    throw "SourceCommit must be an exact 40-character SHA."
}
else {
    $commit = $gitCommit
}

$runtimeFiles = @(Get-RelativeRuntimeFiles -Source $Source)
$timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$backupDirectory = Join-Path $Backups ("gates-of-codex-workshop-{0}-{1}" -f $timestamp, $commit.Substring(0, 12))
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null

Write-Host "Backing up current live Workshop item before mutation: $Target"
Write-Host "Backup: $backupDirectory"
Get-ChildItem -LiteralPath $Target -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $backupDirectory -Recurse -Force
}

$backupMetadata = [ordered]@{
    schema = "gates-of-codex.live-workshop-backup"
    schema_version = 1
    source_commit = $commit
    target_root = $Target
    backup_directory = $backupDirectory
    created_at_utc = [DateTime]::UtcNow.ToString("o")
}
$backupMetadata | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backupDirectory $BackupMetadataName) -Encoding UTF8

Write-Host "Replacing live Workshop item with Core-safe tracked GoH runtime content from $commit"
Get-ChildItem -LiteralPath $Target -Force | Remove-Item -Recurse -Force

$hashes = [ordered]@{}
foreach ($relative in $runtimeFiles) {
    if ([System.IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "Unsafe runtime path returned by git: $relative"
    }
    $normalized = $relative -replace '/', [System.IO.Path]::DirectorySeparatorChar
    $sourcePath = Join-Path $Source $normalized
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Tracked runtime source file is missing: $sourcePath"
    }
    $destination = Join-Path $Target $normalized
    $parent = Split-Path -Parent $destination
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $sourcePath -Destination $destination -Force

    $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $targetHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sourceHash -ne $targetHash) {
        throw "Live Workshop byte verification failed for $relative"
    }
    $hashes[$relative] = $sourceHash
}

$manifest = [ordered]@{
    schema = "gates-of-codex.live-workshop-deployment"
    schema_version = 1
    deployment_kind = "core_safe_owner_native_live_workshop"
    source_root = $Source
    source_commit = $commit
    target_root = $Target
    backup_directory = $backupDirectory
    deployed_at_utc = [DateTime]::UtcNow.ToString("o")
    runtime_roots = $RuntimeRoots
    excluded_native_dc_registration = @($ExcludedNativeDcRegistration) + @("resource/set/multiplayer/armies/goc_*.set")
    files = @($runtimeFiles)
    sha256 = $hashes
}
$manifestPath = Join-Path $Target $ManifestName
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

# Fail closed if anything other than the exact Core-safe runtime set plus our
# manifest is present.
$expectedFiles = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($relative in $runtimeFiles) {
    [void]$expectedFiles.Add(($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar))
}
[void]$expectedFiles.Add($ManifestName)
$unexpected = @()
Get-ChildItem -LiteralPath $Target -File -Recurse -Force | ForEach-Object {
    $relative = [System.IO.Path]::GetRelativePath($Target, $_.FullName)
    if (-not $expectedFiles.Contains($relative)) {
        $unexpected += $relative
    }
}
if ($unexpected.Count -gt 0) {
    throw "Unexpected files remain in authoritative live Workshop target: $($unexpected -join ', ')"
}

# Prove the crash-prone all-faction registration did not leak into the base
# deployment. A bounded profile may add selected GOC army files only after this
# script has completed successfully.
$unsafeLeaks = @(
    Get-ChildItem -LiteralPath (Join-Path $Target "resource\set\multiplayer\armies") -Filter "goc_*.set" -File -ErrorAction SilentlyContinue
)
if ($unsafeLeaks.Count -gt 0) {
    throw "Core-safe deployment leaked GOC army registration: $($unsafeLeaks.Name -join ', ')"
}
foreach ($relative in $ExcludedNativeDcRegistration) {
    $target = Join-Path $Target ($relative -replace '/', '\')
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        throw "Core-safe deployment leaked global Dynamic Conquest registration: $relative"
    }
}

$result = [ordered]@{
    ok = $true
    source_commit = $commit
    source_root = $Source
    target_root = $Target
    backup_directory = $backupDirectory
    manifest = $manifestPath
    deployment_kind = "core_safe_owner_native_live_workshop"
    copied_files = $runtimeFiles.Count
}
$result | ConvertTo-Json -Depth 5
