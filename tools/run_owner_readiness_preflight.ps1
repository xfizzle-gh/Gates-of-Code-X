param(
    [Parameter(Mandatory = $true)]
    [string]$GodotPath,

    [Parameter(Mandatory = $true)]
    [string]$SnapshotPath,

    [string]$CampaignPath = "",

    [string]$PlayerExecutable = "",

    [string]$OutputDirectory = "owner-readiness-preflight",

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
$GodotPath = (Resolve-Path -LiteralPath $GodotPath).Path
$SnapshotPath = (Resolve-Path -LiteralPath $SnapshotPath).Path
$commandProbe = Join-Path $godotProject 'scripts\tools\owner_readiness_command_probe.gd'
if (-not (Test-Path -LiteralPath $commandProbe -PathType Leaf)) {
    throw "Owner-readiness Godot command probe not found: $commandProbe"
}

if ([string]::IsNullOrWhiteSpace($CampaignPath)) {
    $CampaignPath = Join-Path (Split-Path -Parent $SnapshotPath) 'campaign.json'
}
if (-not (Test-Path -LiteralPath $CampaignPath -PathType Leaf)) {
    throw "Campaign file not found for owner-readiness preflight: $CampaignPath"
}
$CampaignPath = (Resolve-Path -LiteralPath $CampaignPath).Path

if ([string]::IsNullOrWhiteSpace($PlayerExecutable)) {
    $PlayerExecutable = Join-Path $repo 'dist\GatesOfCodeX.exe'
}
if (-not (Test-Path -LiteralPath $PlayerExecutable -PathType Leaf)) {
    throw "Packaged player executable not found: $PlayerExecutable. Pass -PlayerExecutable for the exact build under test."
}
$PlayerExecutable = (Resolve-Path -LiteralPath $PlayerExecutable).Path
$liveExecutable = Join-Path (Split-Path -Parent $PlayerExecutable) 'GatesOfCodeXLive.exe'
if (-not (Test-Path -LiteralPath $liveExecutable -PathType Leaf)) {
    throw "Sibling packaged backend executable not found: $liveExecutable"
}
$liveExecutable = (Resolve-Path -LiteralPath $liveExecutable).Path

if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $outDir = $OutputDirectory
} else {
    $outDir = Join-Path $repo $OutputDirectory
}
[System.IO.Directory]::CreateDirectory($outDir) | Out-Null
$outDir = (Resolve-Path -LiteralPath $outDir).Path
$workDir = Join-Path $outDir 'working-copy'
$homeDir = Join-Path $outDir 'home'
Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $homeDir -Recurse -Force -ErrorAction SilentlyContinue
[System.IO.Directory]::CreateDirectory($workDir) | Out-Null
[System.IO.Directory]::CreateDirectory($homeDir) | Out-Null

# Never mutate the owner's acceptance campaign while measuring commands/end-turn.
$campaign = Join-Path $workDir 'campaign.json'
$snapshot = Join-Path $workDir 'campaign_snapshot.json'
$commands = Join-Path $workDir 'frontend_commands.json'
$sessionPath = Join-Path $workDir '.goc-backend-session.json'
Copy-Item -LiteralPath $CampaignPath -Destination $campaign -Force
Copy-Item -LiteralPath $SnapshotPath -Destination $snapshot -Force
'{"commands":[]}' | Set-Content -LiteralPath $commands -Encoding utf8NoBOM

function Get-ExactProcessIds([string]$ExecutablePath) {
    $resolved = [System.IO.Path]::GetFullPath($ExecutablePath)
    $ids = @()
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        if (-not [string]::IsNullOrWhiteSpace([string]$_.ExecutablePath)) {
            try {
                $candidate = [System.IO.Path]::GetFullPath([string]$_.ExecutablePath)
                if ([string]::Equals($candidate, $resolved, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $ids += [int]$_.ProcessId
                }
            } catch {}
        }
    }
    return @($ids)
}

function Stop-NewExactProcesses([string]$ExecutablePath, [int[]]$Before) {
    foreach ($pidValue in @(Get-ExactProcessIds $ExecutablePath)) {
        if ($Before -notcontains $pidValue) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
    }
}

function Read-StartupEvents([string]$LogPath) {
    $events = @()
    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) {
        return $events
    }
    foreach ($line in Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue) {
        if (-not $line.StartsWith('GOC_STARTUP ')) { continue }
        try {
            $events += ($line.Substring(12) | ConvertFrom-Json)
        } catch {}
    }
    return $events
}

function Wait-FirstUsable([string]$LogPath, [int]$TimeoutSeconds = 120) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $events = @(Read-StartupEvents $LogPath)
        $marker = @($events | Where-Object { $_.stage -eq 'first_usable_strategic_frame' } | Select-Object -Last 1)
        if ($marker.Count -gt 0) {
            return [pscustomobject]@{ Marker = $marker[0]; Events = $events }
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Timed out waiting for first_usable_strategic_frame in $LogPath"
}

function Quote-ProcessArgument([string]$Value) {
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Invoke-StartupSample([string]$Name) {
    $logPath = Join-Path $outDir ("startup-{0}.jsonl" -f $Name)
    Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue
    $beforeGodot = @(Get-ExactProcessIds $GodotPath)
    $previousHome = $env:GATES_OF_CODEX_HOME
    $previousTelemetry = $env:GATES_OF_CODEX_STARTUP_TELEMETRY
    $previousLog = $env:GATES_OF_CODEX_STARTUP_LOG
    try {
        $env:GATES_OF_CODEX_HOME = $homeDir
        $env:GATES_OF_CODEX_STARTUP_TELEMETRY = '1'
        $env:GATES_OF_CODEX_STARTUP_LOG = $logPath
        $args = @(
            '--continue',
            '--campaign', (Quote-ProcessArgument $campaign),
            '--godot', (Quote-ProcessArgument $GodotPath),
            '--godot-project', (Quote-ProcessArgument $godotProject)
        )
        $launcher = Start-Process -FilePath $PlayerExecutable -ArgumentList $args -PassThru
        if (-not $launcher.WaitForExit(120000)) {
            try { $launcher.Kill() } catch {}
            throw "$Name packaged launcher did not exit within 120 seconds"
        }
        if ($launcher.ExitCode -ne 0) {
            throw "$Name packaged launcher exited with code $($launcher.ExitCode)"
        }
        $observed = Wait-FirstUsable $logPath
        $seconds = [double]$observed.Marker.since_process_entry_ms / 1000.0
        $reuse = @($observed.Events | Where-Object { $_.stage -eq 'unchanged_continue_reuse' } | Select-Object -Last 1)
        return [pscustomobject]@{
            name = $Name
            seconds = [math]::Round($seconds, 3)
            reused = ($reuse.Count -gt 0 -and [bool]$reuse[0].reused)
            reuse_reason = if ($reuse.Count -gt 0) { [string]$reuse[0].reason } else { '' }
            log = $logPath
        }
    }
    finally {
        Stop-NewExactProcesses $GodotPath $beforeGodot
        $env:GATES_OF_CODEX_HOME = $previousHome
        $env:GATES_OF_CODEX_STARTUP_TELEMETRY = $previousTelemetry
        $env:GATES_OF_CODEX_STARTUP_LOG = $previousLog
    }
}

function Get-SessionDescriptor([int]$TimeoutSeconds = 20) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $sessionPath -PathType Leaf) {
            try {
                $session = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
                if ([int]$session.pid -gt 0) {
                    return [pscustomobject]@{ Path = $sessionPath; Data = $session }
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Persistent backend session descriptor was not established for $campaign"
}

function Assert-SessionAlive($Session) {
    $pidValue = [int]$Session.Data.pid
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        throw "Persistent backend PID $pidValue is not alive"
    }
    if ([string]::IsNullOrWhiteSpace([string]$process.ExecutablePath)) {
        throw "Persistent backend PID $pidValue has no inspectable executable path"
    }
    $actual = [System.IO.Path]::GetFullPath([string]$process.ExecutablePath)
    if (-not [string]::Equals($actual, $liveExecutable, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Persistent backend PID $pidValue is not the exact packaged GatesOfCodeXLive.exe under test: $actual"
    }
    $current = Get-Content -LiteralPath $Session.Path -Raw | ConvertFrom-Json
    if ([int]$current.pid -ne $pidValue) {
        throw "Persistent backend session PID changed during readiness preflight"
    }
}

function Stop-Session($Session) {
    if ($null -eq $Session) { return }
    try {
        Assert-SessionAlive $Session
        Stop-Process -Id ([int]$Session.Data.pid) -Force -ErrorAction SilentlyContinue
    } catch {}
    Remove-Item -LiteralPath $sessionPath -Force -ErrorAction SilentlyContinue
}

function Start-PersistentSession([string]$ExpectedCommit) {
    Remove-Item -LiteralPath $sessionPath -Force -ErrorAction SilentlyContinue
    $args = @(
        'session-backend',
        (Quote-ProcessArgument $campaign),
        '--snapshot', (Quote-ProcessArgument $snapshot),
        '--expected-source-commit', $ExpectedCommit
    )
    $null = Start-Process -FilePath $liveExecutable -ArgumentList $args -WindowStyle Hidden -PassThru
    $session = Get-SessionDescriptor
    Assert-SessionAlive $session
    return $session
}

function Stop-CurrentOwnedSession {
    if (-not (Test-Path -LiteralPath $sessionPath -PathType Leaf)) { return }
    try {
        $data = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
        $candidate = [pscustomobject]@{ Path = $sessionPath; Data = $data }
        Stop-Session $candidate
    } catch {
        Remove-Item -LiteralPath $sessionPath -Force -ErrorAction SilentlyContinue
    }
}

function Write-Command([hashtable]$Command) {
    $body = @{ commands = @($Command) } | ConvertTo-Json -Depth 20 -Compress
    [System.IO.File]::WriteAllText($commands, $body + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

function Invoke-PackagedCommand([hashtable]$Command, [string]$ExpectedCommit) {
    Write-Command $Command
    $probeResultPath = Join-Path $outDir ("command-probe-{0}-{1}.json" -f ([string]$Command.op), [guid]::NewGuid().ToString('N'))
    $probeStdoutPath = Join-Path $outDir ("command-probe-{0}-{1}.stdout.txt" -f ([string]$Command.op), [guid]::NewGuid().ToString('N'))
    $probeStderrPath = Join-Path $outDir ("command-probe-{0}-{1}.stderr.txt" -f ([string]$Command.op), [guid]::NewGuid().ToString('N'))
    $godotArgs = @(
        '--headless',
        '--path', (Quote-ProcessArgument $godotProject),
        '--audio-driver', 'Dummy',
        '-s', 'res://scripts/tools/owner_readiness_command_probe.gd',
        '--',
        (Quote-ProcessArgument "--campaign=$campaign"),
        (Quote-ProcessArgument "--snapshot=$snapshot"),
        (Quote-ProcessArgument "--commands=$commands"),
        (Quote-ProcessArgument "--backend=$liveExecutable"),
        "--expected-source-commit=$ExpectedCommit",
        (Quote-ProcessArgument "--out=$probeResultPath")
    )
    $probeProcess = Start-Process `
        -FilePath $GodotPath `
        -ArgumentList $godotArgs `
        -RedirectStandardOutput $probeStdoutPath `
        -RedirectStandardError $probeStderrPath `
        -PassThru
    if (-not $probeProcess.WaitForExit(620000)) {
        try { $probeProcess.Kill() } catch {}
        throw "Godot retained-backend command probe $($Command.op) did not exit within 620 seconds"
    }
    $probeProcess.WaitForExit()
    $probeExitCode = [int]$probeProcess.ExitCode
    $probeOutput = @()
    if (Test-Path -LiteralPath $probeStdoutPath -PathType Leaf) {
        $probeOutput += Get-Content -LiteralPath $probeStdoutPath -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $probeStderrPath -PathType Leaf) {
        $probeOutput += Get-Content -LiteralPath $probeStderrPath -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $probeStdoutPath, $probeStderrPath -Force -ErrorAction SilentlyContinue
    if ($probeExitCode -ne 0) {
        throw "Godot retained-backend command probe $($Command.op) failed with exit code $probeExitCode`: $($probeOutput -join [Environment]::NewLine)"
    }
    if (-not (Test-Path -LiteralPath $probeResultPath -PathType Leaf)) {
        throw "Godot retained-backend command probe produced no result for $($Command.op)"
    }
    $probe = Get-Content -LiteralPath $probeResultPath -Raw | ConvertFrom-Json
    Remove-Item -LiteralPath $probeResultPath -Force -ErrorAction SilentlyContinue
    if (-not [bool]$probe.ok) {
        throw "Godot retained-backend command probe returned ok=false for $($Command.op): $($probe | ConvertTo-Json -Depth 20 -Compress)"
    }
    if (-not [bool]$probe.persistent_backend_used -or -not ([string]$probe.launch_path).StartsWith('persistent-backend://')) {
        throw "Warm packaged command $($Command.op) did not use the retained backend directly: $([string]$probe.launch_path)"
    }
    $report = $probe.backend_report
    if ($null -eq $report -or -not [bool]$report.ok) {
        throw "Retained backend command $($Command.op) returned an invalid backend report"
    }
    $wallSeconds = [double]$probe.command_elapsed_ms / 1000.0
    $backendSeconds = [double]$report.timings.total_ms / 1000.0
    return [pscustomobject]@{
        op = [string]$Command.op
        wall_seconds = [math]::Round($wallSeconds, 3)
        client_overhead_seconds = [math]::Round([math]::Max(0.0, $wallSeconds - $backendSeconds), 3)
        persistent_backend_used = [bool]$probe.persistent_backend_used
        launch_path = [string]$probe.launch_path
        report = $report
    }
}

Write-Host "Owner-readiness performance preflight"
Write-Host "  Player:   $PlayerExecutable"
Write-Host "  Backend:  $liveExecutable"
Write-Host "  Godot:    $GodotPath"
Write-Host "  Campaign: $CampaignPath (copied; source will not be mutated)"
Write-Host "  Command path: Godot FrontendCommandRunner -> authenticated retained backend"
Write-Host ""

$session = $null
try {
    # The first launch of a freshly built package may legitimately rewrite launch
    # settings, build the derived snapshot cache, and cold-import Godot. Record
    # that setup cost, but do not confuse it with the #221 comparable cold gate.
    $setup = Invoke-StartupSample 'setup'
    $session = Get-SessionDescriptor
    Assert-SessionAlive $session
    Stop-Session $session
    $session = $null

    # Comparable cold acceptance: daemon absent, authoritative files unchanged,
    # snapshot/import caches already established by the setup pass.
    $cold = Invoke-StartupSample 'cold'
    $session = Get-SessionDescriptor
    Assert-SessionAlive $session
    if ($cold.reused) {
        throw "Cold startup unexpectedly reused an existing daemon; daemon-cold proof is invalid"
    }
    if ($cold.seconds -gt $ColdStartupMaxSeconds) {
        throw "Daemon-cold first-usable startup $($cold.seconds)s exceeds ${ColdStartupMaxSeconds}s owner-readiness limit"
    }

    $warm = Invoke-StartupSample 'warm'
    if (-not $warm.reused) {
        throw "Warm startup did not prove unchanged_continue_reuse reused=true (reason=$($warm.reuse_reason))"
    }
    if ($warm.seconds -gt $WarmStartupMaxSeconds) {
        throw "Warm first-usable startup $($warm.seconds)s exceeds ${WarmStartupMaxSeconds}s owner-readiness limit"
    }
    Assert-SessionAlive $session

    $snapshotData = Get-Content -LiteralPath $snapshot -Raw | ConvertFrom-Json
    $expectedCommit = [string]$snapshotData.control.backend_source_commit
    if ([string]::IsNullOrWhiteSpace($expectedCommit)) {
        throw "Published packaged snapshot has no control.backend_source_commit"
    }
    $currentFaction = [string]$snapshotData.campaign.current_faction
    $formations = @{}
    foreach ($formation in @($snapshotData.strategic_formations)) {
        $formations[[string]$formation.id] = $formation
    }
    $route = $null
    foreach ($candidate in @($snapshotData.operational_orders)) {
        $formationId = [string]$candidate.formation_id
        if (-not $formations.ContainsKey($formationId)) { continue }
        $formation = $formations[$formationId]
        if ([string]$formation.faction -ne $currentFaction) { continue }
        $status = [string]$formation.move_order.status
        if ($status -in @('draft', 'committed', 'active')) { continue }
        if (@($candidate.path_node_ids).Count -lt 2) { continue }
        if (@($candidate.path_edge_ids).Count -ne (@($candidate.path_node_ids).Count - 1)) { continue }
        $route = $candidate
        break
    }
    if ($null -eq $route) {
        throw "No clean legal operational order is available for native order-latency preflight"
    }

    $order = Invoke-PackagedCommand @{
        op = 'issue_move_order'
        command_id = 'owner-readiness-order'
        formation = [string]$route.formation_id
        path_node_ids = @($route.path_node_ids)
        path_edge_ids = @($route.path_edge_ids)
    } $expectedCommit
    Assert-SessionAlive $session
    if (-not [bool]$order.report.timings.snapshot_fast_path) {
        throw "Legal order did not use the bounded snapshot fast path"
    }
    if ($order.wall_seconds -gt $OrderMaxSeconds) {
        throw "Legal order submission $($order.wall_seconds)s exceeds ${OrderMaxSeconds}s owner-readiness limit"
    }

    $cancel = Invoke-PackagedCommand @{
        op = 'cancel_move_order'
        command_id = 'owner-readiness-cancel'
        formation = [string]$route.formation_id
    } $expectedCommit
    Assert-SessionAlive $session

    $baselineCampaign = [System.IO.File]::ReadAllBytes($campaign)
    $baselineSnapshot = [System.IO.File]::ReadAllBytes($snapshot)
    $endTurns = @()
    $endTurnSessionPids = @()
    $warnings = @()
    for ($index = 1; $index -le 3; $index++) {
        if ($index -gt 1) {
            Stop-Session $session
            [System.IO.File]::WriteAllBytes($campaign, $baselineCampaign)
            [System.IO.File]::WriteAllBytes($snapshot, $baselineSnapshot)
            '{"commands":[]}' | Set-Content -LiteralPath $commands -Encoding utf8NoBOM
            $session = Start-PersistentSession $expectedCommit
        }
        Assert-SessionAlive $session
        $endTurnSessionPids += [int]$session.Data.pid
        $sample = Invoke-PackagedCommand @{
            op = 'end_player_round'
            command_id = "owner-readiness-end-turn-$index"
        } $expectedCommit
        Assert-SessionAlive $session
        if (-not [bool]$sample.report.timings.runtime_patch_fast_path) {
            throw "End Turn $index did not use the bounded runtime-patch fast path"
        }
        if ($sample.wall_seconds -gt $EndTurnHardMaxSeconds) {
            throw "End Turn $index took $($sample.wall_seconds)s, exceeding ${EndTurnHardMaxSeconds}s hard owner-readiness limit"
        }
        if ($sample.wall_seconds -gt $EndTurnTargetSeconds) {
            $warnings += "End Turn $index took $($sample.wall_seconds)s, above ${EndTurnTargetSeconds}s target"
        }
        $endTurns += $sample
    }

    $result = [ordered]@{
        ok = $true
        schema = 'gates-of-codex.owner-readiness-performance'
        schema_version = 3
        source_commit = $expectedCommit
        player_executable = $PlayerExecutable
        backend_executable = $liveExecutable
        godot_executable = $GodotPath
        source_campaign = $CampaignPath
        working_campaign = $campaign
        command_transport = 'godot-direct-retained-backend'
        persistent_backend_session_pids = $endTurnSessionPids
        thresholds_seconds = [ordered]@{
            cold_startup_max = $ColdStartupMaxSeconds
            warm_startup_max = $WarmStartupMaxSeconds
            legal_order_max = $OrderMaxSeconds
            end_turn_target = $EndTurnTargetSeconds
            end_turn_hard_max = $EndTurnHardMaxSeconds
        }
        setup_prime = $setup
        cold_startup = $cold
        warm_startup = $warm
        legal_order = [ordered]@{
            formation_id = [string]$route.formation_id
            target_province_id = [string]$route.target_province_id
            wall_seconds = $order.wall_seconds
            client_overhead_seconds = $order.client_overhead_seconds
            persistent_backend_used = $order.persistent_backend_used
            launch_path = $order.launch_path
            backend_timings = $order.report.timings
        }
        cancel_order = [ordered]@{
            wall_seconds = $cancel.wall_seconds
            client_overhead_seconds = $cancel.client_overhead_seconds
            persistent_backend_used = $cancel.persistent_backend_used
            launch_path = $cancel.launch_path
            backend_timings = $cancel.report.timings
        }
        end_turns = @($endTurns | ForEach-Object {
            [ordered]@{
                wall_seconds = $_.wall_seconds
                client_overhead_seconds = $_.client_overhead_seconds
                persistent_backend_used = $_.persistent_backend_used
                launch_path = $_.launch_path
                backend_timings = $_.report.timings
                turn_number = [int]$_.report.turn_number
                pending_battle = [bool]$_.report.pending_battle
            }
        })
        warnings = $warnings
    }
    $jsonPath = Join-Path $outDir 'owner-readiness-performance.json'
    $result | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $jsonPath -Encoding utf8NoBOM

    Write-Host ""
    Write-Host ("PASS setup={0}s cold={1}s warm={2}s order={3}s end-turns={4}" -f $setup.seconds, $cold.seconds, $warm.seconds, $order.wall_seconds, ((@($endTurns | ForEach-Object { $_.wall_seconds })) -join ', '))
    foreach ($warning in $warnings) { Write-Warning $warning }
    Write-Host "Evidence: $jsonPath"
}
finally {
    if ($null -ne $session) {
        Stop-Session $session
    } else {
        Stop-CurrentOwnedSession
    }
}
