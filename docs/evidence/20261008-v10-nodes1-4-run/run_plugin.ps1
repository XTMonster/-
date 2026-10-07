# Run one previs through the plugin's own path (see _run_plugin_previs.py).
# ASCII-only: Windows PowerShell 5.1 parses BOM-less UTF-8 as ANSI.
# $ErrorActionPreference stays 'Continue': Blender writes logs to stderr.
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$SidecarUrl = '',
    [string]$Model = 'qwen3.8-max-0902',
    [string]$Preset = 'hd16x9',
    [string]$OutDir = '',
    [string]$LogStem = 'plugin_run',
    [double]$LlmTimeout = 0,
    [switch]$Offline
)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($OutDir) { $env:BLOCKDIRECTOR_PROJECTS = $OutDir }

$blender = 'D:\Blender 5.2\blender.exe'
if (-not (Test-Path $blender)) { Write-Output ('NO BLENDER: ' + $blender); exit 1 }

$driverArgs = @(
    (Join-Path $root 'work\_run_plugin_previs.py'),
    '--', '--script', $Script, '--model', $Model, '--preset', $Preset
)
if ($Offline) { $driverArgs += '--offline' }
if ($SidecarUrl) { $driverArgs += @('--sidecar-url', $SidecarUrl) }
if ($LlmTimeout -gt 0) { $driverArgs += @('--llm-timeout', [string]$LlmTimeout) }

& $blender --background --factory-startup --python $driverArgs `
    1> (Join-Path $root ("work\_" + $LogStem + ".log")) `
    2> (Join-Path $root ("work\_" + $LogStem + ".err"))
$code = $LASTEXITCODE
Write-Output ('blender exit=' + $code)
Write-Output ('projects_root=' + $env:BLOCKDIRECTOR_PROJECTS)
