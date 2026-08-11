[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
$git = Get-Command git -ErrorAction Stop
$dirty = @(& $git.Source -C $resolvedRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw "Unable to inspect tracked working tree." }
if ($dirty.Count -ne 0) { throw "Refusing package build: tracked working tree is dirty." }
$commit = ((& $git.Source -C $resolvedRoot rev-parse HEAD) | Out-String).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve a full Git commit."
}
$stampPath = Join-Path $resolvedRoot "src\gates_of_codex\SOURCE_COMMIT"
[System.IO.File]::WriteAllText($stampPath, "$commit`n", [System.Text.Encoding]::ASCII)
[pscustomobject]@{ Commit = $commit; StampPath = $stampPath }
