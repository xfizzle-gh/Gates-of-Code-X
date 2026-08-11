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
    "resource\script\multiplayer\units\goc_fra\conquest.goc_fra.lua"
)
foreach ($rel in $required) {
    $path = Join-Path $source $rel
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing required #201 file: $path"
    }
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

# The source conquest.lua is the AI Overhaul donor with two #201 nationMap entries.
# Correct the fallback coalition hint in the disposable deployed copy without
# hand-rewriting the 1,000-line donor file: France is the East test faction.
$luaPath = Join-Path $target "resource\script\multiplayer\modes\conquest.lua"
$lua = [IO.File]::ReadAllText($luaPath)
$patched = $lua -replace 'local eastNations = \{ rusa = true, sov = true, prc = true, pol = true, rus = true, jap = true \}', 'local eastNations = { rusa = true, sov = true, prc = true, pol = true, rus = true, jap = true, goc_fra = true }'
$patched = $patched -replace 'goc_usa = true, goc_fra = true \}', 'goc_usa = true }'
if ($patched -eq $lua) {
    throw "Expected #201 coalition-hint patterns were not found in deployed conquest.lua"
}
[IO.File]::WriteAllText($luaPath, $patched, (New-Object Text.UTF8Encoding($false)))

Write-Host "Deployed standalone #201 test mod: $target"
Write-Host "Validated dedicated CTF, alliances, roster, purchase scripts, and conquest.lua."
Write-Host "Patched deployed fallback coalition hints: goc_usa=West, goc_fra=East."
Write-Host "Enable it LAST after West-81, Code-X, Code:X AI Overhaul, and Gates of Code:X."
Write-Host "Disable other Conquest replacement packs while testing."
Write-Host "Remove with: $($MyInvocation.MyCommand.Path) -GameRoot `"$GameRoot`" -Remove"
