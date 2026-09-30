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

Write-Host ("[4/{0}] Run the add-on headless (plan -> scene -> delivery, one command)" -f $total) -ForegroundColor Cyan
$out = Join-Path $env:TEMP ("bd_run_" + (Get-Date -Format 'HHmmss'))
$headlessOut = Invoke-BlenderScript $blender (Join-Path $root 'tools\run_headless.py') @('--offline', '--build', '--out', $out, '--export')
$marker = Assert-Marker $headlessOut 'BLOCKDIRECTOR_RESULT' 'headless'
if ($marker -notmatch '"success": true') { Fail ('  FAILED: ' + $marker) }
if ($marker -notmatch '"built": true') { Fail '  FAILED: the run did not build a scene' }
Write-Host ('  ' + ($marker -replace 'BLOCKDIRECTOR_RESULT ', '')) -ForegroundColor Green
$exportMarker = Assert-Marker $headlessOut 'BLOCKDIRECTOR_EXPORT' 'delivery'
if ($exportMarker -notmatch '"ok": true') { Fail ('  FAILED: ' + $exportMarker) }
if ($exportMarker -notmatch '"aborted": false') { Fail '  FAILED: export aborted (render audit)' }
Write-Host ('  ' + ($exportMarker -replace 'BLOCKDIRECTOR_EXPORT ', '')) -ForegroundColor Green

# --------------------------------------------------------------------------- #
# Blender-side probes from the manifest.
# --------------------------------------------------------------------------- #
$index = 5
$probePassed = @()
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
python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl --json (Join-Path $evidenceDir 'knowledge_quality.json') > $null 2>&1
$rk13Exit = $LASTEXITCODE
if (($rk13Exit -eq 0) -or ($rk13Exit -eq 1)) {
    $rk13Checks += 'RK-13'
    if ($rk13Exit -eq 1) { $rk13Failed += 'RK-13' }
    Write-Host ('  RK-13 measured from the held-out (exit ' + $rk13Exit + ')') -ForegroundColor Green
} else {
    Write-Host '  RK-13 not measured: no usable held-out oracle' -ForegroundColor Yellow
}
$rks = (@('RK-7', 'RK-11', 'RK-12', 'RK-18', 'RK-19') + $probePassed + $rk13Checks) -join ','
$rksFailed = $rk13Failed -join ','
python tools/run_tests_rks.py --run-id $runId --evidence-dir $evidenceDir --checks $rks --failed $rksFailed | Out-Null
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

Write-Host 'All checks passed.' -ForegroundColor Green
exit 0
