# Recreates campaign/ from the AssetRipper export and applies the recorded source repairs.
# Destroys local edits in campaign/ only when -Force is given.
param(
    [switch]$Force,
    [switch]$SettingsOnly,
    [string]$UnityData = 'C:\Program Files\Unity\Hub\Editor\6000.4.0f1\Editor\Data'
)
# Repair 5: PlayerSettings did not survive recovery (AssetRipper read error on globalgamemanagers).
# The game only uses the new Input System, which is off at handler 0, so no UI input reached it.
# Product/company give the app its own save location, separate from the original GOE install.
function Repair-ProjectSettings([string]$path) {
    $t = [IO.File]::ReadAllText($path)
    $t = $t -replace 'activeInputHandler: 0', 'activeInputHandler: 1'
    $t = $t -replace '(?m)^(\s*)productName: .*$', '$1productName: WarfighterCampaign'
    $t = $t -replace '(?m)^(\s*)companyName: .*$', '$1companyName: WarfighterCampaign'
    $t = $t -replace '(?m)^(\s*)runInBackground: 0', '$1runInBackground: 1'
    [IO.File]::WriteAllText($path, $t)
}
if ($SettingsOnly) { Repair-ProjectSettings (Join-Path (Split-Path $PSScriptRoot -Parent) 'campaign\ProjectSettings\ProjectSettings.asset'); return }
$root = Split-Path $PSScriptRoot -Parent
$src = Join-Path $root 'recovered\unity\ExportedProject'
$dst = Join-Path $root 'campaign'
if (-not (Test-Path $src)) { throw "Run AssetRipper export first: $src not found" }
if (Test-Path $dst) {
    if (-not $Force) { throw "campaign/ exists; pass -Force to replace it" }
    Remove-Item -LiteralPath $dst -Recurse -Force
}
Copy-Item $src $dst -Recurse

# Repair 1 and 2: Netcode ILPP output decompiled back into source. From another assembly the
# 'protected internal' base members are only 'protected', and need a derived-type qualifier.
$f = Join-Path $dst 'Assets\Scripts\Assembly-CSharp\CampaignNetworkSessionManager.cs'
$t = [IO.File]::ReadAllText($f)
$t = $t.Replace('protected internal override string __getTypeName()', 'protected override string __getTypeName()')
$t = $t.Replace('target.__rpc_exec_stage', '((CampaignNetworkSessionManager)target).__rpc_exec_stage')
[IO.File]::WriteAllText($f, $t)

Repair-ProjectSettings (Join-Path $dst 'ProjectSettings\ProjectSettings.asset')

# Repair 3: stub shaders -> real sources, and the lost URP global settings link.
python (Join-Path $PSScriptRoot 'repair_shaders.py') $UnityData
if ($LASTEXITCODE -ne 0) { throw "repair_shaders.py failed" }
# Repair 4 (dynamic TMP font atlases) runs inside Unity; see tools/unity/WfRepair.cs.

# WarFighter adaptation: unit catalogs, research trees, portraits; scenario; code hooks.
foreach ($step in 'build_wf_content.py', 'build_wf_scenario.py', 'build_wf_maps.py', 'build_wf_branding.py', 'patch_campaign_code.py') {
    python (Join-Path $PSScriptRoot $step)
    if ($LASTEXITCODE -ne 0) { throw "$step failed" }
}
Write-Output "campaign/ recreated with repairs applied"
