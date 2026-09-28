# BlockDirector test entry point.
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 parses BOM-less
# UTF-8 scripts as ANSI, so non-ASCII characters can break parsing.
#
# Usage: powershell -ExecutionPolicy Bypass -File tools/run_tests.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host '[1/3] Check spec/code consistency (specs/config.default.yaml)' -ForegroundColor Cyan
python tools/gen_specs.py --check

Write-Host '[2/3] Run pytest suite' -ForegroundColor Cyan
python -m pytest

Write-Host '[3/3] Smoke test contracts inside Blender Python' -ForegroundColor Cyan
$blender = $env:BLENDER_EXE
if (-not $blender) {
    $candidates = @(
        'D:\Blender 5.2\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
    )
    $blender = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $blender) {
    Write-Host '  blender.exe not found; skipped (set BLENDER_EXE to enable)' -ForegroundColor Yellow
    exit 0
}

$lines = @(
    'import sys',
    "sys.path.insert(0, r'$root')",
    'import block_director',
    'from block_director.contracts import AppConfig',
    "print('SMOKE_OK', block_director.__version__, sys.version.split()[0], len(AppConfig().errors()))"
)
$expr = ($lines -join '; ')

& $blender --background --factory-startup --python-expr $expr 2>&1 |
    Select-String -Pattern 'SMOKE_OK'
