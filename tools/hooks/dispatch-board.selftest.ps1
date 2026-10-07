# Hermetic self-test for dispatch-board.ps1 (offline; temp dirs only).
#
# Verifies:
#   1. the hook script is pure ASCII (PowerShell 5.1 reads BOM-less UTF-8 as ANSI);
#   2. the board text is produced (header + progress line);
#   3. the DAG rules bite: dependency gating, write-set conflict, parallelism
#      cap, and serial / user / gate modes are never offered;
#   4. -Claim / -Mark / -Unclaim round-trip the state markers.
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File dispatch-board.selftest.ps1

$ErrorActionPreference = 'Continue'
$utf8 = New-Object System.Text.UTF8Encoding($false)

$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$hook = Join-Path $root 'dispatch-board.ps1'

$script:Passed = 0
$script:Failed = 0

function Assert-True([string]$name, $condition, [string]$detail) {
    if ($condition) {
        $script:Passed = $script:Passed + 1
        Write-Host ("  ok   " + $name) -ForegroundColor Green
    } else {
        $script:Failed = $script:Failed + 1
        Write-Host ("  FAIL " + $name + " :: " + $detail) -ForegroundColor Red
    }
}

function Write-Utf8([string]$path, [string]$text) {
    $dir = Split-Path -Parent $path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    [System.IO.File]::WriteAllText($path, $text, $utf8)
}

function Invoke-Board([string[]]$extra) {
    $argList = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', $hook) + $extra
    $out = & powershell.exe @argList 2>&1
    return @{ Text = ([string]::Join("`n", @($out | ForEach-Object { $_.ToString() })))
              ExitCode = $LASTEXITCODE }
}

# The plan dir name is non-ASCII; build it from code points (ASCII-only source).
$planDir = ([char[]]@(0x6267, 0x884C, 0x6587, 0x6863) -join '') + 'v1.5'

function New-Sandbox([string]$graphJson) {
    $ws = Join-Path ([System.IO.Path]::GetTempPath()) ('bd_dispatch_' + [guid]::NewGuid().ToString('N'))
    $dir = Join-Path $ws $planDir
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Write-Utf8 (Join-Path $dir 'dispatch_graph.json') $graphJson
    return $ws
}

Write-Host 'dispatch-board selftest'

# --- 1. ASCII-only hook source --------------------------------------------- #
$bytes = [System.IO.File]::ReadAllBytes($hook)
$nonAscii = 0
foreach ($b in $bytes) { if ($b -gt 127) { $nonAscii = $nonAscii + 1 } }
Assert-True 'hook script is ASCII-only (PS 5.1 safe)' ($nonAscii -eq 0) ("non-ascii bytes: " + $nonAscii)

# --- 2. board text is produced -------------------------------------------- #
$cards = @(
    [ordered]@{ id = 'A-1'; phase = 0; title = 'alpha';  mode = 'auto';   depends_on = @(); files = @('src/a.py') },
    [ordered]@{ id = 'A-2'; phase = 0; title = 'beta';   mode = 'auto';   depends_on = @(); files = @('src/b.py') },
    [ordered]@{ id = 'A-3'; phase = 0; title = 'gamma';  mode = 'auto';   depends_on = @(); files = @('src/c.py') },
    [ordered]@{ id = 'B-1'; phase = 1; title = 'delta';  mode = 'auto';   depends_on = @('A-1'); files = @('src/d.py') },
    [ordered]@{ id = 'S-1'; phase = 1; title = 'serial'; mode = 'serial'; depends_on = @(); files = @('src/e.py') },
    [ordered]@{ id = 'U-1'; phase = 1; title = 'user';   mode = 'user';   depends_on = @(); files = @('src/f.py') },
    [ordered]@{ id = 'G-1'; phase = 2; title = 'gate';   mode = 'gate';   depends_on = @(); files = @('src/g.py') },
    [ordered]@{ id = 'C-1'; phase = 0; title = 'clash';  mode = 'auto';   depends_on = @(); files = @('src/a.py') }
)
$graphJson = ([ordered]@{ max_parallel = 2; cards = $cards } | ConvertTo-Json -Depth 8)
$ws = New-Sandbox $graphJson
$r = Invoke-Board @('-DryRun', '-Workspace', $ws)
$text = $r.Text
Assert-True 'dry-run exits 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode)
Assert-True 'board header present' ($text.Contains('dispatch-board')) $text
Assert-True 'progress line present' ($text.Contains('done 0/8')) $text

# --- 3. DAG rules ---------------------------------------------------------- #
$offered = @()
foreach ($id in @('A-1', 'A-2', 'A-3', 'C-1')) {
    if ($text -match ('- ' + [regex]::Escape($id) + ' \| phase')) { $offered += $id }
}
$offeredText = ($offered -join ',')
Assert-True 'cap respected (max 2 offered from phase 0)' ($offered.Count -le 2) $offeredText
Assert-True 'write-set clash C-1 not offered' (-not ($offered -contains 'C-1')) $offeredText
Assert-True 'dependency-gated B-1 not offered' (-not ($text -match '- B-1 \| phase')) $text
Assert-True 'serial S-1 blocked with mode:serial' ($text.Contains('S-1 | mode:serial')) $text
Assert-True 'user U-1 blocked with mode:user' ($text.Contains('U-1 | mode:user')) $text
Assert-True 'gate G-1 blocked with mode:gate' ($text.Contains('G-1 | mode:gate')) $text

# --- 4. state round-trip --------------------------------------------------- #
$r = Invoke-Board @('-Claim', 'A-1', '-Workspace', $ws)
Assert-True 'claim exits 0' ($r.ExitCode -eq 0) $r.Text
$r = Invoke-Board @('-DryRun', '-Workspace', $ws)
$inflightShown = ($r.Text -match '- A-1 \|')
Assert-True 'claimed card shows as in-flight' $inflightShown $r.Text
$r = Invoke-Board @('-Mark', 'A-1', '-Workspace', $ws)
$r = Invoke-Board @('-DryRun', '-Workspace', $ws)
# After A-1 is done, B-1's dependency is satisfied: whatever blocks it now, it
# must no longer be reported as "depends:A-1".
Assert-True 'marking A-1 clears the depends gate on B-1' `
            (-not ($r.Text.Contains('B-1 | depends:A-1'))) $r.Text
$r = Invoke-Board @('-Unclaim', 'B-1', '-Workspace', $ws)
Assert-True 'unclaim exits 0' ($r.ExitCode -eq 0) $r.Text

# --- 5. conflict path (cap lifted, so the reason code is the conflict one) -- #
$graphJson2 = ([ordered]@{ max_parallel = 8; cards = $cards } | ConvertTo-Json -Depth 8)
$ws2 = New-Sandbox $graphJson2
$r = Invoke-Board @('-DryRun', '-Workspace', $ws2)
Assert-True 'conflict reason surfaces when cap is lifted' ($r.Text.Contains('C-1 | conflict:A-1')) $r.Text
Assert-True 'dependency reason surfaces when cap is lifted' ($r.Text.Contains('B-1 | depends:A-1')) $r.Text
# --- 6. pre-dispatch analysis (goal x coupling) + batch decision ----------- #
Assert-True 'analysis lists a coupling figure per card' ($r.Text.Contains('coupling=1 cards share files')) $r.Text
Assert-True 'analysis lists dependency depth' ($r.Text.Contains('deps_depth=1')) $r.Text
Assert-True 'analysis marks the frozen-instrument column' ($r.Text.Contains('frozen_instruments=')) $r.Text
Assert-True 'analysis gives a HOLD verdict for the clashing card' ($r.Text.Contains('C-1') -and $r.Text.Contains('verdict: HOLD')) $r.Text
Assert-True 'batch decision names how many agents to dispatch' ($r.Text.Contains('DISPATCH 3 agent(s)')) $r.Text
Assert-True 'batch decision explains the guardrail' ($r.Text.Contains('write-set whitelist')) $r.Text
$snapshotPath = Join-Path $ws2 'docs\evidence\_v15_dispatch\last_board.json'
Assert-True 'machine-readable snapshot is written' (Test-Path -LiteralPath $snapshotPath) $snapshotPath
if (Test-Path -LiteralPath $snapshotPath) {
    $snap = ([System.IO.File]::ReadAllText($snapshotPath,
             [System.Text.Encoding]::UTF8) | ConvertFrom-Json)
    Assert-True 'snapshot records the dispatch set' (@($snap.dispatch_now).Count -eq 3) ($snap.dispatch_now -join ',')
    $clash = $snap.cards | Where-Object { $_.id -eq 'C-1' }
    Assert-True 'snapshot records the clash reason' ($clash.reason -like 'conflict:*') $clash.reason
}
Remove-Item -LiteralPath $ws2 -Recurse -Force -ErrorAction SilentlyContinue

# --- summary --------------------------------------------------------------- #
Remove-Item -LiteralPath $ws -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ''
Write-Host ("passed " + $script:Passed + " / failed " + $script:Failed)
if ($script:Failed -gt 0) { exit 1 }
exit 0
