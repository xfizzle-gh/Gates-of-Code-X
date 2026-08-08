param(
    [string]$GameLog = "",
    [string]$ScreenshotDirectory = ""
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$latest = Join-Path $root "live\issue161\latest-session.json"
if (-not (Test-Path $latest)) {
    throw "No prepared issue #161 session found at $latest"
}

$session = Get-Content -Raw $latest | ConvertFrom-Json
$sessionPath = Split-Path -Parent $session.tests[0].campaign_path
$sessionRoot = Split-Path -Parent $sessionPath
$evidence = Join-Path $sessionRoot "engine-evidence"
New-Item -ItemType Directory -Path $evidence -Force | Out-Null

if (-not $GameLog) {
    $searchRoots = @(
        (Join-Path $HOME "Documents"),
        (Join-Path $HOME "OneDrive\Documents"),
        $env:APPDATA,
        $env:LOCALAPPDATA,
        $session.game_directory
    ) | Where-Object { $_ -and (Test-Path $_) }

    $logs = foreach ($searchRoot in $searchRoots) {
        Get-ChildItem -Path $searchRoot -Filter "game.log" -File -Recurse -ErrorAction SilentlyContinue
    }
    $selectedLog = $logs | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if (-not $selectedLog) {
        throw "Could not locate game.log automatically. Re-run with -GameLog <full path>."
    }
    $GameLog = $selectedLog.FullName
}

$resolvedLog = (Resolve-Path $GameLog).Path
Copy-Item $resolvedLog (Join-Path $evidence "game.log") -Force

if ($ScreenshotDirectory) {
    $resolvedScreens = (Resolve-Path $ScreenshotDirectory).Path
    $destination = Join-Path $evidence "screenshots"
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Get-ChildItem $resolvedScreens -File |
        Where-Object { $_.Extension.ToLowerInvariant() -in @(".png", ".jpg", ".jpeg", ".webp") } |
        Copy-Item -Destination $destination -Force
}

Copy-Item $latest (Join-Path $evidence "session.json") -Force
Copy-Item $session.matrix (Join-Path $evidence "wrapper-result-matrix.csv") -Force

$logText = Get-Content -Raw (Join-Path $evidence "game.log")
$wrapperNames = @(
    "goc_ildu_rifle",
    "goc_ildu_at",
    "goc_ildu_javelin",
    "goc_ildu_recon",
    "goc_ildu_engineer",
    "goc_ildu_manpads",
    "goc_sparta_rifle",
    "goc_sparta_recon",
    "goc_vostok_rifle",
    "goc_vostok_mortar",
    "goc_vostok_spg9",
    "goc_serb_rifle",
    "goc_serb_at",
    "goc_serb_recon"
)
$errorTerms = @("error", "exception", "missing", "cannot load", "not found", "failed")
$interesting = foreach ($line in ($logText -split "`r?`n")) {
    $lower = $line.ToLowerInvariant()
    if (($wrapperNames | Where-Object { $lower.Contains($_) }).Count -gt 0 -or
        ($errorTerms | Where-Object { $lower.Contains($_) }).Count -gt 0) {
        $line
    }
}
$interesting | Set-Content (Join-Path $evidence "log-review.txt") -Encoding utf8

$readme = @"
Issue #161 native wrapper evidence

Audited commit: $($session.audited_commit)
Catalog signature: $($session.catalog_signature)
Game log source: $resolvedLog
Collected UTC: $([DateTime]::UtcNow.ToString("o"))

Required manual completion:
1. Fill wrapper-result-matrix.csv with pass/fail and actual spawned member counts.
2. Include screenshots covering ILDU, Sparta, Vostok, and Serbia.
3. Review log-review.txt against the complete game.log. Generic unrelated errors do not automatically fail the test, but every wrapper-related error is blocking.
4. Upload the final ZIP in issue #161.
"@
$readme | Set-Content (Join-Path $evidence "README.txt") -Encoding utf8

$zip = Join-Path $HOME "Desktop\goc-issue161-wrapper-engine-evidence.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $evidence "*") -DestinationPath $zip -CompressionLevel Optimal

Write-Host "Evidence package created:"
Write-Host $zip
Write-Host ""
Write-Host "Before uploading, complete wrapper-result-matrix.csv and confirm screenshots are present."
