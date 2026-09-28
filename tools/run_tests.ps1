# BlockDirector test entry point.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 parses BOM-less
# UTF-8 scripts as ANSI, so non-ASCII characters can break parsing.
#
# NOTE: ErrorActionPreference stays 'Continue'. Blender writes our log lines to
# stderr, and with 'Stop' PowerShell turns any native stderr output into a
# terminating NativeCommandError. We check $LASTEXITCODE explicitly instead.
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

Write-Host '[1/14] Check spec/code consistency (specs/config.default.yaml)' -ForegroundColor Cyan
python tools/gen_specs.py --check
if ($LASTEXITCODE -ne 0) { Fail '  FAILED: spec/code drift' }

Write-Host '[2/14] Run pytest suite' -ForegroundColor Cyan
python -m pytest
if ($LASTEXITCODE -ne 0) { Fail '  FAILED: pytest' }

$blender = $env:BLENDER_EXE
if (-not $blender) {
    $candidates = @(
        'D:\Blender 5.2\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
    )
    $blender = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $blender) {
    Write-Host '[3/14] .. [14/14] skipped: blender.exe not found (set BLENDER_EXE)' -ForegroundColor Yellow
    exit 0
}

Write-Host '[3/14] Smoke test contracts inside Blender Python' -ForegroundColor Cyan
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

Write-Host '[4/14] Run the add-on headless (plan -> scene, full chain)' -ForegroundColor Cyan
$out = Join-Path $env:TEMP ("bd_run_" + (Get-Date -Format 'HHmmss'))
$headlessOut = Invoke-BlenderScript $blender (Join-Path $root 'tools\run_headless.py') @('--offline', '--build', '--out', $out)
$marker = Assert-Marker $headlessOut 'BLOCKDIRECTOR_RESULT' 'headless'
if ($marker -notmatch '"success": true') { Fail ('  FAILED: ' + $marker) }
if ($marker -notmatch '"built": true') { Fail '  FAILED: the run did not build a scene' }
Write-Host ('  ' + ($marker -replace 'BLOCKDIRECTOR_RESULT ', '')) -ForegroundColor Green

Write-Host '[5/14] Phase 1 scene build inside Blender' -ForegroundColor Cyan
$p1Out = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase1_scene.py') $null
$p1Line = Assert-Marker $p1Out 'BD_TEST_RESULT' 'phase1'
if ($p1Line -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p1Line) }
Write-Host '  OK: all Phase 1 scene checks passed' -ForegroundColor Green

Write-Host '[6/14] Phase 2 motion baking inside Blender' -ForegroundColor Cyan
$p2Out = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase2_motion.py') $null
$p2Line = Assert-Marker $p2Out 'BD_TEST_RESULT' 'phase2'
if ($p2Line -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p2Line) }
Write-Host '  OK: all Phase 2 motion checks passed' -ForegroundColor Green

Write-Host '[7/14] Phase 3 framing solver inside Blender' -ForegroundColor Cyan
$p3Out = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase3_framing.py') $null
$p3Line = Assert-Marker $p3Out 'BD_TEST_RESULT' 'phase3'
if ($p3Line -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p3Line) }
Write-Host '  OK: all Phase 3 framing checks passed' -ForegroundColor Green

Write-Host '[8/14] Phase 3 axis and composition audit inside Blender' -ForegroundColor Cyan
$p3bOut = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase3_audit.py') $null
$p3bLine = Assert-Marker $p3bOut 'BD_TEST_RESULT' 'phase3-audit'
if ($p3bLine -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p3bLine) }
Write-Host '  OK: all Phase 3 audit checks passed' -ForegroundColor Green

Write-Host '[9/14] Phase 4 plan-to-scene build inside Blender' -ForegroundColor Cyan
$p4Out = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase4_build.py') $null
$p4Line = Assert-Marker $p4Out 'BD_TEST_RESULT' 'phase4'
if ($p4Line -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p4Line) }
Write-Host '  OK: all Phase 4 build checks passed' -ForegroundColor Green

Write-Host '[10/14] Phase 4 scene state and query tools inside Blender' -ForegroundColor Cyan
$p4tOut = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase4_tools.py') $null
$p4tLine = Assert-Marker $p4tOut 'BD_TEST_RESULT' 'phase4-tools'
if ($p4tLine -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p4tLine) }
Write-Host '  OK: all Phase 4 tools / scene-state checks passed' -ForegroundColor Green

Write-Host '[11/14] Phase 4 rule check and repair loop inside Blender' -ForegroundColor Cyan
$p4rOut = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase4_repair.py') $null
$p4rLine = Assert-Marker $p4rOut 'BD_TEST_RESULT' 'phase4-repair'
if ($p4rLine -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p4rLine) }
Write-Host '  OK: all Phase 4 repair checks passed' -ForegroundColor Green

Write-Host '[12/14] Phase 5 checkpoint and rollback inside Blender' -ForegroundColor Cyan
$p5Out = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase5_checkpoint.py') $null
$p5Line = Assert-Marker $p5Out 'BD_TEST_RESULT' 'phase5-checkpoint'
if ($p5Line -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p5Line) }
Write-Host '  OK: all Phase 5 checkpoint checks passed' -ForegroundColor Green

Write-Host '[13/14] Phase 6 delivery export inside Blender' -ForegroundColor Cyan
$p6Out = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_phase6_delivery.py') $null
$p6Line = Assert-Marker $p6Out 'BD_TEST_RESULT' 'phase6'
if ($p6Line -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $p6Line) }
Write-Host '  OK: all Phase 6 delivery checks passed' -ForegroundColor Green

Write-Host '[14/14] Layer 2/9 project save, load, migrate and rebuild' -ForegroundColor Cyan
$l2Out = Invoke-BlenderScript $blender (Join-Path $root 'tools\blender_tests\test_layer2_project.py') $null
$l2Line = Assert-Marker $l2Out 'BD_TEST_RESULT' 'layer2-project'
if ($l2Line -notmatch '"failed": \[\]') { Fail ('  FAILED: ' + $l2Line) }
Write-Host '  OK: all Layer 2/9 project checks passed' -ForegroundColor Green

Write-Host 'All checks passed.' -ForegroundColor Green
