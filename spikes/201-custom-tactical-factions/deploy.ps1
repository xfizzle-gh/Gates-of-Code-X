param(
    [Parameter(Mandatory = $true)]
    [string]$GatesRoot,
    [string]$WorkshopRoot = "",
    [string]$West81Root = "",
    [string]$CodeXRoot = "",
    [string]$AiOverhaulRoot = "",
    [switch]$Restore,
    [switch]$SkipParentMaterialize
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$spikeRoot = $PSScriptRoot
$resourceRoot = Join-Path $spikeRoot "resource"
$gates = (Resolve-Path -LiteralPath $GatesRoot).Path
$backupRoot = Join-Path $spikeRoot ".deploy-backup"
$manifestPath = Join-Path $backupRoot "deployed-files.txt"
$parentManifestPath = Join-Path $backupRoot "parent-materialized.json"
$evidencePath = Join-Path $backupRoot "deploy-evidence.json"

# Parent conquest files required by roster_conquest.set (not vendored in git).
$ParentConquestFiles = @(
    "settings.set",
    "inf_ukr.set",
    "inf_rusa.set",
    "inf_nato.set",
    "inf_prc_era1960.set",
    "inf_csa_era1960.set",
    "units_ukr.set",
    "units_rusa.set",
    "units_nato.set",
    "units_sov_era1960.set",
    "units_csa_era1960.set",
    "units_prc_era1960.set"
)

$PrototypeArmyIds = [ordered]@{
    goc_usa  = 90
    goc_fra  = 91
    goc_srb  = 92
    goc_rus  = 93
    goc_dprk = 94
}

function Get-Sha256([string]$Path) {
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    return $hash.Hash.ToLowerInvariant()
}

function Resolve-StackRoots {
    param(
        [string]$WorkshopRoot,
        [string]$West81Root,
        [string]$CodeXRoot,
        [string]$AiOverhaulRoot
    )
    $resolved = @{
        West81     = $West81Root
        CodeX      = $CodeXRoot
        AiOverhaul = $AiOverhaulRoot
    }
    if ($WorkshopRoot -and (Test-Path -LiteralPath $WorkshopRoot)) {
        $w = (Resolve-Path -LiteralPath $WorkshopRoot).Path
        if (-not $resolved.West81) {
            $cand = Join-Path $w "2897299509"
            if (Test-Path -LiteralPath $cand) { $resolved.West81 = $cand }
        }
        if (-not $resolved.CodeX) {
            $cand = Join-Path $w "3261086933"
            if (Test-Path -LiteralPath $cand) { $resolved.CodeX = $cand }
        }
        if (-not $resolved.AiOverhaul) {
            $cand = Join-Path $w "3636883799"
            if (Test-Path -LiteralPath $cand) { $resolved.AiOverhaul = $cand }
        }
    }
    foreach ($key in @("West81", "CodeX", "AiOverhaul")) {
        if ($resolved[$key]) {
            $resolved[$key] = (Resolve-Path -LiteralPath $resolved[$key]).Path
        }
    }
    return $resolved
}

function Get-SpikeRelatives {
    Get-ChildItem -LiteralPath $resourceRoot -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($resourceRoot.Length).TrimStart('\', '/')
        ("resource/" + ($rel -replace '\\', '/'))
    }
}

function Backup-TargetFile([string]$TargetPath, [string]$RelUnix) {
    $bak = Join-Path $backupRoot ($RelUnix -replace '/', '\')
    $bakParent = Split-Path -Parent $bak
    if (-not (Test-Path -LiteralPath $bakParent)) {
        New-Item -ItemType Directory -Force -Path $bakParent | Out-Null
    }
    if (Test-Path -LiteralPath $TargetPath) {
        Copy-Item -LiteralPath $TargetPath -Destination $bak -Force
        return $true
    }
    return $false
}

function Copy-ToGates([string]$SourcePath, [string]$RelUnix) {
    $dst = Join-Path $gates ($RelUnix -replace '/', '\')
    Backup-TargetFile -TargetPath $dst -RelUnix $RelUnix | Out-Null
    $dstParent = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dstParent)) {
        New-Item -ItemType Directory -Force -Path $dstParent | Out-Null
    }
    Copy-Item -LiteralPath $SourcePath -Destination $dst -Force
    Write-Host "deployed $RelUnix"
    return $dst
}

function Find-ParentFile {
    param(
        [string]$FileName,
        [hashtable]$Stack
    )
    # Prefer AI Overhaul overlay, then Code:X. West81 rarely owns modern conquest bodies.
    $searchOrder = @($Stack.AiOverhaul, $Stack.CodeX, $Stack.West81) | Where-Object { $_ }
    foreach ($root in $searchOrder) {
        $candidate = Join-Path $root ("resource\set\multiplayer\units\conquest\" + $FileName)
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function Get-ArmyIdMap([string[]]$Roots) {
    $map = @{}
    foreach ($root in $Roots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
        $armies = Join-Path $root "resource\set\multiplayer\armies"
        if (-not (Test-Path -LiteralPath $armies)) { continue }
        Get-ChildItem -LiteralPath $armies -Filter "*.set" -File -ErrorAction SilentlyContinue | ForEach-Object {
            $text = [IO.File]::ReadAllText($_.FullName)
            if ($text -match '\{id\s+(\d+)\}') {
                $id = [int]$Matches[1]
                $name = $_.BaseName
                if (-not $map.ContainsKey($id)) {
                    $map[$id] = @()
                }
                $map[$id] += [pscustomobject]@{ Army = $name; Root = $root }
            }
        }
    }
    return $map
}

if ($Restore) {
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "No deploy backup manifest at $manifestPath"
    }
    $rels = Get-Content -LiteralPath $manifestPath
    foreach ($rel in $rels) {
        $target = Join-Path $gates ($rel -replace '/', '\')
        $bak = Join-Path $backupRoot ($rel -replace '/', '\')
        if (Test-Path -LiteralPath $bak) {
            $parent = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $parent)) {
                New-Item -ItemType Directory -Force -Path $parent | Out-Null
            }
            Copy-Item -LiteralPath $bak -Destination $target -Force
        }
        elseif (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
    }
    Write-Host "Restored Gates root from spike backup"
    exit 0
}

if (-not (Test-Path -LiteralPath $resourceRoot)) {
    throw "Missing spike resource tree: $resourceRoot"
}

$stack = Resolve-StackRoots -WorkshopRoot $WorkshopRoot -West81Root $West81Root -CodeXRoot $CodeXRoot -AiOverhaulRoot $AiOverhaulRoot

# Fresh backup directory each deploy
if (Test-Path -LiteralPath $backupRoot) {
    Remove-Item -LiteralPath $backupRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$deployedRels = New-Object System.Collections.ArrayList
$parentRecords = New-Object System.Collections.ArrayList

# 1) Materialize parent conquest files needed by final-layer roster
if (-not $SkipParentMaterialize) {
    if (-not $stack.CodeX -and -not $stack.AiOverhaul) {
        throw "Parent materialization requires -WorkshopRoot or explicit -CodeXRoot/-AiOverhaulRoot (read-only sources)."
    }
    foreach ($name in $ParentConquestFiles) {
        $src = Find-ParentFile -FileName $name -Stack $stack
        if (-not $src) {
            throw "Missing required parent conquest file in stack: $name"
        }
        $rel = "resource/set/multiplayer/units/conquest/$name"
        $dst = Copy-ToGates -SourcePath $src -RelUnix $rel
        [void]$deployedRels.Add($rel)
        [void]$parentRecords.Add([pscustomobject]@{
                file       = $name
                rel        = $rel
                source     = $src
                sha256     = (Get-Sha256 $src)
                destSha256 = (Get-Sha256 $dst)
            })
        Write-Host ("parent {0} <= {1} sha256={2}" -f $name, $src, (Get-Sha256 $src))
    }
    $parentJson = ConvertTo-Json -InputObject @($parentRecords.ToArray()) -Depth 5
    Set-Content -LiteralPath $parentManifestPath -Value $parentJson -Encoding UTF8
}

# 2) Install GOC prototype files from spike
$spikeRels = @(Get-SpikeRelatives)
foreach ($rel in $spikeRels) {
    $srcRel = $rel -replace '^resource/', ''
    $src = Join-Path $resourceRoot ($srcRel -replace '/', '\')
    Copy-ToGates -SourcePath $src -RelUnix $rel | Out-Null
    if (-not ($deployedRels -contains $rel)) {
        [void]$deployedRels.Add($rel)
    }
}

@($deployedRels) | Set-Content -LiteralPath $manifestPath -Encoding UTF8

# 3) Verify every roster_conquest.set include resolves under Gates
$rosterPath = Join-Path $gates "resource\set\multiplayer\units\roster_conquest.set"
if (-not (Test-Path -LiteralPath $rosterPath)) {
    throw "Missing deployed roster_conquest.set"
}
$rosterText = [IO.File]::ReadAllText($rosterPath)
$includeMatches = [regex]::Matches($rosterText, '\(include\s+"([^"]+)"\)')
$missingIncludes = @()
foreach ($m in $includeMatches) {
    $inc = $m.Groups[1].Value -replace '/', '\'
    $full = Join-Path $gates ("resource\set\multiplayer\units\" + $inc)
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        $missingIncludes += $inc
    }
}
if ($missingIncludes.Count -gt 0) {
    throw ("roster_conquest.set unresolved includes:`n - " + ($missingIncludes -join "`n - "))
}

# 4) Verify GOC army IDs unique in effective stack (parents read-only + Gates after deploy)
$auditRoots = @($stack.West81, $stack.CodeX, $stack.AiOverhaul, $gates) | Where-Object { $_ }
$idMap = Get-ArmyIdMap -Roots $auditRoots
$idCollisions = @()
foreach ($entry in $PrototypeArmyIds.GetEnumerator()) {
    $id = [int]$entry.Value
    $owners = @()
    if ($idMap.ContainsKey($id)) {
        $owners = @($idMap[$id] | ForEach-Object { "{0} @ {1}" -f $_.Army, $_.Root })
    }
    # Expect exactly the prototype army name on Gates (and no foreign army on same id).
    $foreign = @($owners | Where-Object { $_ -notmatch [regex]::Escape($entry.Key) })
    if ($foreign.Count -gt 0) {
        $idCollisions += ("{0} id {1} collides with: {2}" -f $entry.Key, $id, ($foreign -join "; "))
    }
}
# Also ensure prototype ids are pairwise unique
$dupProto = $PrototypeArmyIds.Values | Group-Object | Where-Object { $_.Count -gt 1 }
if ($dupProto) {
    throw "Prototype army IDs are not unique within spike"
}
if ($idCollisions.Count -gt 0) {
    throw ("Army ID collisions in effective stack:`n - " + ($idCollisions -join "`n - "))
}

# 5) Range check
foreach ($entry in $PrototypeArmyIds.GetEnumerator()) {
    $id = [int]$entry.Value
    if ($id -lt 0 -or $id -gt 99) {
        throw "Army id out of range for $($entry.Key): $id"
    }
}

$protoIds = @{}
foreach ($entry in $PrototypeArmyIds.GetEnumerator()) {
    $protoIds[[string]$entry.Key] = [int]$entry.Value
}
$stackOut = @{
    West81     = [string]$stack.West81
    CodeX      = [string]$stack.CodeX
    AiOverhaul = [string]$stack.AiOverhaul
}
$evidenceObj = @{
    timestampUtc      = (Get-Date).ToUniversalTime().ToString("o")
    gatesRoot         = [string]$gates
    stack             = $stackOut
    parentFiles       = @($parentRecords.ToArray())
    spikeFileCount    = [int]@($spikeRels).Count
    deployedFileCount = [int]$deployedRels.Count
    rosterIncludesOk  = $true
    prototypeArmyIds  = $protoIds
    armyIdAuditRoots  = @($auditRoots | ForEach-Object { [string]$_ })
    notes             = @(
        "West81/CodeX/AI Overhaul were treated as read-only sources.",
        "Only required parent conquest text files were copied into Gates.",
        "No native GoH PASS is claimed by this deploy helper."
    )
}
$evidenceJson = ConvertTo-Json -InputObject $evidenceObj -Depth 6
Set-Content -LiteralPath $evidencePath -Value $evidenceJson -Encoding UTF8

Write-Host "Deployed $($deployedRels.Count) files into $gates"
Write-Host "Parent materialization records: $parentManifestPath"
Write-Host "Deploy evidence: $evidencePath"
Write-Host "Restore with: $($MyInvocation.MyCommand.Path) -GatesRoot `"$gates`" -Restore"
