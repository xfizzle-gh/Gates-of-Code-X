param(
    [string]$GodotPath = "",
    [string]$OutPath = "",
    [int]$Width = 1920,
    [int]$Height = 1080,
    [int]$Frames = 36
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-Godot {
    param([string]$Explicit)
    if ($Explicit -and (Test-Path -LiteralPath $Explicit)) {
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    foreach ($candidate in @(
        $env:GATES_OF_CODEX_GODOT,
        "C:\Users\paulf\tools\godot\Godot_v4.7-stable_win64.exe",
        "C:\Users\paulf\tools\godot\Godot.exe",
        "D:\Program Files (x86)\Godot Engine\Godot_v4.7-stable_win64.exe"
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    $fromPath = Get-Command godot -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }
    throw "Godot 4.7 not found. Pass -GodotPath."
}

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$godot = Resolve-Godot -Explicit $GodotPath
if (-not $OutPath) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $OutPath = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\acceptance\overmap-interaction-$stamp.json"
}
$parent = Split-Path -Parent $OutPath
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

Write-Host "Godot: $godot"
Write-Host "Out:   $OutPath"
$godotProject = Join-Path $root "godot"
& $godot --path $godotProject --audio-driver Dummy `
    -s res://scripts/tools/map_overmap_interaction_profiler.gd -- `
    --snapshot=res://fixtures/snapshots/earth3_operational.json `
    --fixture=res://fixtures/presentation/e3_operational.json `
    --manifest=res://assets/maps/earth3_europe_mediterranean/map_manifest.json `
    --width=$Width --height=$Height --frames=$Frames `
    --out=$OutPath
if ($LASTEXITCODE -ne 0) {
    throw "Overmap interaction profiler failed with exit $LASTEXITCODE"
}
Write-Host "Wrote $OutPath"
Get-Content -LiteralPath $OutPath
