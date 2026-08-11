param(
    [Parameter(Mandatory = $true)]
    [string]$GatesRoot,
    [string]$WorkshopRoot = "",
    [string]$West81Root = "",
    [string]$CodeXRoot = "",
    [string]$AiOverhaulRoot = "",
    [switch]$Restore,
    [switch]$SkipParentMaterialize,
    [switch]$ForceDiscardBackup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$spikeRoot = $PSScriptRoot
$resourceRoot = Join-Path $spikeRoot "resource"

if ($Restore) {
    if (-not (Test-Path -LiteralPath $GatesRoot -PathType Container)) {
        throw "Restore target GatesRoot does not exist: $GatesRoot"
    }
}
elseif (-not (Test-Path -LiteralPath $GatesRoot)) {
    New-Item -ItemType Directory -Force -Path $GatesRoot | Out-Null
}

$gates = (Resolve-Path -LiteralPath $GatesRoot).Path
$backupRoot = Join-Path $spikeRoot ".deploy-backup"
$manifestPath = Join-Path $backupRoot "deployed-files.txt"
$ledgerPath = Join-Path $backupRoot "original-ledger.json"
$parentManifestPath = Join-Path $backupRoot "parent-materialized.json"
$evidencePath = Join-Path $backupRoot "deploy-evidence.json"
$statePath = Join-Path $backupRoot "deploy-state.json"

function Write-Utf8NoBomFile([string]$Path, [string]$Content) {
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding $false))
}

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
    # Do not depend on Get-FileHash. Some Windows CI PowerShell hosts do not
    # expose that cmdlet even though the same script also runs under pwsh.
    $stream = [IO.File]::OpenRead($Path)
    try {
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = $hasher.ComputeHash($stream)
        }
        finally {
            $hasher.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
    return ([BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
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
            $candidate = Join-Path $w "2897299509"
            if (Test-Path -LiteralPath $candidate) { $resolved.West81 = $candidate }
        }
        if (-not $resolved.CodeX) {
            $candidate = Join-Path $w "3261086933"
            if (Test-Path -LiteralPath $candidate) { $resolved.CodeX = $candidate }
        }
        if (-not $resolved.AiOverhaul) {
            $candidate = Join-Path $w "3636883799"
            if (Test-Path -LiteralPath $candidate) { $resolved.AiOverhaul = $candidate }
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
        "resource/" + ($rel -replace '\\', '/')
    }
}

function Find-ParentFile {
    param(
        [string]$FileName,
        [hashtable]$Stack
    )

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

function Read-DeployState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    try {
        return (Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json)
    }
    catch {
        throw "Deploy state is unreadable at $statePath"
    }
}

function Test-UnconsumedBackup {
    if (-not (Test-Path -LiteralPath $backupRoot)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $ledgerPath)) {
        # Incomplete/stale backup tree without ledger: treat as blocking residue.
        return $true
    }

    try {
        $state = Read-DeployState
        if ($null -eq $state) { return $true }
        if ($state.status -eq "restored" -or $state.status -eq "failed_rolled_back") {
            return $false
        }
        return $true
    }
    catch {
        return $true
    }
}

function Write-DeployState([string]$Status, [string]$Message = "") {
    $obj = @{
        status       = $Status
        message      = $Message
        timestampUtc = (Get-Date).ToUniversalTime().ToString("o")
        gatesRoot    = [string]$gates
    }
    Write-Utf8NoBomFile -Path $statePath -Content (ConvertTo-Json -InputObject $obj -Depth 4)
}

function Assert-BackupTargetsCurrentGates {
    $state = Read-DeployState
    if ($null -eq $state -or -not $state.gatesRoot) {
        throw "Deploy backup is missing its recorded GatesRoot; refusing restore"
    }

    $recorded = [string]$state.gatesRoot
    if (-not (Test-Path -LiteralPath $recorded -PathType Container)) {
        throw "Recorded GatesRoot no longer exists; refusing restore: $recorded"
    }
    $recordedResolved = (Resolve-Path -LiteralPath $recorded).Path
    $comparison = [StringComparison]::Ordinal
    if ($env:OS -eq "Windows_NT") {
        $comparison = [StringComparison]::OrdinalIgnoreCase
    }
    if (-not [string]::Equals($recordedResolved, $gates, $comparison)) {
        throw "Deploy backup belongs to a different GatesRoot. Recorded='$recordedResolved' requested='$gates'"
    }
}

function Save-OriginalLedger($Ledger) {
    $rows = New-Object System.Collections.ArrayList
    foreach ($key in ($Ledger.Keys | Sort-Object)) {
        $entry = $Ledger[$key]
        [void]$rows.Add(@{
                rel     = [string]$key
                existed = [bool]$entry.existed
                bakRel  = [string]$entry.bakRel
                sha256  = [string]$entry.sha256
            })
    }

    # PS 5.1 ConvertTo-Json collapses single-element arrays; force a JSON array.
    if ($rows.Count -eq 0) {
        $json = "[]"
    }
    elseif ($rows.Count -eq 1) {
        $json = "[" + (ConvertTo-Json -InputObject $rows[0] -Depth 5 -Compress) + "]"
    }
    else {
        $json = ConvertTo-Json -InputObject @($rows.ToArray()) -Depth 5
    }
    Write-Utf8NoBomFile -Path $ledgerPath -Content $json
}

function Import-OriginalLedger {
    $map = @{}
    if (-not (Test-Path -LiteralPath $ledgerPath)) {
        return $map
    }

    $raw = Get-Content -LiteralPath $ledgerPath -Raw
    if (-not $raw -or $raw.Trim() -eq "" -or $raw.Trim() -eq "[]") {
        return $map
    }

    $rows = $raw | ConvertFrom-Json
    foreach ($row in @($rows)) {
        if ($null -eq $row) { continue }
        $map[[string]$row.rel] = @{
            existed = [bool]$row.existed
            bakRel  = [string]$row.bakRel
            sha256  = [string]$row.sha256
        }
    }
    return $map
}

function Register-OriginalState {
    param(
        [hashtable]$Ledger,
        [string]$RelUnix,
        [string]$TargetPath
    )

    # First-write wins: never overwrite an original ledger entry during one deploy.
    if ($Ledger.ContainsKey($RelUnix)) {
        return
    }

    $bakRel = $RelUnix
    $bakPath = Join-Path $backupRoot ($bakRel -replace '/', '\')
    $bakParent = Split-Path -Parent $bakPath
    if (-not (Test-Path -LiteralPath $bakParent)) {
        New-Item -ItemType Directory -Force -Path $bakParent | Out-Null
    }

    if (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
        Copy-Item -LiteralPath $TargetPath -Destination $bakPath -Force
        $Ledger[$RelUnix] = @{
            existed = $true
            bakRel  = $bakRel
            sha256  = (Get-Sha256 $TargetPath)
        }
    }
    else {
        # Originally absent: no content backup; restore deletes the target.
        Write-Utf8NoBomFile -Path ($bakPath + ".absent") -Content "originally-absent"
        $Ledger[$RelUnix] = @{
            existed = $false
            bakRel  = $bakRel
            sha256  = ""
        }
    }
}

function Copy-ToGatesSafe {
    param(
        [hashtable]$Ledger,
        [string]$SourcePath,
        [string]$RelUnix
    )

    $dst = Join-Path $gates ($RelUnix -replace '/', '\')
    Register-OriginalState -Ledger $Ledger -RelUnix $RelUnix -TargetPath $dst
    # Persist ledger before mutation so crash/failure can still roll back.
    Save-OriginalLedger -Ledger $Ledger

    $dstParent = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dstParent)) {
        New-Item -ItemType Directory -Force -Path $dstParent | Out-Null
    }
    Copy-Item -LiteralPath $SourcePath -Destination $dst -Force
    Write-Host "deployed $RelUnix"
    return $dst
}

function Invoke-RestoreFromLedger {
    param([string]$Reason = "")

    if (-not (Test-Path -LiteralPath $ledgerPath)) {
        throw "No original ledger at $ledgerPath"
    }
    Assert-BackupTargetsCurrentGates

    $ledger = Import-OriginalLedger
    if ($ledger.Count -eq 0) {
        throw "Original ledger is empty; refusing restore"
    }

    # The ledger is authoritative. It is written before every target mutation,
    # while deployed-files.txt is only progress/evidence and can lag a failed copy.
    $rels = @($ledger.Keys | Sort-Object)
    foreach ($rel in $rels) {
        $rel = [string]$rel
        $target = Join-Path $gates ($rel -replace '/', '\')
        $entry = $ledger[$rel]

        if ($entry.existed) {
            $bak = Join-Path $backupRoot ($entry.bakRel -replace '/', '\')
            if (-not (Test-Path -LiteralPath $bak -PathType Leaf)) {
                throw "Missing original backup content for $rel at $bak"
            }
            if ($entry.sha256 -and (Get-Sha256 $bak) -ne $entry.sha256) {
                throw "Original backup checksum mismatch for $rel"
            }

            $parent = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $parent)) {
                New-Item -ItemType Directory -Force -Path $parent | Out-Null
            }
            Copy-Item -LiteralPath $bak -Destination $target -Force
            if ($entry.sha256 -and (Get-Sha256 $target) -ne $entry.sha256) {
                throw "Restored target checksum mismatch for $rel"
            }
        }
        elseif (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
    }

    Write-DeployState -Status "restored" -Message $Reason
    if ($Reason) {
        Write-Host "Restored Gates root from original ledger ($Reason)"
    }
    else {
        Write-Host "Restored Gates root from original ledger"
    }
}

function Assert-ArmyIdsSafe {
    param([string[]]$Roots)

    $idMap = Get-ArmyIdMap -Roots $Roots
    $idCollisions = @()
    foreach ($entry in $PrototypeArmyIds.GetEnumerator()) {
        $id = [int]$entry.Value
        if ($id -lt 0 -or $id -gt 99) {
            throw "Army id out of range for $($entry.Key): $id"
        }

        $owners = @()
        if ($idMap.ContainsKey($id)) {
            $owners = @($idMap[$id] | ForEach-Object { "{0} @ {1}" -f $_.Army, $_.Root })
        }
        $foreign = @($owners | Where-Object { $_ -notmatch [regex]::Escape([string]$entry.Key) })
        if ($foreign.Count -gt 0) {
            $idCollisions += ("{0} id {1} collides with: {2}" -f $entry.Key, $id, ($foreign -join "; "))
        }
    }

    $dupProto = $PrototypeArmyIds.Values | Group-Object | Where-Object { $_.Count -gt 1 }
    if ($dupProto) {
        throw "Prototype army IDs are not unique within spike"
    }
    if ($idCollisions.Count -gt 0) {
        throw ("Army ID collisions in effective stack:`n - " + ($idCollisions -join "`n - "))
    }
}

function Assert-RosterIncludes {
    $rosterPath = Join-Path $gates "resource\set\multiplayer\units\roster_conquest.set"
    if (-not (Test-Path -LiteralPath $rosterPath)) {
        throw "Missing deployed roster_conquest.set"
    }

    $rosterText = [IO.File]::ReadAllText($rosterPath)
    $includeMatches = [regex]::Matches($rosterText, '\(include\s+"([^"]+)"\)')
    $missingIncludes = @()
    foreach ($match in $includeMatches) {
        $inc = $match.Groups[1].Value -replace '/', '\'
        $full = Join-Path $gates ("resource\set\multiplayer\units\" + $inc)
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
            $missingIncludes += $inc
        }
    }
    if ($missingIncludes.Count -gt 0) {
        throw ("roster_conquest.set unresolved includes:`n - " + ($missingIncludes -join "`n - "))
    }
}

# -------------------- Restore path --------------------
if ($Restore) {
    if (-not (Test-Path -LiteralPath $ledgerPath)) {
        throw "No deploy original ledger at $ledgerPath (nothing safe to restore)"
    }
    Invoke-RestoreFromLedger -Reason "explicit -Restore"
    exit 0
}

# -------------------- Deploy path --------------------
if (-not (Test-Path -LiteralPath $resourceRoot)) {
    throw "Missing spike resource tree: $resourceRoot"
}

$stack = Resolve-StackRoots -WorkshopRoot $WorkshopRoot -West81Root $West81Root -CodeXRoot $CodeXRoot -AiOverhaulRoot $AiOverhaulRoot

# Refuse to destroy an unconsumed original-state backup.
if (Test-UnconsumedBackup) {
    if (-not $ForceDiscardBackup) {
        throw @"
Unconsumed #201 deploy backup already exists at:
  $backupRoot
Restore first:
  $($MyInvocation.MyCommand.Path) -GatesRoot `"$gates`" -Restore
Or, only if you intentionally discard recovery state:
  ... -ForceDiscardBackup
"@
    }
    Write-Host "WARNING: discarding unconsumed backup due to -ForceDiscardBackup"
    Remove-Item -LiteralPath $backupRoot -Recurse -Force
}

# -------- Preflight (no Gates mutation yet) --------
$parentPlan = New-Object System.Collections.ArrayList
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
        [void]$parentPlan.Add([pscustomobject]@{
                file   = $name
                rel    = $rel
                source = $src
                sha256 = (Get-Sha256 $src)
            })
    }
}

$spikeRels = @(Get-SpikeRelatives)
if ($spikeRels.Count -lt 1) {
    throw "Spike resource tree produced no files"
}

# Preflight army IDs against read-only parents + current Gates (before we write).
$preflightRoots = @($stack.West81, $stack.CodeX, $stack.AiOverhaul, $gates) | Where-Object { $_ }
Assert-ArmyIdsSafe -Roots $preflightRoots

# -------- Begin mutation with original ledger --------
# Clear only consumed/restored residue after preflight succeeds.
if (Test-Path -LiteralPath $backupRoot) {
    Remove-Item -LiteralPath $backupRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
Write-DeployState -Status "in_progress" -Message "starting deploy"
$ledger = @{}
$deployedRels = New-Object System.Collections.ArrayList
$parentRecords = New-Object System.Collections.ArrayList

try {
    # 1) Materialize parent conquest files.
    if (-not $SkipParentMaterialize) {
        foreach ($item in $parentPlan) {
            $dst = Copy-ToGatesSafe -Ledger $ledger -SourcePath $item.source -RelUnix $item.rel
            [void]$deployedRels.Add($item.rel)
            [void]$parentRecords.Add([pscustomobject]@{
                    file       = $item.file
                    rel        = $item.rel
                    source     = $item.source
                    sha256     = $item.sha256
                    destSha256 = (Get-Sha256 $dst)
                })
            Write-Host ("parent {0} <= {1} sha256={2}" -f $item.file, $item.source, $item.sha256)
        }
        Write-Utf8NoBomFile -Path $parentManifestPath -Content (ConvertTo-Json -InputObject @($parentRecords.ToArray()) -Depth 5)
    }

    # 2) Install GOC prototype files from spike.
    foreach ($rel in $spikeRels) {
        $srcRel = $rel -replace '^resource/', ''
        $src = Join-Path $resourceRoot ($srcRel -replace '/', '\')
        Copy-ToGatesSafe -Ledger $ledger -SourcePath $src -RelUnix $rel | Out-Null
        if (-not ($deployedRels -contains $rel)) {
            [void]$deployedRels.Add($rel)
        }
    }

    Write-Utf8NoBomFile -Path $manifestPath -Content ((@($deployedRels) -join "`n") + "`n")
    Save-OriginalLedger -Ledger $ledger

    # 3) Post-copy validation.
    Assert-RosterIncludes
    $auditRoots = @($stack.West81, $stack.CodeX, $stack.AiOverhaul, $gates) | Where-Object { $_ }
    Assert-ArmyIdsSafe -Roots $auditRoots

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
        originalLedger    = $ledgerPath
        notes             = @(
            "West81/CodeX/AI Overhaul were treated as read-only sources.",
            "Only required parent conquest text files were copied into Gates.",
            "Original Gates bytes are snapshotted on first write only (duplicate paths do not clobber originals).",
            "Restore is bound to the exact recorded GatesRoot and is ledger-authoritative.",
            "No native GoH PASS is claimed by this deploy helper."
        )
    }
    Write-Utf8NoBomFile -Path $evidencePath -Content (ConvertTo-Json -InputObject $evidenceObj -Depth 6)
    Write-DeployState -Status "deployed" -Message "deploy complete"

    Write-Host "Deployed $($deployedRels.Count) files into $gates"
    Write-Host "Original ledger: $ledgerPath"
    Write-Host "Parent materialization records: $parentManifestPath"
    Write-Host "Deploy evidence: $evidencePath"
    Write-Host "Restore with: $($MyInvocation.MyCommand.Path) -GatesRoot `"$gates`" -Restore"
}
catch {
    $err = $_
    Write-Host "Deploy failed; attempting automatic rollback from original ledger..."
    try {
        if ($ledger.Count -gt 0) {
            Save-OriginalLedger -Ledger $ledger
            # Evidence only. Invoke-RestoreFromLedger intentionally ignores this
            # manifest and restores every ledgered path so a failed in-flight copy
            # cannot escape auto-rollback.
            Write-Utf8NoBomFile -Path $manifestPath -Content ((@($deployedRels) -join "`n") + "`n")
        }
        if (Test-Path -LiteralPath $ledgerPath) {
            Invoke-RestoreFromLedger -Reason ("auto-rollback: " + $err.Exception.Message)
            Write-DeployState -Status "failed_rolled_back" -Message $err.Exception.Message
        }
        else {
            Write-DeployState -Status "failed_no_ledger" -Message $err.Exception.Message
        }
    }
    catch {
        Write-Host ("Rollback also failed: " + $_.Exception.Message)
        Write-DeployState -Status "failed_partial" -Message ($err.Exception.Message + " | rollback: " + $_.Exception.Message)
        throw ("Deploy failed and rollback failed. Manual inspection required. Original error: " + $err.Exception.Message)
    }
    throw
}
