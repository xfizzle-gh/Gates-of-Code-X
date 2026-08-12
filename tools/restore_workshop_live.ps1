param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRoot,

    [Parameter(Mandatory = $true)]
    [string]$BackupDirectory,

    [switch]$AcceptWorkshopMutation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$BackupMetadataName = ".goc-live-workshop-backup.json"

function Resolve-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    if (-not (Test-Path -LiteralPath $expanded -PathType Container)) {
        throw "Directory not found: $expanded"
    }
    return (Resolve-Path -LiteralPath $expanded).Path
}

if (-not $AcceptWorkshopMutation) {
    throw "Restoring the live Workshop item replaces its current contents. Re-run with -AcceptWorkshopMutation."
}

$Target = Resolve-Directory -Path $TargetRoot
$Backup = Resolve-Directory -Path $BackupDirectory
$metadataPath = Join-Path $Backup $BackupMetadataName
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "Backup metadata missing: $metadataPath"
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ($metadata.schema -ne "gates-of-codex.live-workshop-backup" -or [int]$metadata.schema_version -ne 1) {
    throw "Unsupported live Workshop backup metadata: $metadataPath"
}
$recordedTarget = [System.IO.Path]::GetFullPath([string]$metadata.target_root).TrimEnd('\', '/')
$currentTarget = [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
if (-not $recordedTarget.Equals($currentTarget, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup belongs to $recordedTarget, not $currentTarget"
}

Write-Host "Restoring live Workshop item from: $Backup"
Write-Host "Target: $Target"
Get-ChildItem -LiteralPath $Target -Force | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $Backup -Force | Where-Object {
    $_.Name -ne $BackupMetadataName
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
}

$result = [ordered]@{
    ok = $true
    target_root = $Target
    restored_from = $Backup
    backup_source_commit = [string]$metadata.source_commit
}
$result | ConvertTo-Json -Depth 4
