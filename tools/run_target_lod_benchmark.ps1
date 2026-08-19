param(
    [string]$GodotPath = "",
    [string]$SnapshotPath = "",
    [string]$OutPath = ""
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
        "C:\Users\paulf\tools\godot\Godot.exe"
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "Godot 4.7 not found. Pass -GodotPath."
}

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $SnapshotPath) {
    $pointer = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\last_campaign.json"
    if (Test-Path -LiteralPath $pointer) {
        $payload = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
        $campaign = [string]$payload.campaign_path
        $sibling = Join-Path (Split-Path -Parent $campaign) "campaign_snapshot.json"
        if (Test-Path -LiteralPath $sibling) {
            $SnapshotPath = $sibling
        }
    }
}
if (-not $SnapshotPath -or -not (Test-Path -LiteralPath $SnapshotPath)) {
    throw "No campaign snapshot found."
}
$SnapshotPath = (Resolve-Path -LiteralPath $SnapshotPath).Path
if (-not $OutPath) {
    $OutPath = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\acceptance\overmap-target-lod-benchmark.json"
}
$parent = Split-Path -Parent $OutPath
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$godot = Resolve-Godot -Explicit $GodotPath
$godotArgs = @(
    "--disable-vsync",
    "--path", (Join-Path $root "godot"),
    "--audio-driver", "Dummy",
    "-s", "res://scripts/tools/map_target_lod_benchmark.gd",
    "--",
    "--snapshot=$SnapshotPath",
    "--out=$OutPath"
)
Write-Host "Read-only target LOD benchmark. Owner campaign files are not written."
$global:LASTEXITCODE = 0
& $godot @godotArgs
$code = $global:LASTEXITCODE
if ($null -eq $code) { $code = 0 }
if ($code -ne 0) { throw "Target LOD benchmark failed with exit $code" }
$deadline = (Get-Date).AddSeconds(15)
while (-not (Test-Path -LiteralPath $OutPath) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
if (-not (Test-Path -LiteralPath $OutPath)) {
    throw "Godot exited $code but did not write $OutPath"
}
Write-Host "Wrote $OutPath"
Get-Content -LiteralPath $OutPath
