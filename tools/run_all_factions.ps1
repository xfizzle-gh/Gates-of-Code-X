# Runs tests\autoplay\attack_round_trip.txt once per faction and prints one summary line each.
# Keeps the player's remembered New Campaign settings as they were.
param([ValidateSet('win', 'loss')][string]$Result = 'win')
$root = Split-Path $PSScriptRoot -Parent
$settings = Join-Path $env:USERPROFILE 'AppData\LocalLow\WarfighterCampaign\WarfighterCampaign\startup_settings.json'
$keep = Join-Path $root 'build\startup_settings.keep.json'
if (Test-Path $settings) { Copy-Item $settings $keep -Force }
$names = 'usa', 'usmc', 'uaf', 'ger', 'fra', 'idf', 'grm', 'reb', 'rus', 'pla'
foreach ($i in 0..9) {
    $o = & (Join-Path $PSScriptRoot 'run_autoplay.ps1') -Script (Join-Path $root 'tests\autoplay\attack_round_trip.txt') -Faction $i -SimulateResult $Result -TimeoutSeconds 200 2>&1 | ForEach-Object { "$_" }
    $setup = "$($o | Where-Object { $_ -like 'setup: *' } | Select-Object -First 1)"
    $attack = "$($o | Where-Object { $_ -like 'attack: *' -or $_ -like 'FAILED*' } | Select-Object -First 1)"
    $target = "$($o | Where-Object { $_ -like 'target province*' } | Select-Object -Last 1)".Replace('target province ', '')
    $exc = "$($o | Where-Object { $_ -like 'exceptions in player log*' } | Select-Object -First 1)".Replace('exceptions in player log: ', 'exc=')
    $state = if ($attack -like 'attack: pending*') { 'exported' } elseif ($attack) { $attack.Substring(0, [Math]::Min(48, $attack.Length)) } else { 'no attack' }
    $short = $setup.Replace('setup: battalion ', '').Replace('created=True; ', '')
    '{0,-5} | {1} | {2} | {3} | {4}' -f $names[$i], $short.Substring(0, [Math]::Min(95, $short.Length)), $state, $target, $exc
}
if (Test-Path $keep) { Copy-Item $keep $settings -Force }
