# Runs an autoplay script in the campaign app with no mouse or keyboard input.
# The app is pointed at a scratch profile (build/scratch-profile), never the real game profile.
#   tools\run_autoplay.ps1 -Script tests\autoplay\attack_round_trip.txt -Faction 3 [-SimulateResult win]
param(
    [Parameter(Mandatory)][string]$Script,
    [int]$Faction = 0,
    [ValidateSet('', 'win', 'loss')][string]$SimulateResult = '',
    [int]$TimeoutSeconds = 240
)
$root = Split-Path $PSScriptRoot -Parent
$paths = Get-Content (Join-Path $PSScriptRoot 'paths.json') -Raw | ConvertFrom-Json
$work = Join-Path $root 'build\autoplay'
$out = Join-Path $work 'autoplay-out'
$profile = Join-Path $root 'build\scratch-profile'
Get-Process WarfighterCampaign -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work, (Join-Path $profile 'campaign') | Out-Null
if (-not (Test-Path (Join-Path $profile 'options.set'))) { Set-Content (Join-Path $profile 'options.set') "{options`n}`n" -NoNewline }
Get-ChildItem (Join-Path $profile 'campaign') -Filter *.sav | Remove-Item -Force
$copy = Join-Path $work 'script.txt'
(Get-Content $Script) + 'wait 2', 'quit' | Set-Content $copy
$p = Start-Process (Join-Path $root 'build\campaign-win64\WarfighterCampaign.exe') -PassThru -ArgumentList @(
    '-logFile', "`"$root\build\player-autoplay.log`"", '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '720',
    '-wfAutoplay', "`"$copy`"", '-wfNewCampaign', $Faction, '-wfGameDir', "`"$($paths.GAME)`"", '-wfProfileDir', "`"$profile`"",
    '-wfCampaignName', "`"WF Autoplay $Faction`"")
$log = Join-Path $out 'autoplay.log'
$simulated = $false
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while (-not $p.HasExited -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if ($SimulateResult -and -not $simulated -and (Test-Path $log) -and (Select-String -Path $log -Pattern '^attack: pending' -Quiet)) {
        # The attack's own save, named in the hook's log line. Battles the AI started against the player
        # earlier in the round leave other saves in the same folder.
        $line = (Select-String -Path $log -Pattern '^attack: pending .* sav=(.+?\.sav) ' | Select-Object -First 1)
        $sav = if ($line) { Get-Item -LiteralPath $line.Matches[0].Groups[1].Value -ErrorAction SilentlyContinue }
        if ($sav) {
            Copy-Item $sav.FullName (Join-Path $out 'exported.sav')
            python (Join-Path $PSScriptRoot 'simulate_battle_result.py') $sav.FullName $SimulateResult
            $simulated = $true
        }
    }
}
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force; Write-Output 'TIMED OUT - app killed' }
if (Test-Path $log) { Get-Content $log }
Write-Output ("exceptions in player log: " + (Select-String -Path "$root\build\player-autoplay.log" -Pattern 'Exception').Count)
