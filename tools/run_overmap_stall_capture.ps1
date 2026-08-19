param(
    [string]$GodotPath = "",
    [string]$CampaignPath = "",
    [string]$SnapshotPath = "",
    [string]$OutPath = "",
    [int]$Width = 1920,
    [int]$Height = 1080,
    [switch]$Vsync
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
    $OutPath = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\acceptance\overmap-stall-$stamp.json"
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
    "-s", "res://scripts/tools/map_overmap_stall_capture.gd",
    "--",
    "--snapshot=$SnapshotPath",
    "--out=$OutPath",
    "--width=$Width",
    "--height=$Height",
    "--label=owner"
)
if ($CampaignPath) {
    $godotArgs += "--campaign=$CampaignPath"
}
if ($Vsync) {
    $godotArgs = @($godotArgs | Where-Object { $_ -ne "--disable-vsync" })
    $godotArgs += "--vsync"
}

Write-Host "Godot:    $godot"
Write-Host "Campaign: $CampaignPath"
Write-Host "Snapshot: $SnapshotPath"
Write-Host "Out:      $OutPath"
Write-Host "Read-only pan/zoom/select. Owner campaign files are not written."
$global:LASTEXITCODE = 0
& $godot @godotArgs
$code = $global:LASTEXITCODE
if ($null -eq $code) {
    $code = 0
}
if ($code -ne 0) {
    throw "Stall capture failed with exit $code"
}
Write-Host "Wrote $OutPath"
Get-Content -LiteralPath $OutPath
