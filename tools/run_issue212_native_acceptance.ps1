param(
    [Parameter(Mandatory = $true)]
    [string]$GodotPath,

    [string]$SnapshotPath = "",

    [string]$CampaignPath = "",

    [string]$PlayerExecutable = "",

    [string]$OutputDirectory = "issue212-native-acceptance",

    [double]$ColdStartupMaxSeconds = 15.0,
    [double]$WarmStartupMaxSeconds = 5.0,
    [double]$OrderMaxSeconds = 3.0,
    [double]$EndTurnTargetSeconds = 5.0,
    [double]$EndTurnHardMaxSeconds = 8.0
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$godotProject = Join-Path $repo 'godot'

if (-not (Test-Path -LiteralPath $GodotPath -PathType Leaf)) {
    throw "Godot executable not found: $GodotPath"
}

if ([string]::IsNullOrWhiteSpace($SnapshotPath)) {
    if (-not [string]::IsNullOrWhiteSpace($env:GATES_OF_CODEX_HOME)) {
        $playerHome = $env:GATES_OF_CODEX_HOME
    } elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $playerHome = Join-Path $env:LOCALAPPDATA 'GatesOfCodeX'
    } else {
        $userProfile = [Environment]::GetFolderPath('UserProfile')
        if ([string]::IsNullOrWhiteSpace($userProfile)) {
            throw "Unable to resolve the Gates of CodeX player home. Pass -SnapshotPath explicitly."
        }
        $playerHome = Join-Path $userProfile 'AppData\Local\GatesOfCodeX'
    }

    $lastCampaignPath = Join-Path $playerHome 'last_campaign.json'
    if (-not (Test-Path -LiteralPath $lastCampaignPath -PathType Leaf)) {
        throw "No remembered production campaign found at $lastCampaignPath. Launch/create an Earth3 campaign first, or pass -SnapshotPath pointing to its current campaign_snapshot.json."
    }
    try {
        $lastCampaign = Get-Content -LiteralPath $lastCampaignPath -Raw | ConvertFrom-Json
    } catch {
        throw "Unable to read remembered production campaign pointer at $lastCampaignPath. Pass -SnapshotPath explicitly."
    }
    if ([string]$lastCampaign.schema -ne 'gates-of-codex.player-last-campaign') {
        throw "Remembered campaign pointer has an unexpected schema at $lastCampaignPath. Pass -SnapshotPath explicitly."
    }
    $rememberedCampaign = [string]$lastCampaign.campaign_path
    if ([string]::IsNullOrWhiteSpace($rememberedCampaign)) {
        throw "Remembered campaign pointer has no campaign_path at $lastCampaignPath. Pass -SnapshotPath explicitly."
    }
    if ([string]::IsNullOrWhiteSpace($CampaignPath)) {
        $CampaignPath = $rememberedCampaign
    }
    $SnapshotPath = Join-Path (Split-Path -Parent $rememberedCampaign) 'campaign_snapshot.json'
    if (-not (Test-Path -LiteralPath $SnapshotPath -PathType Leaf)) {
        throw "Remembered production campaign has no current snapshot at $SnapshotPath. Continue the campaign once to republish it, or pass -SnapshotPath explicitly."
    }
}
$SnapshotPath = (Resolve-Path -LiteralPath $SnapshotPath).Path

if ([string]::IsNullOrWhiteSpace($CampaignPath)) {
    $CampaignPath = Join-Path (Split-Path -Parent $SnapshotPath) 'campaign.json'
}
if (-not (Test-Path -LiteralPath $CampaignPath -PathType Leaf)) {
    throw "Owner-native acceptance requires the authoritative campaign beside the snapshot, or an explicit -CampaignPath: $CampaignPath"
}
$CampaignPath = (Resolve-Path -LiteralPath $CampaignPath).Path

if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $outDir = $OutputDirectory
} else {
    $outDir = Join-Path $repo $OutputDirectory
}
[System.IO.Directory]::CreateDirectory($outDir) | Out-Null
$screensDir = Join-Path $outDir 'screens'
[System.IO.Directory]::CreateDirectory($screensDir) | Out-Null
$jsonPath = Join-Path $outDir 'issue212-native-acceptance.json'

$preflight = Join-Path $PSScriptRoot 'run_owner_readiness_preflight.ps1'
if (-not (Test-Path -LiteralPath $preflight -PathType Leaf)) {
    throw "Owner-readiness performance preflight script missing: $preflight"
}
if ([string]::IsNullOrWhiteSpace($PlayerExecutable)) {
    $PlayerExecutable = Join-Path $repo 'dist\GatesOfCodeX.exe'
}
Write-Host "Running mandatory owner-readiness performance preflight before visual acceptance..."
& $preflight `
    -GodotPath $GodotPath `
    -SnapshotPath $SnapshotPath `
    -CampaignPath $CampaignPath `
    -PlayerExecutable $PlayerExecutable `
    -OutputDirectory (Join-Path $outDir 'performance-preflight') `
    -ColdStartupMaxSeconds $ColdStartupMaxSeconds `
    -WarmStartupMaxSeconds $WarmStartupMaxSeconds `
    -OrderMaxSeconds $OrderMaxSeconds `
    -EndTurnTargetSeconds $EndTurnTargetSeconds `
    -EndTurnHardMaxSeconds $EndTurnHardMaxSeconds
if ($LASTEXITCODE -ne 0) {
    throw "Owner-readiness performance preflight failed with exit code $LASTEXITCODE"
}
Write-Host "Performance preflight passed. Continuing to #212 visual/presentation acceptance."
Write-Host ""

Write-Host "Issue #212 native acceptance"
Write-Host "  Godot:    $GodotPath"
Write-Host "  Snapshot: $SnapshotPath"
Write-Host "  Output:   $outDir"
Write-Host ""
Write-Host "This run gathers evidence only. It cannot authorize the production renderer switch."
Write-Host "The snapshot must contain a real strategic formation and authenticated operational order with a non-empty legal-target set."

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
$reference = $data.authority.reference
if ([string]::IsNullOrWhiteSpace([string]$reference.selected_province_id)) {
    throw "Acceptance authority proof has an empty selected_province_id"
}
if ([string]::IsNullOrWhiteSpace([string]$reference.selected_strategic_formation_id)) {
    throw "Acceptance authority proof has an empty selected_strategic_formation_id"
}
$legalTargets = @($reference.legal_target_ids)
$expectedTargets = @($reference.operational_order_target_ids)
if ($legalTargets.Count -eq 0 -or $expectedTargets.Count -eq 0) {
    throw "Acceptance authority proof has an empty legal/expected operational target set"
}
if (-not $reference.operational_order_selection_ok) {
    throw "Acceptance authority proof did not drive a real operational order"
}
if (($legalTargets -join '|') -ne ($expectedTargets -join '|')) {
    throw "Acceptance legal-target set does not exactly match the selected formation's operational orders"
}
if ($data.decision.production_switch_authorized) {
    throw "Profiler must never self-authorize the production switch"
}

Write-Host ""
Write-Host "Operational parity proof"
Write-Host "  Selected province:  $($reference.selected_province_id)"
Write-Host "  Selected formation: $($reference.selected_strategic_formation_id)"
Write-Host "  Legal targets:      $($legalTargets -join ', ')"

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
Write-Host "NEXT OWNER GATE: inspect polygon/candidate screenshots and the performance-preflight evidence."
Write-Host "Do not change the default renderer until owner visual acceptance, owner native performance acceptance, and fresh independent review are all recorded."