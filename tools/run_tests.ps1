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

Write-Host '[1/4] Check spec/code consistency (specs/config.default.yaml)' -ForegroundColor Cyan
python tools/gen_specs.py --check
if ($LASTEXITCODE -ne 0) { Fail '  FAILED: spec/code drift' }

Write-Host '[2/4] Run pytest suite' -ForegroundColor Cyan
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
    Write-Host '[3/4] and [4/4] skipped: blender.exe not found (set BLENDER_EXE)' -ForegroundColor Yellow
    exit 0
}

Write-Host '[3/4] Smoke test contracts inside Blender Python' -ForegroundColor Cyan
$smoke = @(
    'import sys',
    "sys.path.insert(0, r'$root')",
    'import block_director',
    'from block_director.contracts import AppConfig',
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

Write-Host '[4/4] Run the add-on headless (Phase 0 state machine)' -ForegroundColor Cyan
$out = Join-Path $env:TEMP ("bd_run_" + (Get-Date -Format 'HHmmss'))
$script = Join-Path $root 'tools\run_headless.py'
$output = & $blender --background --factory-startup --python $script -- --offline --out $out 2>&1
$marker = $output | Select-String -Pattern 'BLOCKDIRECTOR_RESULT' | Select-Object -First 1
if (-not $marker) {
    Write-Host '  FAILED: no BLOCKDIRECTOR_RESULT marker' -ForegroundColor Red
    $output | Select-Object -Last 15
    exit 1
}
if ($marker.Line -notmatch '"success": true') {
    Write-Host ('  FAILED: ' + $marker.Line) -ForegroundColor Red
    exit 1
}
Write-Host ('  ' + ($marker.Line -replace 'BLOCKDIRECTOR_RESULT ', '')) -ForegroundColor Green
Write-Host 'All checks passed.' -ForegroundColor Green
