param(
    [string]$Actor = "",
    [string]$StackConfig = (Join-Path (Split-Path -Parent $PSScriptRoot) "config\mod-stack.windows.json"),
    [string]$GameDirectory = $env:GOH_VANILLA_ROOT,
    [string]$GatesRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$VanillaRoot = $env:GOH_VANILLA_ROOT,
    [string]$West81Root = $env:WEST81_ROOT,
    [string]$CodeXRoot = $env:CODEX_ROOT,
    [string]$AiOverhaulRoot = $env:CODEX_AI_OVERHAUL_ROOT,
    [switch]$Core,
    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$root = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$stack = (Resolve-Path $StackConfig).Path
$gates = (Resolve-Path $GatesRoot).Path

if ([string]::IsNullOrWhiteSpace($VanillaRoot)) { throw "GOH Vanilla root is required. Pass -VanillaRoot or set GOH_VANILLA_ROOT." }
if ([string]::IsNullOrWhiteSpace($West81Root)) { throw "West81 root is required. Pass -West81Root or set WEST81_ROOT." }
if ([string]::IsNullOrWhiteSpace($CodeXRoot)) { throw "Code:X root is required. Pass -CodeXRoot or set CODEX_ROOT." }
if ([string]::IsNullOrWhiteSpace($AiOverhaulRoot)) { throw "AI Overhaul root is required. Pass -AiOverhaulRoot or set CODEX_AI_OVERHAUL_ROOT." }

$env:GOH_VANILLA_ROOT = (Resolve-Path $VanillaRoot).Path
$env:WEST81_ROOT = (Resolve-Path $West81Root).Path
$env:CODEX_ROOT = (Resolve-Path $CodeXRoot).Path
$env:CODEX_AI_OVERHAUL_ROOT = (Resolve-Path $AiOverhaulRoot).Path
$env:GATES_CODEX_ROOT = $gates

$python = (& py -3.11 -c "import platform,sys; assert platform.python_version() == '3.11.9'; print(sys.executable)").Trim()
if (-not $python) { throw "Python 3.11.9 is required." }

& $python -m pip install -e $root | Out-Host

if ($Core) {
    & $python -m gates_of_codex.expanded_nations_cli core --gates-root $gates
    exit $LASTEXITCODE
}
if ([string]::IsNullOrWhiteSpace($Actor)) {
    throw "Pass -Actor with one playable actor ID, or pass -Core to restore Core Code:X mode."
}

if ($NoLaunch) {
    & $python -m gates_of_codex.expanded_nations_cli activate `
        --stack-config $stack `
        --actor $Actor `
        --gates-root $gates
    exit $LASTEXITCODE
}
if ([string]::IsNullOrWhiteSpace($GameDirectory)) {
    throw "Game directory is required for launch. Pass -GameDirectory or set GOH_VANILLA_ROOT."
}
$game = (Resolve-Path $GameDirectory).Path
& $python -m gates_of_codex.expanded_nations_cli launch `
    --stack-config $stack `
    --actor $Actor `
    --gates-root $gates `
    --game $game
exit $LASTEXITCODE
