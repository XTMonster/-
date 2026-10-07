# Start a SECOND BlockDirector sidecar in front of DeepSeek (port 8782).
# The key is read from HKCU:\Environment into this process only (never written to the repo).
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$hkcu = Get-ItemProperty 'HKCU:\Environment'
$env:DEEPSEEK_API_KEY = $hkcu.DEEPSEEK_API_KEY
if (-not $env:DEEPSEEK_API_KEY) {
    Write-Output 'NO DEEPSEEK_API_KEY in HKCU:\Environment'
    exit 1
}

$sidecarArgs = @(
    'tools/sidecar_server.py',
    '--host', '127.0.0.1',
    '--port', '8782',
    '--upstream', 'https://api.deepseek.com',
    '--upstream-kind', 'openai',
    '--model', 'deepseek-chat',
    '--upstream-api-key-env', 'DEEPSEEK_API_KEY',
    '--knowledge-dir', 'knowledge',
    '--cases-backend', 'hybrid',
    '--temperature', '0',
    '--seed', '0',
    '--timeout', '900'
)

$p = Start-Process -FilePath 'python' -ArgumentList $sidecarArgs `
    -WorkingDirectory $root `
    -RedirectStandardOutput "$root\work\_sidecar_ds.out" `
    -RedirectStandardError "$root\work\_sidecar_ds.err" `
    -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 6
Write-Output ("pid=" + $p.Id + " hasExited=" + $p.HasExited)
try {
    $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8782/health' -TimeoutSec 10
    Write-Output ("health=" + ($h | ConvertTo-Json -Compress))
} catch {
    Write-Output ("HEALTH FAIL: " + $_.Exception.Message)
}
