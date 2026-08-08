param(
    [string]$SourceRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$GodotPath = $env:GOC_GODOT,
    [switch]$Wait
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath $SourceRoot).Path
$ProjectRoot = Join-Path $Root "godot"
$PluginConfig = Join-Path $ProjectRoot "addons\godot_ai\plugin.cfg"
if (-not (Test-Path -LiteralPath $PluginConfig -PathType Leaf)) {
    throw "Godot AI is not installed. Run: pwsh -File .\dev\godot-ai\setup.ps1"
}

if ([string]::IsNullOrWhiteSpace($GodotPath)) {
    foreach ($commandName in @("godot4", "godot")) {
        $candidate = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($null -ne $candidate) {
            $GodotPath = $candidate.Source
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($GodotPath)) {
    $commonCandidates = @(
        "$env:LOCALAPPDATA\Programs\Godot\Godot.exe",
        "$env:ProgramFiles\Godot\Godot.exe",
        "$env:ProgramFiles\Godot\Godot_v4.7-stable_win64.exe"
    )
    foreach ($candidate in $commonCandidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $GodotPath = $candidate
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($GodotPath) -or -not (Test-Path -LiteralPath $GodotPath -PathType Leaf)) {
    throw "Godot executable not found. Pass -GodotPath or set GOC_GODOT."
}

# Keep this development integration private to the local machine. The plugin
# and any client-owned attach backend inherit the opt-out from this launcher.
$env:GODOT_AI_DISABLE_TELEMETRY = "true"
$env:DISABLE_TELEMETRY = "true"

$arguments = @("--editor", "--path", $ProjectRoot)
$process = Start-Process -FilePath $GodotPath -ArgumentList $arguments -PassThru
Write-Host "Opened Gates of CodeX in Godot with Godot AI telemetry disabled. PID: $($process.Id)"
Write-Host "Enable Godot AI once under Project > Project Settings > Plugins, then configure Grok Build in the Godot AI dock."

if ($Wait) {
    $process.WaitForExit()
    exit $process.ExitCode
}
