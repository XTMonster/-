# Codex hook: inject the enforced workflow contract.
# Events: SessionStart / UserPromptSubmit / SubagentStart.
# stdin  : hook event JSON (UTF-8)
# stdout : hook output JSON (UTF-8)

$ErrorActionPreference = 'Continue'

$utf8 = New-Object System.Text.UTF8Encoding($false)

$raw = ''
try {
    $stdinStream = [Console]::OpenStandardInput()
    $stdinReader = New-Object System.IO.StreamReader($stdinStream, $utf8)
    $raw = $stdinReader.ReadToEnd()
} catch {
    $raw = ''
}

$event = 'UserPromptSubmit'
if ($raw) {
    try {
        $evt = $raw | ConvertFrom-Json
        if ($evt -and $evt.hook_event_name) { $event = [string]$evt.hook_event_name }
    } catch {
        $event = 'UserPromptSubmit'
    }
}

if (-not $raw) { exit 0 }

$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }

function Get-ContractText([string]$fileName) {
    if (-not $root) { return '' }
    $path = Join-Path $root $fileName
    if (Test-Path -LiteralPath $path) {
        return ([System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)).Trim()
    }
    return ''
}

$parts = @()
$contract = Get-ContractText 'workflow-contract.md'
if ($contract) { $parts += $contract }

# Model-routing contract (ideas / hard problems / review go to the GLM-5.3 channel;
# execution stays on the main DeepSeek thread). Injected on all three events, so
# sub-agents see it too. NOTE: keep this file ASCII-only - Windows PowerShell 5.1
# parses BOM-less UTF-8 as ANSI and would swallow the next line.
$routing = Get-ContractText 'model-routing.md'
if ($routing) { $parts += $routing }

# --------------------------------------------------------------------------- #
# Auto joint-consultation trigger (2026-10-05).
# Why: the routing contract above is passive text; the user asked for the
# two-sided panel to fire *by itself* when the request is an analysis, a review
# or a hard problem.  ASCII-only by design -- PowerShell 5.1 reads a BOM-less
# UTF-8 .ps1 as ANSI, so every Chinese trigger word is a \uXXXX regex escape
# and every Chinese line of prose lives in consult-trigger.md (read as UTF-8).
# --------------------------------------------------------------------------- #
function Get-EventText($hookEvent) {
    if (-not $hookEvent) { return '' }
    foreach ($name in @('prompt', 'message', 'task', 'text', 'user_prompt',
                        'description', 'agent_prompt', 'content')) {
        $value = $hookEvent.$name
        if ($value -is [string] -and $value.Trim()) { return [string]$value }
    }
    return ''
}

#: kind -> (roles, pattern). First match wins, so the order is the priority:
#: a request that is both a hard problem and a design question is a hard problem.
$CONSULT_TRIGGERS = @(
    @{ Kind = 'hard';   Roles = '\u9886\u57df\u8bb2\u89e3,\u7ea2\u961f\u53cd\u65b9,\u5b9e\u73b0\u987e\u95ee'
       Pattern = '(\u96be\u9898|\u5361\u4f4f|\u963b\u585e|\u4e3a\u4ec0\u4e48|\u8bca\u65ad|\u6392\u67e5|\u6b7b\u7ed3|\u6839\u56e0|\u62a5\u9519|\u5d29\u6e83|\u7591\u96be|stuck|blocker|root cause|diagnose|deadlock)' },
    @{ Kind = 'review'; Roles = '\u6d4b\u8bd5\u4e0e\u9a8c\u6536,\u89c4\u683c\u4e00\u81f4\u6027'
       Pattern = '(\u5ba1\u67e5|\u5ba1\u6838|\u590d\u6838|\u9a8c\u6536|\u5bf9\u6297|\u590d\u7b97|\u6821\u9a8c|review|audit|verify|cross-check)' },
    @{ Kind = 'idea';   Roles = '\u9886\u57df\u8bb2\u89e3,\u5b9e\u73b0\u987e\u95ee'
       Pattern = '(\u65b9\u6848|\u53d6\u820d|\u6743\u8861|\u601d\u8def|\u67b6\u6784|\u600e\u4e48\u505a|design|approach|tradeoff)' }
)

$promptText = ''
if ($raw) {
    try { $promptText = Get-EventText $evt } catch { $promptText = '' }
}

$trigger = $null
if ($promptText -and $promptText.Length -ge 8) {
    foreach ($candidate in $CONSULT_TRIGGERS) {
        $found = [regex]::Matches($promptText, $candidate.Pattern, 'IgnoreCase')
        if ($found.Count -gt 0) {
            $hits = (($found | ForEach-Object { $_.Value }) |
                     Select-Object -Unique) -join '/'
            $trigger = [pscustomobject]@{ Kind = $candidate.Kind
                                          Roles = $candidate.Roles
                                          Hits = $hits
                                          Prompt = $promptText }
            break
        }
    }
}

if ($trigger) {
    $template = Get-ContractText 'consult-trigger.md'
    if ($template) {
        $tick = [char]96
        $paths = @([regex]::Matches(
            $trigger.Prompt,
            '[A-Za-z0-9_\-./\\]+\.(py|md|json|jsonl|ps1|ya?ml|toml)') |
            ForEach-Object { $_.Value } | Select-Object -Unique | Select-Object -First 6)
        $sourceLines = ''
        foreach ($item in $paths) {
            $sourceLines += '    --source ' + $item + ' ' + $tick + "`n"
        }
        if (-not $sourceLines) {
            $sourceLines = '    --source <file:start-end> ' + $tick + "`n"
        }
        $parts += $template.Replace('{{KIND}}', $trigger.Kind).
                            Replace('{{HITS}}', $trigger.Hits).
                            Replace('{{ROLES}}', $trigger.Roles).
                            Replace('{{SOURCES}}', $sourceLines).
                            Replace('{{SLUG}}', $trigger.Kind)
    }
}

if ($event -eq 'SessionStart') {
    $extra = Get-ContractText 'session-start.md'
    if ($extra) { $parts += $extra }
} elseif ($event -eq 'SubagentStart') {
    $extra = Get-ContractText 'subagent-protocol.md'
    if ($extra) { $parts += $extra }
}

$context = ($parts -join "`n`n").Trim()
if (-not $context) { exit 0 }

$payload = [ordered]@{
    hookSpecificOutput = [ordered]@{
        hookEventName     = $event
        additionalContext = $context
    }
}

$json = $payload | ConvertTo-Json -Depth 5 -Compress

$outStream = [Console]::OpenStandardOutput()
$writer = New-Object System.IO.StreamWriter($outStream, $utf8)
$writer.Write($json)
$writer.Flush()
exit 0
