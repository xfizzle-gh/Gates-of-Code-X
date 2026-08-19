param(
    [string]$SourceCampaign = "",
    [string]$OutDir = "",
    [string]$GodotPath = "C:\Users\paulf\tools\godot\Godot_v4.7-stable_win64.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $SourceCampaign) {
    $pointer = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\last_campaign.json"
    if (-not (Test-Path -LiteralPath $pointer)) {
        throw "No last_campaign.json. Pass -SourceCampaign."
    }
    $SourceCampaign = [string]((Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json).campaign_path)
}
if (-not (Test-Path -LiteralPath $SourceCampaign)) {
    throw "Source campaign not found: $SourceCampaign"
}
if (-not $OutDir) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $OutDir = Join-Path $env:LOCALAPPDATA "GatesOfCodeX\acceptance\command-latency-$stamp"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$copyDir = Join-Path $OutDir "work"
$outJson = Join-Path $OutDir "command-latency.json"
$python = "python"
$siblingSnap = Join-Path (Split-Path -Parent $SourceCampaign) "campaign_snapshot.json"
if (Test-Path -LiteralPath $siblingSnap) {
    $ctrl = Get-Content -LiteralPath $siblingSnap -Raw | ConvertFrom-Json
    $fromSnap = [string]$ctrl.control.python_executable
    if ($fromSnap -and (Test-Path -LiteralPath $fromSnap)) {
        $python = $fromSnap
    }
}
Write-Host "Source campaign: $SourceCampaign"
Write-Host "Disposable work: $copyDir"
Write-Host "Python: $python"
Write-Host "Owner files are not written. Only the copy is mutated."
& $python (Join-Path $root "tools\capture_command_latency.py") --source-campaign $SourceCampaign --copy-dir $copyDir --out $outJson --python $python --godot $GodotPath --repo $root
if ($LASTEXITCODE -ne 0) {
    throw "Latency capture failed with exit $LASTEXITCODE"
}
Write-Host "Wrote $outJson"
