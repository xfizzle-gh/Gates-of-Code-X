param(
    [string]$GodotPath = "",
    [string]$SnapshotPath = "",
    [string]$OutPath = "",
    [string]$Label = "",
    [int]$Frames = 240,
    [int]$Warmup = 6,
    [double]$Scale = 1.150,
    [string]$Thresholds = ""
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
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $OutPath = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\acceptance\overmap-target-lod-$stamp.json"
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
    "--out=$OutPath",
    "--frames=$Frames",
    "--warmup=$Warmup",
    "--scale=$Scale"
)
if ($Label) {
    $godotArgs += "--label=$Label"
}
if ($Thresholds) {
    $godotArgs += "--thresholds=$Thresholds"
}
Write-Host "Read-only same-harness target LOD benchmark. Owner campaign files are not written."
Write-Host "Root=$root Label=$Label Frames=$Frames Scale=$Scale Out=$OutPath"
$global:LASTEXITCODE = 0
& $godot @godotArgs
$code = $global:LASTEXITCODE
if ($null -eq $code) { $code = 0 }
if ($code -ne 0) { throw "Target LOD benchmark failed with exit $code" }
$deadline = (Get-Date).AddSeconds(45)
while (-not (Test-Path -LiteralPath $OutPath) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
if (-not (Test-Path -LiteralPath $OutPath)) {
    throw "Godot exited $code but did not write $OutPath"
}
Write-Host "Wrote $OutPath"
