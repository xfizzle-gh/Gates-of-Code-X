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

$required = @(
    "mod.info",
    "resource\set\dynamic_campaign\values.set",
    "resource\set\multiplayer\games\campaign_capture_the_flag.set",
    "resource\set\multiplayer\games\presets\alliances_goc_201.inc",
    "resource\set\multiplayer\units\roster_conquest.set",
    "resource\script\multiplayer\modes\conquest.lua",
    "resource\script\multiplayer\units\goc_usa\conquest.goc_usa.lua",
    "resource\script\multiplayer\units\goc_fra\conquest.goc_fra.lua",
    "resource\script\multiplayer\units\goc_srb\conquest.goc_srb.lua",
    "resource\script\multiplayer\units\goc_rus\conquest.goc_rus.lua",
    "resource\script\multiplayer\units\goc_dprk\conquest.goc_dprk.lua"
)
foreach ($rel in $required) {
    $path = Join-Path $source $rel
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing required #201 file: $path"
    }
}

# Source conquest.lua is authoritative. Validate coalition membership; do not mutate after copy.
$luaSource = Join-Path $source "resource\script\multiplayer\modes\conquest.lua"
$lua = [IO.File]::ReadAllText($luaSource)
$checks = @(
    @{ Name = "westNations goc_usa"; Pattern = 'westNations\s*=\s*\{[^}]*\bgoc_usa\s*=\s*true' },
    @{ Name = "eastNations goc_fra"; Pattern = 'eastNations\s*=\s*\{[^}]*\bgoc_fra\s*=\s*true' },
    @{ Name = "eastNations goc_srb"; Pattern = 'eastNations\s*=\s*\{[^}]*\bgoc_srb\s*=\s*true' },
    @{ Name = "eastNations goc_rus"; Pattern = 'eastNations\s*=\s*\{[^}]*\bgoc_rus\s*=\s*true' },
    @{ Name = "eastNations goc_dprk"; Pattern = 'eastNations\s*=\s*\{[^}]*\bgoc_dprk\s*=\s*true' },
    @{ Name = "nationMap goc_usa"; Pattern = '\bgoc_usa\s*=\s*9\b' },
    @{ Name = "nationMap goc_fra"; Pattern = '\bgoc_fra\s*=\s*10\b' },
    @{ Name = "nationMap goc_srb"; Pattern = '\bgoc_srb\s*=\s*11\b' },
    @{ Name = "nationMap goc_rus"; Pattern = '\bgoc_rus\s*=\s*12\b' },
    @{ Name = "nationMap goc_dprk"; Pattern = '\bgoc_dprk\s*=\s*13\b' }
)
foreach ($check in $checks) {
    if ($lua -notmatch $check.Pattern) {
        throw "Source conquest.lua failed validation: $($check.Name)"
    }
}
if ($lua -match 'westNations\s*=\s*\{[^}]*\bgoc_fra\s*=\s*true') {
    throw "Source conquest.lua incorrectly places goc_fra in westNations"
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

# Re-read deployed copy and confirm it was not mutated and still validates.
$luaDeployed = Join-Path $target "resource\script\multiplayer\modes\conquest.lua"
$deployed = [IO.File]::ReadAllText($luaDeployed)
if ($deployed -ne $lua) {
    throw "Deployed conquest.lua differs from authoritative source (mutation is forbidden)"
}
foreach ($check in $checks) {
    if ($deployed -notmatch $check.Pattern) {
        throw "Deployed conquest.lua failed validation: $($check.Name)"
    }
}

Write-Host "Deployed standalone #201 test mod: $target"
Write-Host "Validated dedicated CTF, alliances, roster, purchase scripts, and conquest.lua."
Write-Host "Source conquest.lua is authoritative; no post-copy mutation performed."
Write-Host "Enable it LAST after West-81, Code-X, Code:X AI Overhaul, and Gates of Code:X."
Write-Host "Disable other Conquest replacement packs while testing."
Write-Host "Remove with: $($MyInvocation.MyCommand.Path) -GameRoot `"$GameRoot`" -Remove"
