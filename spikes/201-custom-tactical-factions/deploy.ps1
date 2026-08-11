param(
    [Parameter(Mandatory = $true)]
    [string]$GatesRoot,
    [switch]$Restore
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$spikeRoot = $PSScriptRoot
$resourceRoot = Join-Path $spikeRoot "resource"
$gates = (Resolve-Path -LiteralPath $GatesRoot).Path
$backupRoot = Join-Path $spikeRoot ".deploy-backup"
$manifestPath = Join-Path $backupRoot "deployed-files.txt"

function Get-SpikeRelatives {
    Get-ChildItem -LiteralPath $resourceRoot -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($resourceRoot.Length).TrimStart('\', '/')
        # Engine content lives under resource/ in the Gates package root.
        ("resource/" + ($rel -replace '\\', '/'))
    }
}

if ($Restore) {
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "No deploy backup manifest at $manifestPath"
    }
    $rels = Get-Content -LiteralPath $manifestPath
    foreach ($rel in $rels) {
        $target = Join-Path $gates ($rel -replace '/', '\')
        $bak = Join-Path $backupRoot ($rel -replace '/', '\')
        if (Test-Path -LiteralPath $bak) {
            $parent = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $parent)) {
                New-Item -ItemType Directory -Force -Path $parent | Out-Null
            }
            Copy-Item -LiteralPath $bak -Destination $target -Force
        } elseif (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
    }
    Write-Host "Restored Gates root from spike backup"
    exit 0
}

if (-not (Test-Path -LiteralPath $resourceRoot)) {
    throw "Missing spike resource tree: $resourceRoot"
}

# Fresh backup directory each deploy
if (Test-Path -LiteralPath $backupRoot) {
    Remove-Item -LiteralPath $backupRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$rels = @(Get-SpikeRelatives)
$rels | Set-Content -LiteralPath $manifestPath -Encoding UTF8

foreach ($rel in $rels) {
    $srcRel = $rel -replace '^resource/', ''
    $src = Join-Path $resourceRoot ($srcRel -replace '/', '\')
    $dst = Join-Path $gates ($rel -replace '/', '\')
    $bak = Join-Path $backupRoot ($rel -replace '/', '\')
    $bakParent = Split-Path -Parent $bak
    if (-not (Test-Path -LiteralPath $bakParent)) {
        New-Item -ItemType Directory -Force -Path $bakParent | Out-Null
    }
    if (Test-Path -LiteralPath $dst) {
        Copy-Item -LiteralPath $dst -Destination $bak -Force
    }
    $dstParent = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dstParent)) {
        New-Item -ItemType Directory -Force -Path $dstParent | Out-Null
    }
    Copy-Item -LiteralPath $src -Destination $dst -Force
    Write-Host "deployed $rel"
}

Write-Host "Deployed $($rels.Count) spike files into $gates"
Write-Host "Restore with: $($MyInvocation.MyCommand.Path) -GatesRoot `"$gates`" -Restore"
