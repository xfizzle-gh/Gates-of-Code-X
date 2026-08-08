param(
    [string]$SourceRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [switch]$Clean,
    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $script:Git.Source @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git failed with exit code $LASTEXITCODE: git $($Arguments -join ' ')"
    }
}

$Root = (Resolve-Path -LiteralPath $SourceRoot).Path
$LockPath = Join-Path $Root "dev\godot-ai\lock.json"
if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
    throw "Godot AI lock file not found: $LockPath"
}

$Lock = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
$Repository = [string]$Lock.repository
$Version = [string]$Lock.version
$Commit = ([string]$Lock.commit).ToLowerInvariant()
$PluginSourceSubpath = ([string]$Lock.plugin_source_subpath) -replace '/', [System.IO.Path]::DirectorySeparatorChar
$PluginInstallSubpath = ([string]$Lock.plugin_install_subpath) -replace '/', [System.IO.Path]::DirectorySeparatorChar

if ($Commit -notmatch '^[0-9a-f]{40}$') {
    throw "Invalid pinned Godot AI commit in $LockPath"
}
if (-not [bool]$Lock.telemetry_disabled) {
    throw "The Gates integration requires telemetry_disabled=true."
}

$StateRoot = Join-Path $Root ".godot-ai"
$Checkout = Join-Path $StateRoot "source-$Commit"
$InstallPath = Join-Path $Root $PluginInstallSubpath
$InstallParent = Split-Path -Parent $InstallPath

if ($Remove) {
    if (Test-Path -LiteralPath $InstallPath) {
        Remove-Item -LiteralPath $InstallPath -Recurse -Force
    }
    if ($Clean -and (Test-Path -LiteralPath $StateRoot)) {
        Remove-Item -LiteralPath $StateRoot -Recurse -Force
    }
    [ordered]@{
        ok = $true
        removed = $true
        install_path = $InstallPath
        cache_removed = [bool]$Clean
    } | ConvertTo-Json -Depth 3
    exit 0
}

$script:Git = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $script:Git) {
    throw "Git is required to install the pinned Godot AI source."
}

if ($Clean -and (Test-Path -LiteralPath $Checkout)) {
    Remove-Item -LiteralPath $Checkout -Recurse -Force
}
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $Checkout ".git") -PathType Container)) {
    if (Test-Path -LiteralPath $Checkout) {
        Remove-Item -LiteralPath $Checkout -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Checkout -Force | Out-Null
    Invoke-Git -Arguments @("-C", $Checkout, "init")
    Invoke-Git -Arguments @("-C", $Checkout, "remote", "add", "origin", $Repository)
    Invoke-Git -Arguments @("-C", $Checkout, "fetch", "--depth", "1", "origin", $Commit)
    Invoke-Git -Arguments @("-C", $Checkout, "checkout", "--detach", "FETCH_HEAD")
}

$ResolvedCommit = (& $script:Git.Source -C $Checkout rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $ResolvedCommit -ne $Commit) {
    throw "Pinned checkout mismatch. Expected $Commit, found $ResolvedCommit"
}

$PluginSource = Join-Path $Checkout $PluginSourceSubpath
$PluginConfig = Join-Path $PluginSource "plugin.cfg"
if (-not (Test-Path -LiteralPath $PluginConfig -PathType Leaf)) {
    throw "Pinned checkout does not contain the expected plugin: $PluginConfig"
}

$PluginConfigText = Get-Content -LiteralPath $PluginConfig -Raw
if ($PluginConfigText -notmatch ('version\s*=\s*"' + [Regex]::Escape($Version) + '"')) {
    throw "Pinned plugin version does not match lock version $Version."
}

if (Test-Path -LiteralPath $InstallPath) {
    Remove-Item -LiteralPath $InstallPath -Recurse -Force
}
New-Item -ItemType Directory -Path $InstallParent -Force | Out-Null
Copy-Item -LiteralPath $PluginSource -Destination $InstallParent -Recurse -Force

$InstalledConfig = Join-Path $InstallPath "plugin.cfg"
if (-not (Test-Path -LiteralPath $InstalledConfig -PathType Leaf)) {
    throw "Godot AI installation failed: $InstalledConfig was not created."
}

$InstallRecord = [ordered]@{
    schema_version = 1
    repository = $Repository
    version = $Version
    commit = $Commit
    installed_at_utc = [DateTime]::UtcNow.ToString("o")
    install_path = $InstallPath
    telemetry_disabled = $true
}
$InstallRecord | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $StateRoot "install.json") -Encoding UTF8

$Uv = Get-Command uv -ErrorAction SilentlyContinue
$Uvx = Get-Command uvx -ErrorAction SilentlyContinue
$UvAvailable = ($null -ne $Uv -or $null -ne $Uvx)
if (-not $UvAvailable) {
    Write-Warning "uv/uvx was not found. Install uv before configuring an MCP client in the Godot AI dock."
}

Write-Host "Godot AI $Version installed from exact commit $Commit"
Write-Host "Open the editor with: pwsh -File .\dev\godot-ai\open-editor.ps1"
Write-Host "Then enable Godot AI under Project > Project Settings > Plugins."
Write-Host "In the Godot AI dock, configure Grok Build or another approved MCP client."
Write-Host "Do not use the plugin self-updater; update dev/godot-ai/lock.json through review instead."

[ordered]@{
    ok = $true
    version = $Version
    commit = $Commit
    install_path = $InstallPath
    uv_available = $UvAvailable
    telemetry_disabled_by_launcher = $true
    next_step = "Run dev/godot-ai/open-editor.ps1 and enable the plugin once."
} | ConvertTo-Json -Depth 3
