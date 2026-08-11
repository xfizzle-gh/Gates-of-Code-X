param(
    [Parameter(Mandatory = $true)]
    [string]$GameRoot,
    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$source = $PSScriptRoot
$modsRoot = Join-Path (Resolve-Path -LiteralPath $GameRoot).Path "mods"
$target = Join-Path $modsRoot "goc_201_faction_spike"

if ($Remove) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    Write-Host "Removed standalone #201 test mod: $target"
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $source "mod.info"))) {
    throw "Missing standalone mod.info in $source"
}
if (-not (Test-Path -LiteralPath (Join-Path $source "resource"))) {
    throw "Missing resource tree in $source"
}

if (-not (Test-Path -LiteralPath $modsRoot)) {
    New-Item -ItemType Directory -Force -Path $modsRoot | Out-Null
}
if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $target | Out-Null

Copy-Item -LiteralPath (Join-Path $source "mod.info") -Destination (Join-Path $target "mod.info") -Force
Copy-Item -LiteralPath (Join-Path $source "resource") -Destination $target -Recurse -Force

Write-Host "Deployed standalone #201 test mod: $target"
Write-Host "Enable it LAST after West-81, Code-X, Code:X AI Overhaul, and Gates of Code:X."
Write-Host "Disable other Conquest replacement packs while testing."
Write-Host "Remove with: $($MyInvocation.MyCommand.Path) -GameRoot `"$GameRoot`" -Remove"
