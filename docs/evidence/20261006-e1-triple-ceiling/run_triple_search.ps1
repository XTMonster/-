# Decisive experiment behind GPT-6A's challenge (docs/evidence/20261006-gpt6a-round2/
# answers/full_head.md point 3): is the "0.46-0.47 ceiling" a combinatorial optimum, or
# just the score of the ONE selection method we happened to try?
#
# We assemble triples ourselves and judge them under the SAME frozen C=3 ruler
# (same SYSTEM prompt, same two judges, via tools/knowledge/e1_panel.judge).
$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)

$env:DEEPSEEK_API_KEY = (Get-ItemProperty -Path 'HKCU:\Environment' -Name DEEPSEEK_API_KEY).DEEPSEEK_API_KEY
$env:GLM_API_KEY = (Get-ItemProperty -Path 'HKCU:\Environment' -Name GLM_API_KEY).GLM_API_KEY
$env:PYTHONIOENCODING = 'utf-8'

python -u tools/knowledge/e1_triple_search.py `
  --labels docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl `
  --cases knowledge --pool-per-query 6 --max-triples 20 --workers 6 `
  --out work/_triple_search.batch3.top120.json
Write-Host ("exit=" + $LASTEXITCODE)
