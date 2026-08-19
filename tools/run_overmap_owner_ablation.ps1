param(
    [string]$GodotPath = "",
    [string]$CampaignPath = "",
    [string]$SnapshotPath = "",
    [string]$OutPath = "",
    [int]$Width = 1920,
    [int]$Height = 1080
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
if (-not $CampaignPath) {
    $pointer = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\last_campaign.json"
    if (Test-Path -LiteralPath $pointer) {
        $payload = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
        $CampaignPath = [string]$payload.campaign_path
    }
}
if (-not $SnapshotPath -and $CampaignPath) {
    $sibling = Join-Path (Split-Path -Parent $CampaignPath) "campaign_snapshot.json"
    if (Test-Path -LiteralPath $sibling) {
        $SnapshotPath = $sibling
    }
}
if (-not $SnapshotPath -or -not (Test-Path -LiteralPath $SnapshotPath)) {
    throw "No campaign snapshot found. Pass -SnapshotPath or keep last_campaign.json + campaign_snapshot.json."
}
$SnapshotPath = (Resolve-Path -LiteralPath $SnapshotPath).Path
if ($CampaignPath -and (Test-Path -LiteralPath $CampaignPath)) {
    $CampaignPath = (Resolve-Path -LiteralPath $CampaignPath).Path
}
if (-not $OutPath) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $OutPath = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\acceptance\overmap-owner-ablation-$stamp.json"
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
    "-s", "res://scripts/tools/map_overmap_owner_ablation.gd",
    "--",
    "--snapshot=$SnapshotPath",
    "--out=$OutPath",
    "--width=$Width",
    "--height=$Height"
)
if ($CampaignPath) {
    $godotArgs += "--campaign=$CampaignPath"
}

Write-Host "Godot:    $godot"
Write-Host "Campaign: $CampaignPath"
Write-Host "Snapshot: $SnapshotPath"
Write-Host "Out:      $OutPath"
Write-Host "Read-only owner-snapshot ablation. Owner campaign files are not written."
$global:LASTEXITCODE = 0
& $godot @godotArgs
$code = $global:LASTEXITCODE
if ($null -eq $code) {
    $code = 0
}
if ($code -ne 0) {
    throw "Owner ablation failed with exit $code"
}
$deadline = (Get-Date).AddSeconds(15)
while (-not (Test-Path -LiteralPath $OutPath) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
if (-not (Test-Path -LiteralPath $OutPath)) {
    throw "Godot exited $code but did not write $OutPath"
}
Write-Host "Wrote $OutPath"
Get-Content -LiteralPath $OutPath
