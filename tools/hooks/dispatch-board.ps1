# Codex hook: auto-dispatch board.
#
# Events: SessionStart / UserPromptSubmit.
# stdin : hook event JSON (UTF-8)
# stdout: hook output JSON (UTF-8)  -- or plain text with -DryRun
#
# What it does: reads <workspace>/<plan-dir>/dispatch_graph.json (a machine
# readable DAG of the execution plan) plus the done/claim markers under
# <workspace>/docs/evidence/_v15_dispatch/, then injects a board saying which
# task cards can be dispatched to sub-agents RIGHT NOW in parallel.  A card is
# dispatchable only when (a) its dependencies are all done, (b) its write-set
# does not intersect any in-flight or already-selected card, (c) its mode is
# "auto" (not serial / not user-decision / not a gate), and (d) the parallelism
# cap is not reached.  Anything else is reported as "do not dispatch" with a
# reason code, so the main thread falls back to serial execution instead of
# hurting quality.
#
# NOTE: this file MUST stay ASCII-only.  Windows PowerShell 5.1 reads a BOM-less
# UTF-8 .ps1 as ANSI; any non-ASCII byte would swallow the following line.  The
# Chinese prose lives in dispatch-board.md (read explicitly as UTF-8), and the
# one non-ASCII path segment is built from code points below.

param(
    [string]$Workspace = '',
    [string]$Claim = '',
    [string]$Mark = '',
    [string]$Unclaim = '',
    [switch]$Status,
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$utf8 = New-Object System.Text.UTF8Encoding($false)

$script:Root = $PSScriptRoot
if (-not $script:Root) {
    $script:Root = Split-Path -Parent $MyInvocation.MyCommand.Path
}

function Get-Text([string]$fileName) {
    $path = Join-Path $script:Root $fileName
    if (Test-Path -LiteralPath $path) {
        return ([System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)).Trim()
    }
    return ''
}

# --- workspace resolution --------------------------------------------------- #
# Plan directory name is non-ASCII (U+6267 U+884C U+6587 U+6863 + "v1.5");
# build it from code points so this file stays pure ASCII.
$planDirCodes = [char[]]@(0x6267, 0x884C, 0x6587, 0x6863)
$planDir = ($planDirCodes -join '') + 'v1.5'

function Resolve-Workspace([string]$explicit, $event) {
    if ($explicit -and (Test-Path -LiteralPath $explicit)) { return $explicit }
    $cfg = Get-Text 'dispatch-config.json'
    if ($cfg) {
        try {
            $ws = [string](($cfg | ConvertFrom-Json).workspace)
            if ($ws -and (Test-Path -LiteralPath $ws)) { return $ws }
        } catch { }
    }
    foreach ($name in @('cwd', 'workspace', 'working_directory')) {
        if ($event) {
            $value = $event.$name
            if ($value -is [string] -and $value -and (Test-Path -LiteralPath $value)) {
                return [string]$value
            }
        }
    }
    return (Get-Location).Path
}

function Get-GraphPath([string]$ws) {
    $candidates = @(
        (Join-Path $ws (Join-Path $planDir 'dispatch_graph.json')),
        (Join-Path $ws 'dispatch_graph.json'),
        (Join-Path $ws 'docs\evidence\_v15_dispatch\dispatch_graph.json')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return ''
}

function Get-StateDir([string]$ws) {
    return (Join-Path $ws 'docs\evidence\_v15_dispatch')
}

function Normalise([string]$value) {
    return ($value -replace '\\', '/').Trim().ToLowerInvariant()
}

function Test-Overlap($filesA, $filesB) {
    foreach ($a in @($filesA)) {
        foreach ($b in @($filesB)) {
            $x = Normalise $a
            $y = Normalise $b
            if (-not $x -or -not $y) { continue }
            if ($x -eq $y) { return $true }
            if ($x.EndsWith('/') -and $y.StartsWith($x)) { return $true }
            if ($y.EndsWith('/') -and $x.StartsWith($y)) { return $true }
        }
    }
    return $false
}

function Get-Markers([string]$dir, [string]$ext) {
    $names = @()
    if (Test-Path -LiteralPath $dir) {
        Get-ChildItem -LiteralPath $dir -Filter ("*" + $ext) -File -ErrorAction SilentlyContinue |
            ForEach-Object { $names += $_.BaseName }
    }
    return $names
}

function Write-Marker([string]$dir, [string]$id, [string]$ext) {
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $path = Join-Path $dir ($id + $ext)
    $stamp = (Get-Date).ToString('s')
    [System.IO.File]::WriteAllText($path, $stamp + "`n", $utf8)
    return $path
}

function Remove-Marker([string]$dir, [string]$id, [string]$ext) {
    $path = Join-Path $dir ($id + $ext)
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    return $path
}

# --- stdin / event ---------------------------------------------------------- #
$raw = ''
try {
    $stdinStream = [Console]::OpenStandardInput()
    $stdinReader = New-Object System.IO.StreamReader($stdinStream, $utf8)
    $raw = $stdinReader.ReadToEnd()
} catch {
    $raw = ''
}

$event = $null
$eventName = 'UserPromptSubmit'
if ($raw) {
    try {
        $event = $raw | ConvertFrom-Json
        if ($event -and $event.hook_event_name) {
            $eventName = [string]$event.hook_event_name
        }
    } catch {
        $event = $null
    }
}

$ws = Resolve-Workspace $Workspace $event
$graphPath = Get-GraphPath $ws
if (-not $graphPath) { exit 0 }
$stateDir = Get-StateDir $ws
$doneDir = Join-Path $stateDir 'done'
$inflightDir = Join-Path $stateDir 'inflight'

# --- state maintenance modes ------------------------------------------------ #
if ($Claim) { Write-Marker $inflightDir $Claim '.claim' | Out-Null; exit 0 }
if ($Mark) {
    Write-Marker $doneDir $Mark '.done' | Out-Null
    Remove-Marker $inflightDir $Mark '.claim' | Out-Null
    exit 0
}
if ($Unclaim) { Remove-Marker $inflightDir $Unclaim '.claim' | Out-Null; exit 0 }

# --- load graph + state ----------------------------------------------------- #
$graph = $null
try {
    $graph = [System.IO.File]::ReadAllText($graphPath,
             [System.Text.Encoding]::UTF8) | ConvertFrom-Json
} catch {
    exit 0
}
if (-not $graph -or -not $graph.cards) { exit 0 }

$maxParallel = 6
if ($graph.max_parallel) { $maxParallel = [int]$graph.max_parallel }

$done = @{}
foreach ($id in (Get-Markers $doneDir '.done')) { $done[$id.ToUpperInvariant()] = $true }
$inflight = @{}
foreach ($id in (Get-Markers $inflightDir '.claim')) { $inflight[$id.ToUpperInvariant()] = $true }

$cards = @($graph.cards)
$total = $cards.Count

$inflightCards = @()
foreach ($card in $cards) {
    if ($inflight.ContainsKey([string]$card.id.ToUpperInvariant())) { $inflightCards += $card }
}

# --- compute ready / blocked ------------------------------------------------ #
$ready = @()
$blocked = @()
$blockedFiles = @()
foreach ($card in $inflightCards) {
    foreach ($f in @($card.files)) { $blockedFiles += $f }
}
$slots = $maxParallel - $inflightCards.Count

$ordered = @($cards | Sort-Object @{Expression = { [int]$_.phase }}, @{Expression = { [string]$_.id }})

foreach ($card in $ordered) {
    $id = [string]$card.id
    $upper = $id.ToUpperInvariant()
    if ($done.ContainsKey($upper)) { continue }
    if ($inflight.ContainsKey($upper)) { continue }

    $mode = 'auto'
    if ($card.mode) { $mode = [string]$card.mode }

    $missing = @()
    foreach ($dep in @($card.depends_on)) {
        if (-not $done.ContainsKey([string]$dep.ToUpperInvariant())) { $missing += [string]$dep }
    }
    if ($missing.Count -gt 0) {
        $blocked += [ordered]@{ id = $id; reason = ('depends:' + ($missing -join ',')) }
        continue
    }
    if ($mode -eq 'serial') {
        $blocked += [ordered]@{ id = $id; reason = 'mode:serial' }
        continue
    }
    if ($mode -eq 'user') {
        $blocked += [ordered]@{ id = $id; reason = 'mode:user' }
        continue
    }
    if ($mode -eq 'gate') {
        $blocked += [ordered]@{ id = $id; reason = 'mode:gate' }
        continue
    }

    $hit = ''
    foreach ($other in $inflightCards) {
        if (Test-Overlap $card.files $other.files) { $hit = [string]$other.id; break }
    }
    if ($hit) {
        $blocked += [ordered]@{ id = $id; reason = ('conflict:' + $hit) }
        continue
    }
    if ($slots -le 0) {
        $blocked += [ordered]@{ id = $id; reason = 'cap' }
        continue
    }
    # also avoid two ready cards that would fight over the same files
    $clash = ''
    foreach ($other in $ready) {
        if (Test-Overlap $card.files $other.files) { $clash = [string]$other.id; break }
    }
    if ($clash) {
        $blocked += [ordered]@{ id = $id; reason = ('conflict:' + $clash) }
        continue
    }

    $ready += $card
    foreach ($f in @($card.files)) { $blockedFiles += $f }
    $slots = $slots - 1
}

# --- render ----------------------------------------------------------------- #
# Pre-dispatch analysis: per card, its goal and how coupled it is to the rest
# of the plan (shared write-set / dependency depth / frozen instruments), then
# a batch decision.  The point of the board is to answer "may I dispatch, and
# how many" from evidence rather than from optimism.
$frozen = @()
$freezePath = Join-Path $ws 'tests\plan_v4_instruments.sha256.json'
if (Test-Path -LiteralPath $freezePath) {
    try {
        $freezeDoc = [System.IO.File]::ReadAllText($freezePath,
                     [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        foreach ($prop in $freezeDoc.instruments.PSObject.Properties) {
            $frozen += (Normalise ([string]$prop.Name))
        }
    } catch { $frozen = @() }
}

function Get-Coupling([object]$card, [object[]]$all) {
    $count = 0
    foreach ($other in $all) {
        if ([string]$other.id -eq [string]$card.id) { continue }
        if (Test-Overlap $card.files $other.files) { $count = $count + 1 }
    }
    return $count
}

function Get-FrozenHits([object]$card) {
    $hits = @()
    foreach ($f in @($card.files)) {
        $n = Normalise $f
        if ($frozen -contains $n) { $hits += $n }
    }
    return $hits
}

$depDepth = @{}
function Get-Depth([string]$id, [hashtable]$edges) {
    if ($depDepth.ContainsKey($id)) { return $depDepth[$id] }
    $myets = 0
    foreach ($dep in @($edges[$id])) {
        $d = 1 + (Get-Depth ([string]$dep) $edges)
        if ($d -gt $myets) { $myets = $d }
    }
    $depDepth[$id] = $myets
    return $myets
}
$edges = @{}
foreach ($card in $cards) { $edges[[string]$card.id] = @($card.depends_on) }
foreach ($card in $cards) { Get-Depth ([string]$card.id) $edges | Out-Null }

$readyIds = @{}
foreach ($card in $ready) { $readyIds[[string]$card.id] = $true }

$analysisLines = @()
$analysisRecords = @()
foreach ($card in $ordered) {
    $id = [string]$card.id
    $upper = $id.ToUpperInvariant()
    $state = 'pending'
    if ($done.ContainsKey($upper)) { $state = 'done' }
    elseif ($inflight.ContainsKey($upper)) { $state = 'inflight' }
    elseif ($readyIds.ContainsKey($id)) { $state = 'DISPATCH' }
    $reason = ''
    foreach ($item in $blocked) { if ($item.id -eq $id) { $reason = $item.reason } }
    if ($state -eq 'pending' -and -not $reason) { $reason = 'blocked' }
    $coupling = Get-Coupling $card $cards
    $frozenHits = Get-FrozenHits $card
    $filesText = (@($card.files) -join ' | ')
    if (-not $filesText) { $filesText = '(none)' }
    $analysisLines += ('- {0} | state={1} | goal: {2}' -f $id, $state, $card.title)
    $frozenText = ' none'
    if ($frozenHits.Count -gt 0) { $frozenText = ($frozenHits -join ',') }
    $analysisLines += ('    coupling={0} cards share files | deps_depth={1} | frozen_instruments={2} | files: {3}' -f
                       $coupling, $depDepth[[string]$card.id], $frozenText, $filesText)
    if ($state -eq 'pending') { $analysisLines += ('    verdict: HOLD ({0})' -f $reason) }
    if ($state -eq 'done') { $analysisLines += '    verdict: already done' }
    if ($state -eq 'inflight') { $analysisLines += '    verdict: in flight' }
    $analysisRecords += [ordered]@{
        id = $id; state = $state; mode = [string]$card.mode; coupling = $coupling
        deps_depth = $depDepth[[string]$card.id]; frozen = @($frozenHits)
        reason = $reason; files = @($card.files)
    }
}

$batchLines = @()
if ($ready.Count -eq 0) {
    $batchLines += ('- DISPATCH 0 agent(s). Every remaining card is blocked by one of:' +
                    ' dependency, write-set coupling with an in-flight card, mode=serial' +
                    ' (same-file double write), mode=user (needs the user), mode=gate' +
                    ' (stage gate), or the parallelism cap.')
    $batchLines += '- Falling back to SERIAL execution is the correct move; do not' +
                   ' raise the cap or ignore coupling to look parallel.'
} else {
    $batchLines += ('- DISPATCH {0} agent(s): {1}' -f $ready.Count,
                    ((@($ready) | ForEach-Object { [string]$_.id }) -join ', '))
    $batchLines += ('- Reason: dependencies satisfied, write-sets pairwise disjoint' +
                    ' (checked file by file), mode=auto, within cap {0}.' -f $maxParallel)
    $batchLines += '- Guardrail: each agent gets ONLY its write-set whitelist, and may' +
                   ' NOT spawn further agents (enforced by guard-pretool.ps1).'
    foreach ($card in $ready) {
        $files = (@($card.files) -join ' | ')
        if (-not $files) { $files = '(none)' }
        $batchLines += ('    {0}: {1} -> {2}' -f $card.id, $card.title, $files)
    }
}

$statePath = Join-Path $stateDir 'last_board.json'
try {
    if (-not (Test-Path -LiteralPath $stateDir)) {
        New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    }
    $snapshot = [ordered]@{
        generated_at = (Get-Date).ToString('s')
        max_parallel = $maxParallel
        done = [int]$done.Count
        total = [int]$total
        inflight = @($inflightCards | ForEach-Object { [string]$_.id })
        dispatch_now = @($ready | ForEach-Object { [string]$_.id })
        cards = $analysisRecords
    }
    [System.IO.File]::WriteAllText($statePath,
        ($snapshot | ConvertTo-Json -Depth 6), $utf8)
} catch { }

$readyLines = @()
if ($ready.Count -eq 0) {
    $readyLines += '(none: no card is both dependency-ready and write-set-disjoint' +
                   ' within the parallelism cap -- fall back to serial)'
} else {
    foreach ($card in $ready) {
        $taskName = ([string]$card.id).ToLowerInvariant() -replace '[^a-z0-9]+', '_'
        $files = (@($card.files) | ForEach-Object { $_ }) -join ' | '
        if (-not $files) { $files = '(none)' }
        $readyLines += ('- {0} | phase {1} | {2}' -f $card.id, $card.phase, $card.title)
        $readyLines += ('    - spawn_agent task_name={0}' -f $taskName)
        $readyLines += ('    - write-set whitelist (touch ONLY these): {0}' -f $files)
        $readyLines += ('    - done => run the card acceptance command, then -Mark {0}' -f $card.id)
    }
}

$inflightLines = @()
if ($inflightCards.Count -eq 0) {
    $inflightLines += '(none)'
} else {
    foreach ($card in $inflightCards) {
        $inflightLines += ('- {0} | {1}' -f $card.id, $card.title)
    }
}

$blockedLines = @()
if ($blocked.Count -eq 0) {
    $blockedLines += '(none)'
} else {
    foreach ($item in $blocked) {
        $blockedLines += ('- {0} | {1}' -f $item.id, $item.reason)
    }
}

$template = Get-Text 'dispatch-board.md'
if (-not $template) { exit 0 }
$board = $template
$board = $board.Replace('{DONE}', [string]$done.Count)
$board = $board.Replace('{TOTAL}', [string]$total)
$board = $board.Replace('{INFLIGHT_N}', [string]$inflightCards.Count)
$board = $board.Replace('{MAX}', [string]$maxParallel)
$board = $board.Replace('{READY_N}', [string]$ready.Count)
$board = $board.Replace('{READY}', ($readyLines -join "`n"))
$board = $board.Replace('{INFLIGHT}', ($inflightLines -join "`n"))
$board = $board.Replace('{BLOCKED}', ($blockedLines -join "`n"))
$board = $board.Replace('{ANALYSIS}', ($analysisLines -join "`n"))
$board = $board.Replace('{BATCH}', ($batchLines -join "`n"))
$board = $board.Trim()

if ($Status) {
    Write-Output $board
    exit 0
}

if ($DryRun) {
    Write-Output $board
    exit 0
}

if ($eventName -eq 'SubagentStart') { exit 0 }

$payload = [ordered]@{
    hookSpecificOutput = [ordered]@{
        hookEventName     = $eventName
        additionalContext = $board
    }
}
$json = $payload | ConvertTo-Json -Depth 5 -Compress
$outStream = [Console]::OpenStandardOutput()
$writer = New-Object System.IO.StreamWriter($outStream, $utf8)
$writer.Write($json)
$writer.Flush()
exit 0
