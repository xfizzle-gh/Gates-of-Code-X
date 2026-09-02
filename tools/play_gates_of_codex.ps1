$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..
$env:PYTHONPATH = "src"
$campaign = if ($args.Count -ge 1) { $args[0] } else { "live/europe.json" }
$codex = "E:\Steam\steamapps\workshop\content\400750\3261086933"
py -3 -m gates_of_codex play $campaign --codex $codex --snapshot "godot/campaign_snapshot.json"
