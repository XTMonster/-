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

# --------------------------------------------------------------------------- #
# The Blender-side manifest. One entry per `--python` script we execute.
# Every tools/blender_tests/test_*.py MUST appear here (asserted below).
# --------------------------------------------------------------------------- #
$checks = @(
    @{ Script = 'tools\blender_tests\test_operator_end_to_end.py'; Marker = 'BD_TEST_RESULT'; Label = 'operator-e2e' },
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
foreach ($check in $checks) {
    Write-Host ("[{0}/{1}] Blender probe: {2}" -f $index, $total, $check.Label) -ForegroundColor Cyan
    $probeOut = Invoke-BlenderScript $blender (Join-Path $root $check.Script) $null
    $probeLine = Assert-Marker $probeOut $check.Marker $check.Label
    if ($probeLine -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $probeLine) }
    Write-Host ('  OK: ' + $check.Label) -ForegroundColor Green
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
python tools/run_tests_rks.py --run-id $runId --evidence-dir $evidenceDir --check 'RK-12,RK-18,RK-19' | Out-Null
Write-Host ('Evidence: ' + $evidenceDir) -ForegroundColor Green

Write-Host 'All checks passed.' -ForegroundColor Green
exit 0
