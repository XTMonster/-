# BlockDirector test entry point.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 parses BOM-less
# UTF-8 scripts as ANSI, so non-ASCII characters can break parsing.
#
# NOTE: ErrorActionPreference stays 'Continue'. Blender writes our log lines to
# stderr, and with 'Stop' PowerShell turns any native stderr output into a
# terminating NativeCommandError. We check $LASTEXITCODE explicitly instead.
#
# v1.4 F1/US-16: when Blender cannot be found we FAIL with a non-zero exit code
# and print INCOMPLETE -- never a silent "all green" with the Blender checks
# skipped. The Blender side is driven by an explicit manifest ($checks) and we
# assert BOTH directions: every listed file exists, and every
# tools/blender_tests/test_*.py on disk is listed.
#
# Usage: powershell -ExecutionPolicy Bypass -File tools/run_tests.ps1

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --------------------------------------------------------------------------- #
# UTF-8 everywhere BEFORE any native command runs.
#
# Windows PowerShell 5.1 decodes a native command's stdout with the console code
# page (cp936 on this machine). Blender and Python both write UTF-8, so every
# non-ASCII character in a probe's output was decoded wrongly - and the damage is
# not just cosmetic: BD_TEST_RESULT carries Chinese inside its JSON (rule names,
# conflict messages), and the mis-decoded bytes make the payload invalid JSON.
# ConvertFrom-Json then throws, the probe's `passed` names are never collected,
# and the RK rules hanging off that probe silently become not_measured
# (measured: RK-6 and RK-8 both fell to not_measured for exactly this reason,
# while the same markers parsed fine when the probe was run by hand).
#
# Setting the console + pipeline encodings fixes it at the single place that
# spawns the children, so no probe has to know about it.
# --------------------------------------------------------------------------- #
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONIOENCODING = 'utf-8'

function Fail([string]$message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

function Invoke-BlenderScript([string]$blender, [string]$script, [string[]]$extra) {
    $blenderArgs = @('--background', '--factory-startup', '--python', $script)
    if ($extra) { $blenderArgs += '--'; $blenderArgs += $extra }
    return & $blender @blenderArgs 2>&1
}

function Assert-Marker([object]$output, [string]$pattern, [string]$label) {
    $line = $output | Select-String -Pattern $pattern | Select-Object -First 1
    if (-not $line) {
        Write-Host "  FAILED: no $pattern marker ($label)" -ForegroundColor Red
        $output | Select-Object -Last 20
        exit 1
    }
    return $line.Line
}

# Reassemble the BD_TEST_RESULT JSON payload from the WHOLE probe output.
#
# Why not ConvertFrom-Json on the single line Select-String matched: the marker is
# a multi-KB one-liner, and Blender flushes stdout and stderr in separate chunks
# (which get interlaced when the machine is busy with another long run). More than
# one of those interlacings shows up as a line that does not parse, and then the
# probe's `passed` names are lost - which quietly turns the RKs hanging off that
# probe into not_measured (measured: RK-6 and RK-8 both fell from measured to
# not_measured that way). Brace matching after the marker survives both splitting
# and interleaving.
function Get-MarkerPayload([object]$output, [string]$marker) {
    $text = [string]::Join("`n", @($output | ForEach-Object { $_.ToString() }))
    $index = $text.IndexOf($marker)
    if ($index -lt 0) { return $null }
    $rest = $text.Substring($index + $marker.Length)
    $start = $rest.IndexOf('{')
    if ($start -lt 0) { return $null }
    $depth = 0
    $inString = $false
    $escape = $false
    for ($i = $start; $i -lt $rest.Length; $i++) {
        $ch = $rest[$i]
        if ($inString) {
            if ($escape) { $escape = $false }
            elseif ($ch -eq '\') { $escape = $true }
            elseif ($ch -eq '"') { $inString = $false }
            continue
        }
        if ($ch -eq '"') { $inString = $true; continue }
        if ($ch -eq '{') { $depth = $depth + 1 }
        elseif ($ch -eq '}') {
            $depth = $depth - 1
            if ($depth -eq 0) { return $rest.Substring($start, $i - $start + 1) }
        }
    }
    return $null
}

# --------------------------------------------------------------------------- #
# The Blender-side manifest. One entry per `--python` script we execute.
# Every tools/blender_tests/test_*.py MUST appear here (asserted below).
# --------------------------------------------------------------------------- #
$checks = @(
    @{ Script = 'tools\blender_tests\test_operator_end_to_end.py'; Marker = 'BD_TEST_RESULT'; Label = 'operator-e2e' },
    @{ Script = 'tools\blender_tests\test_character_geometry.py';  Marker = 'BD_TEST_RESULT'; Label = 'character-geometry' },
    @{ Script = 'tools\blender_tests\test_scene_contract.py';      Marker = 'BD_TEST_RESULT'; Label = 'scene-contract' },
    @{ Script = 'tools\blender_tests\test_label_toggles.py';       Marker = 'BD_TEST_RESULT'; Label = 'label-toggles' },
    @{ Script = 'tools\blender_tests\test_label_layout.py';        Marker = 'BD_TEST_RESULT'; Label = 'label-layout' },
    @{ Script = 'tools\blender_tests\test_composition_gate.py';    Marker = 'BD_TEST_RESULT'; Label = 'composition-gate' },
    @{ Script = 'tools\blender_tests\test_phase1_scene.py';      Marker = 'BD_TEST_RESULT'; Label = 'phase1' },
    @{ Script = 'tools\blender_tests\test_phase2_motion.py';     Marker = 'BD_TEST_RESULT'; Label = 'phase2' },
    @{ Script = 'tools\blender_tests\test_phase3_framing.py';    Marker = 'BD_TEST_RESULT'; Label = 'phase3' },
    @{ Script = 'tools\blender_tests\test_phase3_audit.py';      Marker = 'BD_TEST_RESULT'; Label = 'phase3-audit' },
    @{ Script = 'tools\blender_tests\test_phase4_build.py';      Marker = 'BD_TEST_RESULT'; Label = 'phase4' },
    @{ Script = 'tools\blender_tests\test_phase4_tools.py';      Marker = 'BD_TEST_RESULT'; Label = 'phase4-tools' },
    @{ Script = 'tools\blender_tests\test_phase4_repair.py';     Marker = 'BD_TEST_RESULT'; Label = 'phase4-repair' },
    @{ Script = 'tools\blender_tests\test_phase5_checkpoint.py'; Marker = 'BD_TEST_RESULT'; Label = 'phase5-checkpoint' },
    @{ Script = 'tools\blender_tests\test_phase6_delivery.py';   Marker = 'BD_TEST_RESULT'; Label = 'phase6' },
    @{ Script = 'tools\blender_tests\test_layer2_project.py';    Marker = 'BD_TEST_RESULT'; Label = 'layer2-project' },
    @{ Script = 'tools\blender_tests\test_replay.py';            Marker = 'BD_TEST_RESULT'; Label = 'replay' },
    @{ Script = 'tools\blender_tests\test_golden.py';            Marker = 'BD_TEST_RESULT'; Label = 'golden' },
    @{ Script = 'tools\blender_tests\test_scene_sync.py';        Marker = 'BD_TEST_RESULT'; Label = 'scene-sync' },
    @{ Script = 'tools\blender_tests\test_ui_panels.py';         Marker = 'BD_TEST_RESULT'; Label = 'ui-panels' },
    @{ Script = 'tools\blender_tests\test_overlay_path.py';      Marker = 'BD_TEST_RESULT'; Label = 'overlay-path' },
    @{ Script = 'tools\blender_tests\test_delivery_extras.py';   Marker = 'BD_TEST_RESULT'; Label = 'delivery-extras' },
    @{ Script = 'tools\blender_tests\test_tools_extended.py';    Marker = 'BD_TEST_RESULT'; Label = 'tools-extended' },
    @{ Script = 'tools\blender_tests\test_cast_panel.py';        Marker = 'BD_TEST_RESULT'; Label = 'cast-panel' },
    @{ Script = 'tools\blender_tests\test_llm_trace.py';         Marker = 'BD_TEST_RESULT'; Label = 'llm-trace' },
    @{ Script = 'tools\blender_tests\test_camera_motion.py';     Marker = 'BD_TEST_RESULT'; Label = 'camera-motion' },
    @{ Script = 'tools\blender_tests\test_crowd_vfx.py';         Marker = 'BD_TEST_RESULT'; Label = 'crowd-vfx' }
)

# +4 = spec/golden drift, pytest, the contract smoke test, the headless run.
$total = $checks.Count + 4

Write-Host ("[1/{0}] Check spec and golden-fixture consistency" -f $total) -ForegroundColor Cyan
python tools/gen_specs.py --check
if ($LASTEXITCODE -ne 0) { Fail '  FAILED: spec/code drift' }
python tools/gen_golden.py --check
if ($LASTEXITCODE -ne 0) { Fail '  FAILED: golden fixture drift' }

Write-Host ("[2/{0}] Run pytest suite" -f $total) -ForegroundColor Cyan
python -m pytest
if ($LASTEXITCODE -ne 0) { Fail '  FAILED: pytest' }

# --------------------------------------------------------------------------- #
# Locate Blender. A non-empty but missing $env:BLENDER_EXE counts as "not
# found" (US-16: pointing the variable at a dead path must NOT fall through).
# --------------------------------------------------------------------------- #
$blender = $env:BLENDER_EXE
if ($blender -and -not (Test-Path $blender)) {
    Write-Host "  BLENDER_EXE points at a missing path: $blender" -ForegroundColor Yellow
    $blender = $null
}
if (-not $blender) {
    $candidates = @(
        'D:\Blender 5.2\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
    )
    $blender = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $blender) {
    Write-Host 'INCOMPLETE: blender.exe not found. Set BLENDER_EXE to the full path.' -ForegroundColor Red
    Write-Host 'INCOMPLETE: the Blender checks were NOT executed; this run is not green.' -ForegroundColor Red
    exit 1
}

# --------------------------------------------------------------------------- #
# Manifest / execution-set assertions (F1, both directions).
# --------------------------------------------------------------------------- #
foreach ($check in $checks) {
    if (-not (Test-Path (Join-Path $root $check.Script))) {
        Fail ("  FAILED: manifest lists a missing file: " + $check.Script)
    }
}
$listed = @{}
foreach ($check in $checks) { $listed[$check.Script.ToLower()] = $true }
$onDisk = Get-ChildItem (Join-Path $root 'tools\blender_tests') -Filter 'test_*.py'
foreach ($file in $onDisk) {
    $rel = 'tools\blender_tests\' + $file.Name
    if (-not $listed.ContainsKey($rel.ToLower())) {
        Fail ("  FAILED: " + $rel + " is on disk but not registered in the manifest")
    }
}

Write-Host ("[3/{0}] Smoke test contracts inside Blender Python" -f $total) -ForegroundColor Cyan
$smoke = @(
    'import sys',
    "sys.path.insert(0, r'$root')",
    'import block_director',
    'from block_director.contracts import AppConfig',
    'from block_director.utils.blender_compat import startup_report',
    'startup_report()',
    "print('SMOKE_OK', block_director.__version__, sys.version.split()[0], len(AppConfig().errors()))"
) -join '; '
$smokeOut = & $blender --background --factory-startup --python-expr $smoke 2>&1
$smokeLine = $smokeOut | Select-String -Pattern 'SMOKE_OK' | Select-Object -First 1
if (-not $smokeLine) {
    Write-Host '  FAILED: contracts did not import inside Blender' -ForegroundColor Red
    $smokeOut | Select-Object -Last 15
    exit 1
}
Write-Host ('  ' + $smokeLine.Line) -ForegroundColor Green

# The LONG script, not the default: SS4.4 step 1 names
# `--script fixtures/script_long_61.md` and P13's acceptance is "61 shots finish
# without degrading".  Measured 2026-10-03: this step was running WITHOUT --script,
# i.e. the 2-shot default - so the chain never exercised the long path end to end
# (the 61-shot plan SHAPE was covered by pytest, but not the build, the label
# baking, the export or the budget ceiling).  The long run takes ~159 s offline
# (64 shots, DONE) which is worth it: it is the only place the ceiling formula and
# the cross-shot machinery meet real execution.
Write-Host ("[4/{0}] Run the add-on headless (plan -> scene -> delivery, one command)" -f $total) -ForegroundColor Cyan
$out = Join-Path $env:TEMP ("bd_run_" + (Get-Date -Format 'HHmmss'))
# `--preset fhd16x9` is part of section 4.4 step 1's command and the doc says it is
# MANDATORY (RK-4's eye clusters and RK-14's head sphere scale with resolution; the
# default preset is hd16x9 = 1280x720).  Measured: the committed
# docs/evidence/offline_run1/export/shots.json is 1920x1080, i.e. the recorded run
# used fhd16x9 - while this chain step was running at the default.  At fhd16x9 the
# long baseline takes 293 s instead of 159 s and still finishes DONE with 64 shots.
$headlessOut = Invoke-BlenderScript $blender (Join-Path $root 'tools\run_headless.py') @('--offline', '--script', 'fixtures\script_long_61.md', '--build', '--preset', 'fhd16x9', '--out', $out, '--save', (Join-Path $out 'project'), '--export')
$marker = Assert-Marker $headlessOut 'BLOCKDIRECTOR_RESULT' 'headless'
if ($marker -notmatch '"success": true') { Fail ('  FAILED: ' + $marker) }
if ($marker -notmatch '"built": true') { Fail '  FAILED: the run did not build a scene' }
if ($marker -notmatch '"state": "DONE"') { Fail '  FAILED: the long baseline did not finish (state != DONE)' }
Write-Host ('  ' + ($marker -replace 'BLOCKDIRECTOR_RESULT ', '')) -ForegroundColor Green
# P13 / SS2.4: declared N -> produced N, and the budget ceiling is
# `ceiling_effective = max(200, shots * 8 + 40)` (528 for 61 shots).  Read the
# payload rather than regexing the numbers out of the single line.
$headlessPayload = Get-MarkerPayload $headlessOut 'BLOCKDIRECTOR_RESULT'
if (-not $headlessPayload) { Fail '  FAILED: could not parse BLOCKDIRECTOR_RESULT' }
$headlessJson = $null
try { $headlessJson = $headlessPayload | ConvertFrom-Json } catch { $headlessJson = $null }
if (-not $headlessJson) { Fail '  FAILED: BLOCKDIRECTOR_RESULT is not valid JSON' }
$longShots = [int]$headlessJson.shots
if ($longShots -lt 61) { Fail ('  FAILED: the long baseline produced only ' + $longShots + ' shots (< 61)') }
$ceiling = [Math]::Max(200, $longShots * 8 + 40)
$longCalls = [int]$headlessJson.llm_calls
if ($longCalls -gt $ceiling) {
    Fail ('  FAILED: llm_calls ' + $longCalls + ' > ceiling_effective ' + $ceiling)
}
Write-Host ('  long baseline: ' + $longShots + ' shots, ' + $longCalls +
            ' llm calls (ceiling ' + $ceiling + ')') -ForegroundColor DarkGray
# The preset is only real if it reached the delivery config - assert the artifact.
$shotsPath = Join-Path $out 'export\shots.json'
if (-not (Test-Path $shotsPath)) { Fail '  FAILED: step 1 wrote no export/shots.json' }
$shotsJson = ([System.IO.File]::ReadAllText($shotsPath,
              [System.Text.Encoding]::UTF8) | ConvertFrom-Json)
$gotResolution = ($shotsJson.resolution -join 'x')
if ($gotResolution -ne '1920x1080') {
    Fail ('  FAILED: step 1 must run at --preset fhd16x9 (1920x1080), got ' + $gotResolution)
}
Write-Host ('  delivery resolution: ' + $gotResolution + ' (--preset fhd16x9)') -ForegroundColor DarkGray

# Section 4.4 STEP 3: rebuild the scene from STEP 1's saved project, with no LLM
# call at all.  Measured 2026-10-03: `tools/rebuild_project.py` was called by
# NOTHING - not by the chain and not by any test - while P9.4's acceptance column
# says "sections 4.4 step 1 and step 3 must be executable as written".  Running it
# here (against the temp project the step above just saved) keeps that true; the
# rebuild's own nested export lands under TEMP, so the repo is untouched.
$rebuildOut = Invoke-BlenderScript $blender (Join-Path $root 'tools\rebuild_project.py') @('--project', (Join-Path $out 'project'), '--export')
$rebuildMarker = Assert-Marker $rebuildOut 'BLOCKDIRECTOR_REBUILD' 'rebuild'
if ($rebuildMarker -notmatch '"ok": true') { Fail ('  FAILED: ' + $rebuildMarker) }
$rebuildPayload = Get-MarkerPayload $rebuildOut 'BLOCKDIRECTOR_REBUILD'
$rebuildJson = $null
try { $rebuildJson = $rebuildPayload | ConvertFrom-Json } catch { $rebuildJson = $null }
if (-not $rebuildJson) { Fail '  FAILED: BLOCKDIRECTOR_REBUILD is not valid JSON' }
# The rebuilt scene must reproduce the step-1 plan exactly: same shots, same frames,
# and an export that is ok.  A rebuild that quietly drops shots would still print ok.
if ([int]$rebuildJson.shots -ne $longShots) {
    Fail ('  FAILED: rebuild produced ' + [int]$rebuildJson.shots + ' shots, step 1 produced ' + $longShots)
}
if ([int]$rebuildJson.total_frames -ne [int]$headlessJson.total_frames) {
    Fail ('  FAILED: rebuild total_frames ' + [int]$rebuildJson.total_frames +
          ' != step 1 ' + [int]$headlessJson.total_frames)
}
# `--export` was asked for, so the export block must say so (a rebuild that skips
# the export would otherwise pass on `ok: true` alone).
if (-not $rebuildJson.export) {
    Fail '  FAILED: rebuild --export produced no export block'
}
if (-not $rebuildJson.export.ok) {
    Fail ('  FAILED: rebuild export not ok: ' + $rebuildJson.export.reason)
}
Write-Host ('  rebuild (no LLM): ' + [int]$rebuildJson.shots + ' shots / ' +
            [int]$rebuildJson.total_frames + ' frames reproduced') -ForegroundColor DarkGray
$exportMarker = Assert-Marker $headlessOut 'BLOCKDIRECTOR_EXPORT' 'delivery'
if ($exportMarker -notmatch '"ok": true') { Fail ('  FAILED: ' + $exportMarker) }
if ($exportMarker -notmatch '"aborted": false') { Fail '  FAILED: export aborted (render audit)' }
Write-Host ('  ' + ($exportMarker -replace 'BLOCKDIRECTOR_EXPORT ', '')) -ForegroundColor Green

# --------------------------------------------------------------------------- #
# Blender-side probes from the manifest.
# --------------------------------------------------------------------------- #
$index = 5
$probePassed = @()
$probeParseFailures = @()
foreach ($check in $checks) {
    Write-Host ("[{0}/{1}] Blender probe: {2}" -f $index, $total, $check.Label) -ForegroundColor Cyan
    $probeOut = Invoke-BlenderScript $blender (Join-Path $root $check.Script) $null
    $probeLine = Assert-Marker $probeOut $check.Marker $check.Label
    # Prefer the reassembled payload for the "any failures?" verdict (the single
    # line can be cut by stream interleaving); fall back to the original line
    # regex only when no payload can be recovered. The negative path still fires.
    $payloadOk = $false
    $markerPayload = Get-MarkerPayload $probeOut $check.Marker
    if ($markerPayload) {
        try {
            $parsed = $markerPayload | ConvertFrom-Json
            $payloadOk = $true
        } catch {
            $payloadOk = $false
        }
    }
    if ($payloadOk) {
        if (@($parsed.failed).Count -ne 0) {
            Fail ('  FAILED: ' + ($parsed.failed -join ', '))
        }
    } elseif ($probeLine -notmatch '"failed": \[\]') {
        Fail ('  FAILED: ' + $probeLine)
    }
    Write-Host ('  OK: ' + $check.Label) -ForegroundColor Green
    # Collect the probe's self-reported "passed" names so the RK aggregator can
    # derive which RKs were actually measured.
    if ($payloadOk) {
        foreach ($name in $parsed.passed) { $probePassed += $name }
    } else {
        Write-Host '  WARN: could not parse the probe result for the RK aggregate' -ForegroundColor Yellow
        # Leave evidence on disk: a WARN alone hides the fact that the RK derived
        # from this probe is now not_measured.
        $dumpPath = Join-Path $root ('work\probe_parse_fail-' + $check.Label + '.txt')
        ($probeLine + "`n") | Out-File -Encoding utf8 $dumpPath
        $probeParseFailures += $check.Label
    }
    $index = $index + 1
}

# --------------------------------------------------------------------------- #
# RK results hook (v1.4 SS B.2 L5): write docs/evidence/<run-id>/rks.json plus a
# config fingerprint so the evidence directory is self-describing (S13).
# --------------------------------------------------------------------------- #
$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
$evidenceDir = Join-Path $root ('docs\evidence\' + $runId)
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
# Both helpers write their own file (never Set-Content: PowerShell 5.1 would
# prepend a BOM and break json.loads downstream).
python tools/evidence_fingerprint.py --out (Join-Path $evidenceDir 'config.fingerprint.json') | Out-Null
# The pytest-side RKs are covered by named cases (RK-7 dialogue three-way,
# RK-11 frame identity, RK-12 replay, RK-18 budget gate, RK-19 screen
# direction); their check names are the RK ids themselves.
#
# RK-13 is measured from the held-out oracle: holdout_score exits 0 (all
# metrics on the line) or 1 (measured but below the line). Exit 2 / INCOMPLETE
# means the oracle is missing, and then RK-13 stays not_measured (never a pass).
$rk13Checks = @()
$rk13Failed = @()
# NOTE (2026-10-02): this file's name says which tool wrote it. holdout_score.py
# emits Q1..Q7 and nothing else, so writing it under `knowledge_quality.json` (the
# name AGENTS.md gives to quality.py's report) made every evidence directory look
# like the knowledge stack had been judged when Q0 and E3 had not been measured at
# all. See the knowledge-stack block below.
python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json (Join-Path $evidenceDir 'holdout_quality.json') > $null 2>&1
$rk13Exit = $LASTEXITCODE
if (($rk13Exit -eq 0) -or ($rk13Exit -eq 1)) {
    $rk13Checks += 'RK-13'
    if ($rk13Exit -eq 1) { $rk13Failed += 'RK-13' }
    Write-Host ('  RK-13 measured from the held-out (exit ' + $rk13Exit + ')') -ForegroundColor Green
} else {
    Write-Host '  RK-13 not measured: no usable held-out oracle' -ForegroundColor Yellow
}
# The held-out coverage gates (v1.4 SS 4.1b, gates 1-8 as of R54) decide whether
# the RK-13 numbers above are usable at all: "if a gate is not passed, every
# RK-13 metric is void". Run them into the same evidence directory, and treat a
# non-zero exit as RK-13 failing (this mirrors the holdout_score exit handling
# above; it never turns the suite itself red, it attributes the failure).
# `--out` is written by Python on purpose: PowerShell 5.1's `>` emits UTF-16,
# which breaks the downstream json.loads.
# `--assertable` is gate 4's cap (user ruling 2026-10-01): each type must supply
# `min(30, assertable pairs for that type)`. The JSON is a property of
# (index, vocabulary) - produced by `holdout_pool --assertable-out` and committed -
# so using it here is not the oracle grading itself.
# `--reviewer-classes human,llm-panel` is gate 7's recorded scope: the user
# delegated Q5/Q7/E3 to the DeepSeek + GLM panel ("I have no experience") and
# then authorised the machine pass outright. The review records themselves are
# NOT rewritten - `holdout_review_llm.py` still writes `reviewed_by: "llm-panel"`,
# and the report's `reviewed_by_class` says who judged. Leaving the flag off made
# the panel's work invisible to RK-13 while the docs claimed the chain passed it.
# `--exclude-cards` is gate 6's denominator, and the reason is in the doc: 4.1b says
# "every CATALOGUED card (L1/L2) must derive >= 1 entry". Cards outside L1/L2
# (photo chemistry / drawing technique / electrical work / manuscript-format rules -
# criterion and per-card reasons in `tools/kb_fetch/card_scope_audit.py` and
# `knowledge/card_scope.json`) are not catalogued cards, so they leave the
# denominator. The gate's own detail still reports `cards_out_of_scope_count`, so
# shrinking the denominator silently is impossible.
python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab fixtures/knowledge_holdout.vocab.json --cards fixtures/knowledge_holdout.cards.json --assertable fixtures/knowledge_holdout.assertable.json --reviewer-classes human,llm-panel --exclude-cards knowledge/card_scope.json --out (Join-Path $evidenceDir 'holdout_gates.json') > $null 2>&1
$gateExit = $LASTEXITCODE
if ($gateExit -eq 0) {
    Write-Host '  held-out coverage gates: all passed' -ForegroundColor Green
} elseif ($rk13Checks.Count -gt 0) {
    if ($rk13Failed -notcontains 'RK-13') { $rk13Failed = @($rk13Failed) + 'RK-13' }
    Write-Host ('  held-out coverage gates exit ' + $gateExit + ' -> RK-13 counts as failed') -ForegroundColor Yellow
} else {
    # No usable oracle: RK-13 stays not_measured - running a gate is not a measurement.
    Write-Host ('  held-out coverage gates exit ' + $gateExit + ' (no usable oracle: RK-13 stays not_measured)') -ForegroundColor Yellow
}
if (-not (Test-Path (Join-Path $evidenceDir 'holdout_gates.json'))) {
    Fail '  FAILED: the held-out gate report was not written'
}
# Provenance gate (user ruling 2026-10-01): every generated knowledge card must come
# from somebody else's work (http/https source_ref). A single `repo://` record means
# the project wrote its own theory - that is a hard fail, and it is attributed to
# RK-13 exactly like the held-out gates above (it never turns the suite red by
# itself, it says WHY the knowledge stack is not passing).
python tools/knowledge/authorship_report.py --json (Join-Path $evidenceDir 'authorship.json') > $null 2>&1
$authorshipExit = $LASTEXITCODE
if (-not (Test-Path (Join-Path $evidenceDir 'authorship.json'))) {
    Fail '  FAILED: the authorship report was not written'
}
if ($authorshipExit -eq 0) {
    Write-Host '  authorship: every generated card comes from an external work' -ForegroundColor Green
} else {
    if ($rk13Failed -notcontains 'RK-13') { $rk13Failed = @($rk13Failed) + 'RK-13' }
    Write-Host ('  authorship gate exit ' + $authorshipExit + ' -> RK-13 counts as failed') -ForegroundColor Yellow
}

# Attestation (2026-10-02): how many of the shipped index's member slots can be
# traced to a surface form of the value in the edge's OWN source cards.  It is a
# DIAGNOSTIC, not a gate: it never fails the chain, and it must not (it measures a
# known weakness, see ACCEPTANCE_STATUS.md SS29 - 21.19% attested on the shipped
# index, which is the same finding the cross-family review panel reports as 92%
# rejections).  It exists so that number is in every evidence directory instead of
# being re-derived by hand.  `extractor.member_grounding` cannot serve this role:
# the prompt only asks for the edge-level quote, so that ledger is a constant
# (measured 8087/8087 `inferred`).
python tools/knowledge/attestation.py --json (Join-Path $evidenceDir 'knowledge_attestation.json') > $null 2>&1
if (-not (Test-Path (Join-Path $evidenceDir 'knowledge_attestation.json'))) {
    Fail '  FAILED: the attestation report was not written'
} else {
# Read it as UTF-8 explicitly: Windows PowerShell 5.1's `Get-Content -Raw` uses the
# ANSI code page when the file has no BOM, so the Chinese `criterion` field turns into
# mojibake and `ConvertFrom-Json` throws (measured 2026-10-02: the chain printed an
# empty diagnostic line while still exiting 0 - a silent hole in a diagnostic).
    $attestPath = Join-Path $evidenceDir 'knowledge_attestation.json'
    $attested = ([System.IO.File]::ReadAllText($attestPath,
                 [System.Text.Encoding]::UTF8) | ConvertFrom-Json)
    Write-Host ('  attestation (diagnostic): ' + $attested.attested_share +
                ' of checkable member slots are named by the edge''s own source cards (' +
                $attested.edges_fully_attested + '/' + $attested.edges + ' edges fully attested)') -ForegroundColor DarkGray
}

# Human spot-check sample (2026-10-03): the evidence table in section 6 names the
# "extraction noise" row's evidence as sample_edges.py --n 30 ->
# docs/evidence/<run-id>/edge_spotcheck.jsonl - a stratified, RENDERED sample of 30
# edges with verdict/reviewer/notes left blank for a human.  Measured: only three
# evidence directories have it (2026-09-30), i.e. every run since then has been
# missing a named deliverable while the chain stayed green.  The chain cannot fill
# the verdicts (that is the human's job) - but it must produce the sheet, and the
# script refuses to pre-fill (verdict is always null; pre-filling would be
# self-confirmation under SS4.1b rule 2).
python tools/knowledge/sample_edges.py --n 30 --out (Join-Path $evidenceDir 'edge_spotcheck.jsonl') > $null 2>&1
if (-not (Test-Path (Join-Path $evidenceDir 'edge_spotcheck.jsonl'))) {
    Fail '  FAILED: the SS6 edge spot-check sheet was not written'
} else {
    $spotPath = Join-Path $evidenceDir 'edge_spotcheck.jsonl'
    $spot = ([System.IO.File]::ReadAllText($spotPath,
             [System.Text.Encoding]::UTF8) -split "`n" | Where-Object { $_.Trim() })
    Write-Host ('  edge spot-check sheet (for a human; verdicts blank): ' +
                $spot.Count + ' edges') -ForegroundColor DarkGray
}

# A/B triple (2026-10-03): SS2.3d T2 / P14-5 asks for one run of the
# hypergraph-vs-binary-triple comparison, landed as
# `docs/evidence/<run-id>/ab_triple.json`.  The TOOL has been in the repo since the
# P14 layout, but the chain never called it - so the deliverable simply did not
# exist in any evidence directory, and nobody could tell whether the hypergraph was
# buying anything.  Measured on the shipped index: Q2 1.0000 (hypergraph) vs 0.6315
# (triples), delta_Q2 +0.3685; Q6b 1.0 vs 1.0 (the tool says why: the delta only
# shows up when the injection budget binds, so 0 there is not evidence of anything).
# It stays a DIAGNOSTIC - no pass line - but the artifact must be written: a
# deliverable that can silently go missing is the same hole as a gate that can.
python tools/ab_triple_baseline.py --out (Join-Path $evidenceDir 'ab_triple.json') > $null 2>&1
if (-not (Test-Path (Join-Path $evidenceDir 'ab_triple.json'))) {
    Fail '  FAILED: the A/B triple comparison was not written (SS2.3d T2 / P14-5)'
} else {
    $abPath = Join-Path $evidenceDir 'ab_triple.json'
    $ab = ([System.IO.File]::ReadAllText($abPath,
           [System.Text.Encoding]::UTF8) | ConvertFrom-Json)
    Write-Host ('  a/b triple (diagnostic, no pass line): Q2 ' + $ab.Q2.hypergraph +
                ' vs triples ' + $ab.Q2.triples + '; Q6b ' + $ab.Q6b.hypergraph +
                ' vs ' + $ab.Q6b.triples) -ForegroundColor DarkGray
}

# --------------------------------------------------------------------------- #
# P14 / knowledge stack: Q0 and E3 live in tools/knowledge/quality.py, and the
# chain used to run only holdout_score.py (see the NOTE above its command).
#
# Measured on 2026-10-02: every docs/evidence/<run-id>/knowledge_quality.json had
# metric ids ['Q1','Q2','Q3','Q4','Q6a','Q6b','Q7'] - no Q0, no E3 - so the hard
# gate "E3 experience-override rate == 0" (SS2.3b / SS4.1b) was never measured by
# the chain. Both tools are run now, and each report keeps its own file name.
#
# RK-13 is attributed by ID from the quality report, never by its aggregate exit
# code: quality.py returns 2 whenever Q5/E1 are not_measured, which is always in
# CI, so that code cannot tell "a hard gate is red" from "the human-only items
# were not measured this time". tools/knowledge/hard_gates.py owns that call, and
# it treats a MISSING id exactly like a failing one (SS4.1b rule 1).
# --------------------------------------------------------------------------- #
# E1 is fed the recorded panel scores on purpose (2026-10-02). E1 is SOFT_IDS, so
# this cannot change the exit code - but the report now says WHY it is red instead
# of "no reviews supplied". Those scores predate the current case index (9 of 16
# case_ids are gone), so quality.py reports `stale_evidence: true` + the stale
# numerator/denominator. Silently omitting them would leave the evidence directory
# looking like nobody had tried; feeding them makes the staleness machine-visible.
# 2026-10-03: the recorded scores now come from the run that measured E1 with the
# Chinese search line in place (`docs/evidence/20261003-e1-zh/README.md`): 3/18 =
# 0.1667, reproduced by two independent panel runs with the same three hits.  The
# older file (docs/evidence/20261002_real/e1_reviews.jsonl) is kept as history; it
# measured 0/16 on the pre-search-line index and half of its case_ids are gone.
# 2026-10-03: Q5's run side now has a real input. SS4.1b judges Q5 only on a real
# model run (the offline plan is written by the same batch as the held-out, so it
# would be self-confirmation), so the chain feeds the committed shots.json of the
# cloud-GLM run. That file also carries `knowledge.hypergraph_fingerprint`, so
# quality.py can tell WHICH index generation produced it: a run from another
# generation is reported as `stale_evidence: true` + not_measured instead of being
# silently joined against today's oracle (the shape of the 20261002_real file).
# ...and `audit_log.jsonl` (the per-run slice) is what makes the JOIN KEY honest:
# SS4.1b rule 2 (no self-reporting) allows reading "what was actually sent" only
# from the audit events, never from shots.json - which is a wrap-up snapshot whose
# camera/movements differ from what the per-shot retrieval saw (measured
# 2026-10-03: 6 of 6 shots drift).  quality.py joins on the emitted query and
# reports the re-derived one as a drift diagnostic only.
# 2026-10-03: the run fed here is now the DeepSeek one (docs/evidence/20261003_real_ds).
# Two reasons over the earlier cloud-GLM run: its shots.json carries a
# `retrieval_calls` that AGREES with the audit events (7 = 7, so extract_run_evidence
# reports no contract warning), and it is the first run made AFTER the per-shot query
# started carrying the shot's DECLARED technique.  The GLM run stays in the repo as
# history (it is what SS35 measured).
python tools/knowledge/quality.py --run-id $runId --json --cases knowledge/cases.jsonl --e1-reviews docs/evidence/20261003-e1-zh/reviews.jsonl --shots docs/evidence/20261003_real_ds/export/shots.json --audit-log docs/evidence/20261003_real_ds/audit_log.jsonl --out (Join-Path $evidenceDir 'knowledge_quality.json') > $null 2>&1
if (-not (Test-Path (Join-Path $evidenceDir 'knowledge_quality.json'))) {
    Fail '  FAILED: the knowledge-stack report was not written'
}
if ($rk13Checks -contains 'RK-13') {
    python tools/knowledge/hard_gates.py --report (Join-Path $evidenceDir 'knowledge_quality.json')
    $hardExit = $LASTEXITCODE
    if ($hardExit -eq 0) {
        Write-Host '  knowledge-stack hard gates (Q0 / Q1-Q7 / E3): all passing' -ForegroundColor Green
    } else {
        if ($rk13Failed -notcontains 'RK-13') { $rk13Failed = @($rk13Failed) + 'RK-13' }
        Write-Host ('  knowledge-stack hard gates exit ' + $hardExit + ' -> RK-13 counts as failed') -ForegroundColor Yellow
    }
} else {
    Write-Host '  knowledge-stack gates not judged: no usable held-out oracle' -ForegroundColor Yellow
}
$rks = (@('RK-7', 'RK-11', 'RK-12', 'RK-18', 'RK-19') + $probePassed + $rk13Checks) -join ','
$rksFailed = $rk13Failed -join ','
# NOTE (2026-10-02 11:17): `--failed` can legitimately be EMPTY now that RK-13 can
# pass, and PowerShell 5.1 DROPS an empty-string argument when it invokes a native
# command. `--failed $rksFailed` therefore reached argparse as a bare `--failed`,
# which exits 2 with "expected one argument"; rks.json was never written and the
# S13 check below failed the run. The first chain run in which every gate passed
# was also the first one that could not report it. The `=` form is a single token,
# so it cannot vanish.
python tools/run_tests_rks.py --run-id $runId --evidence-dir $evidenceDir --checks=$rks --failed=$rksFailed | Out-Null
if ($LASTEXITCODE -ne 0) { Fail '  FAILED: the RK evidence hook (rks.json)' }
Write-Host ('Evidence: ' + $evidenceDir) -ForegroundColor Green

# --------------------------------------------------------------------------- #
# P16 / S13: the evidence directory must be self-describing and committable.
# --------------------------------------------------------------------------- #
foreach ($name in @('rks.json', 'config.fingerprint.json')) {
    if (-not (Test-Path (Join-Path $evidenceDir $name))) {
        Fail ('  FAILED: evidence directory is missing ' + $name)
    }
}
# `git check-ignore -q` exit code 1 means "not ignored" (0 = ignored).
git check-ignore -q ('docs/evidence/' + $runId + '/rks.json')
if ($LASTEXITCODE -ne 1) {
    Fail '  FAILED: docs/evidence/** is ignored by .gitignore (S13)'
}

# A probe whose BD_TEST_RESULT payload could not be reassembled measured NOTHING:
# every RK hanging off it silently degrades to not_measured, and a WARN alone left
# the run printing "All checks passed." with the evidence missing (SS4.1b rule 1).
# The probes did run, so this is not a skip - it is "the evidence did not come
# back", which is the same INCOMPLETE verdict used when Blender is absent.
if ($probeParseFailures.Count -gt 0) {
    Write-Host ('INCOMPLETE: ' + $probeParseFailures.Count + ' probe result(s) could not be parsed: ' + ($probeParseFailures -join ', ')) -ForegroundColor Red
    Write-Host 'INCOMPLETE: their RKs are not_measured; this run is NOT green.' -ForegroundColor Red
    exit 1
}

Write-Host 'All checks passed.' -ForegroundColor Green
exit 0
