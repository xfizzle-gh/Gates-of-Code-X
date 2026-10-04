# Runs one autoplay script for one faction, prints the hook's key lines, and restores the player's
# remembered New Campaign settings and the bridge context afterwards.
param([Parameter(Mandatory)][string]$Script, [int]$Faction = 0, [string]$SimulateResult = '', [int]$TimeoutSeconds = 300)
$root = Split-Path $PSScriptRoot -Parent
$data = Join-Path $env:USERPROFILE 'AppData\LocalLow\WarfighterCampaign\WarfighterCampaign'
$settings = Join-Path $data 'startup_settings.json'
$keep = Join-Path $root 'build\startup_settings.keep.json'
if (Test-Path $settings) { Copy-Item $settings $keep -Force }
$runArgs = @{ Script = $Script; Faction = $Faction; TimeoutSeconds = $TimeoutSeconds }
if ($SimulateResult) { $runArgs.SimulateResult = $SimulateResult }
$lines = & (Join-Path $PSScriptRoot 'run_autoplay.ps1') @runArgs 2>&1 | ForEach-Object { "$_" }
$keys = 'setup: ', 'attack: ', 'target province', 'pending=', 'recruit: ', 'waitturn', 'round ', 'createpanel', 'FAILED', 'TIMED', 'exceptions', 'created battalion'
$lines | Where-Object { $l = $_; ($keys | Where-Object { $l.StartsWith($_) }) -or $l.Contains('playedGames') } |
    ForEach-Object { $_.Substring(0, [Math]::Min(190, $_.Length)) }
if (Test-Path $keep) { Copy-Item $keep $settings -Force }
$context = Join-Path $data 'Bridge\gow_battle_context.lua'
if (Test-Path $context) { [IO.File]::Delete($context) }
