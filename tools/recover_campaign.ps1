# Recreates campaign/ from the AssetRipper export and applies the recorded source repairs.
# Destroys local edits in campaign/ only when -Force is given.
param([switch]$Force)
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
Write-Output "campaign/ recreated with repairs applied"
