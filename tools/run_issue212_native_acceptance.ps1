param(
    [Parameter(Mandatory = $true)]
    [string]$GodotPath,

    [string]$SnapshotPath = "",

    [string]$OutputDirectory = "issue212-native-acceptance"
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$godotProject = Join-Path $repo 'godot'

if (-not (Test-Path -LiteralPath $GodotPath -PathType Leaf)) {
    throw "Godot executable not found: $GodotPath"
}

if ([string]::IsNullOrWhiteSpace($SnapshotPath)) {
    $SnapshotPath = Join-Path $godotProject 'fixtures\snapshots\earth3_theatre.json'
}
$SnapshotPath = (Resolve-Path -LiteralPath $SnapshotPath).Path

if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $outDir = $OutputDirectory
} else {
    $outDir = Join-Path $repo $OutputDirectory
}
[System.IO.Directory]::CreateDirectory($outDir) | Out-Null
$screensDir = Join-Path $outDir 'screens'
[System.IO.Directory]::CreateDirectory($screensDir) | Out-Null
$jsonPath = Join-Path $outDir 'issue212-native-acceptance.json'

Write-Host "Issue #212 native acceptance"
Write-Host "  Godot:   $GodotPath"
Write-Host "  Snapshot: $SnapshotPath"
Write-Host "  Output:   $outDir"
Write-Host ""
Write-Host "This run gathers evidence only. It cannot authorize the production renderer switch."

& $GodotPath `
    --path $godotProject `
    --audio-driver Dummy `
    -s 'res://scripts/tools/map_candidate_native_acceptance_loaded.gd' `
    -- `
    "--snapshot=$SnapshotPath" `
    "--out=$jsonPath" `
    "--screens-dir=$screensDir" `
    '--width=1920' `
    '--height=1080'

if ($LASTEXITCODE -ne 0) {
    throw "Issue #212 native acceptance profiler failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $jsonPath -PathType Leaf)) {
    throw "Acceptance JSON was not produced: $jsonPath"
}

$data = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
if (-not $data.ok) {
    throw "Acceptance JSON did not report ok=true"
}
if ($data.authority.province_count -ne $null) {
    # Compatibility with earlier result shapes; current count lives in reference.
    $provinceCount = [int]$data.authority.province_count
} else {
    $provinceCount = [int]$data.authority.reference.province_count
}
if ($provinceCount -ne 3514) {
    throw "Authority province count changed: $provinceCount"
}
if (-not $data.authority.unchanged) {
    throw "Authority hashes changed during acceptance run"
}
if ($data.decision.production_switch_authorized) {
    throw "Profiler must never self-authorize the production switch"
}

Write-Host ""
Write-Host "Scenario comparison (positive = candidate faster)"
$rows = foreach ($name in @('idle_full_theatre', 'continuous_pan', 'continuous_zoom')) {
    $row = $data.scenarios.$name
    [pscustomobject]@{
        Scenario        = $name
        PolygonP50ms    = [math]::Round([double]$row.local_polygon_baseline.frame_time_ms.p50, 3)
        CandidateP50ms  = [math]::Round([double]$row.candidate.frame_time_ms.p50, 3)
        ImprovementMs   = [math]::Round([double]$row.improvement.frame_ms_p50, 3)
        ImprovementPct  = [math]::Round([double]$row.improvement.frame_p50_ratio * 100.0, 1)
        DrawCallsSaved  = [int]$row.improvement.draw_calls_p50
        PrimitivesSaved = [int]$row.improvement.primitives_p50
    }
}
$rows | Format-Table -AutoSize

Write-Host ""
Write-Host "Evidence written to: $jsonPath"
Write-Host "Screenshots:"
Get-ChildItem -LiteralPath $screensDir -Filter '*.png' | ForEach-Object { Write-Host "  $($_.FullName)" }
Write-Host ""
Write-Host "NEXT OWNER GATE: inspect polygon/candidate screenshots and native responsiveness."
Write-Host "Do not change the default renderer until owner visual acceptance, owner native performance acceptance, and fresh independent review are all recorded."
