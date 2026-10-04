# Self-test for the Codex hook pack in this directory.
# It runs the exact command lines from hooks.json through cmd.exe (the same
# program-resolution path a Windows hook launch uses) and asserts exit codes,
# UTF-8 output and the hook output JSON contract.
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File selftest.ps1

$ErrorActionPreference = 'Continue'

$root = $PSScriptRoot
$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$failures = 0
$total = 0

function Read-Utf8File([string]$path) {
    return [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
}

function First-Line([string]$path) {
    return ((Read-Utf8File $path) -split "`n")[0].Trim()
}

function Invoke-HookCommand {
    param([string]$Command, [string]$StdInText)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = '/c ' + $Command
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $inBytes = $utf8NoBom.GetBytes($StdInText)
    $proc.StandardInput.BaseStream.Write($inBytes, 0, $inBytes.Length)
    $proc.StandardInput.BaseStream.Flush()
    $proc.StandardInput.Close()
    $outMs = New-Object System.IO.MemoryStream
    $proc.StandardOutput.BaseStream.CopyTo($outMs)
    $outBytes = $outMs.ToArray()
    $errMs = New-Object System.IO.MemoryStream
    $proc.StandardError.BaseStream.CopyTo($errMs)
    $errBytes = $errMs.ToArray()
    $proc.WaitForExit()
    $stdoutText = ''
    $utf8Ok = $true
    try { $stdoutText = $strictUtf8.GetString($outBytes) } catch { $utf8Ok = $false }
    $stderrText = ''
    try { $stderrText = $strictUtf8.GetString($errBytes) } catch { }
    return [pscustomobject]@{
        ExitCode    = $proc.ExitCode
        Stdout      = $stdoutText
        Stderr      = $stderrText
        StdoutBytes = $outBytes.Length
        Utf8Ok      = $utf8Ok
    }
}

function Assert-True {
    param([string]$Name, [bool]$Condition, [string]$Detail)
    $script:total = $script:total + 1
    if ($Condition) {
        Write-Host ("  PASS  " + $Name)
    } else {
        $script:failures = $script:failures + 1
        Write-Host ("  FAIL  " + $Name + " :: " + $Detail)
    }
}

# --- resolve the real hook commands straight out of hooks.json ---------------

$configPath = Join-Path (Split-Path -Parent $root) 'hooks.json'
$config = (Read-Utf8File $configPath) | ConvertFrom-Json
$commands = @{}
foreach ($eventProperty in $config.hooks.PSObject.Properties) {
    $group = $eventProperty.Value[0]
    $handler = $group.hooks[0]
    $commands[$eventProperty.Name] = [string]$handler.command
}

foreach ($required in @('SessionStart', 'UserPromptSubmit', 'SubagentStart', 'PreToolUse')) {
    Assert-True ("hooks.json declares " + $required) ($commands.ContainsKey($required)) 'missing event'
}

$contractFirstLine = First-Line (Join-Path $root 'workflow-contract.md')
$subagentMarker = First-Line (Join-Path $root 'subagent-protocol.md')
$sessionMarker = First-Line (Join-Path $root 'session-start.md')
$routingMarker = First-Line (Join-Path $root 'model-routing.md')

Write-Host 'Inject hook (SessionStart / UserPromptSubmit / SubagentStart)'

$r = Invoke-HookCommand $commands.SessionStart '{"hook_event_name":"SessionStart","cwd":"E:\\\\demo","session_id":"s1","source":"startup"}'
Assert-True 'session-start exit 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
Assert-True 'session-start stdout is valid utf-8' $r.Utf8Ok 'stdout was not valid utf-8'
$sessionOk = $false
$sessionJson = $null
try { $sessionJson = $r.Stdout | ConvertFrom-Json; $sessionOk = $true } catch { }
Assert-True 'session-start stdout is json' $sessionOk $r.Stdout
if ($sessionOk) {
    $ctx = $sessionJson.hookSpecificOutput.additionalContext
    Assert-True 'session-start event name' ($sessionJson.hookSpecificOutput.hookEventName -eq 'SessionStart') $r.Stdout
    Assert-True 'session-start injects contract' ($ctx -and $ctx.Contains($contractFirstLine)) 'missing contract text'
    Assert-True 'session-start injects checklist' ($ctx -and $ctx.Contains($sessionMarker)) 'missing session checklist'
    Assert-True 'session-start injects model routing' ($ctx -and $ctx.Contains($routingMarker)) 'missing model routing contract'
}

$r = Invoke-HookCommand $commands.UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"hi","session_id":"s1"}'
Assert-True 'prompt-submit exit 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$promptOk = $false
try { $promptJson = $r.Stdout | ConvertFrom-Json; $promptOk = $true } catch { }
Assert-True 'prompt-submit stdout is json' $promptOk $r.Stdout
if ($promptOk) {
    $ctx = $promptJson.hookSpecificOutput.additionalContext
    Assert-True 'prompt-submit event name' ($promptJson.hookSpecificOutput.hookEventName -eq 'UserPromptSubmit') $r.Stdout
    Assert-True 'prompt-submit injects contract' ($ctx -and $ctx.Contains($contractFirstLine)) 'missing contract text'
    Assert-True 'prompt-submit omits checklist' ($ctx -and (-not $ctx.Contains($sessionMarker))) 'unexpected checklist'
    Assert-True 'prompt-submit injects model routing' ($ctx -and $ctx.Contains($routingMarker)) 'missing model routing contract'
    #: No trigger words in "hi" -> the auto-consultation block must stay out.
    #: (`panel_consult.py` itself is in the always-injected routing contract, so the
    #: marker has to be the trigger-only output dir `--out work/_panel_*`.)
    Assert-True 'prompt-submit does not trigger the panel on a plain prompt' `
        ($ctx -and (-not $ctx.Contains('--out work/_panel_'))) 'panel block leaked into a plain prompt'
}

Write-Host 'Auto joint-consultation trigger (UserPromptSubmit)'

#: Chinese trigger words are built from code points so this file stays ASCII-only
#: (PowerShell 5.1 would read a BOM-less UTF-8 literal as ANSI).
function From-CodePoints([int[]]$codes) {
    return -join ($codes | ForEach-Object { [char]$_ })
}

$hardWord = From-CodePoints @(0x96be, 0x9898)          # "hard problem"
$whyWord = From-CodePoints @(0x4e3a, 0x4ec0, 0x4e48)   # "why"
$reviewWord = From-CodePoints @(0x5ba1, 0x67e5)        # "review"
$tradeWord = From-CodePoints @(0x53d6, 0x820d)         # "tradeoff"

$hardEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $hardWord + ' ' +
    $whyWord + ' tools/kb_fetch/build_cases.py","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $hardEvent
Assert-True 'trigger: hard prompt exit 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$triggerOk = $false
try { $triggerJson = $r.Stdout | ConvertFrom-Json; $triggerOk = $true } catch { }
Assert-True 'trigger: hard prompt stdout is json' $triggerOk $r.Stdout
if ($triggerOk) {
    $ctx = $triggerJson.hookSpecificOutput.additionalContext
    Assert-True 'trigger: hard prompt pulls the panel' `
        ($ctx -and $ctx.Contains('python tools/panel_consult.py')) 'missing panel command'
    Assert-True 'trigger: hard prompt picks the hard bucket' `
        ($ctx -and $ctx.Contains('_panel_hard')) 'wrong output dir'
    Assert-True 'trigger: hard prompt offers the file from the prompt' `
        ($ctx -and $ctx.Contains('--source tools/kb_fetch/build_cases.py')) 'source not extracted'
    Assert-True 'trigger: hard prompt keeps the routing contract' `
        ($ctx -and $ctx.Contains($routingMarker)) 'missing routing contract'
}

$reviewEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $reviewWord +
    ' tests/test_cases_corpus.py","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $reviewEvent
$reviewOk = $false
try { $reviewJson = $r.Stdout | ConvertFrom-Json; $reviewOk = $true } catch { }
if ($reviewOk) {
    $ctx = $reviewJson.hookSpecificOutput.additionalContext
    Assert-True 'trigger: review bucket' ($ctx -and $ctx.Contains('_panel_review')) $ctx
}

$ideaEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $tradeWord +
    ' build_cases.py","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $ideaEvent
$ideaOk = $false
try { $ideaJson = $r.Stdout | ConvertFrom-Json; $ideaOk = $true } catch { }
if ($ideaOk) {
    $ctx = $ideaJson.hookSpecificOutput.additionalContext
    Assert-True 'trigger: idea bucket' ($ctx -and $ctx.Contains('_panel_idea')) $ctx
}

$r = Invoke-HookCommand $commands.SubagentStart '{"hook_event_name":"SubagentStart","agent_id":"a1","agent_type":"reviewer"}'
Assert-True 'subagent-start exit 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$subagentOk = $false
try { $subagentJson = $r.Stdout | ConvertFrom-Json; $subagentOk = $true } catch { }
Assert-True 'subagent-start stdout is json' $subagentOk $r.Stdout
if ($subagentOk) {
    $ctx = $subagentJson.hookSpecificOutput.additionalContext
    Assert-True 'subagent-start event name' ($subagentJson.hookSpecificOutput.hookEventName -eq 'SubagentStart') $r.Stdout
    Assert-True 'subagent-start injects role protocol' ($ctx -and $ctx.Contains($subagentMarker)) 'missing subagent protocol'
    Assert-True 'subagent-start injects model routing' ($ctx -and $ctx.Contains($routingMarker)) 'missing model routing contract'
}

$r = Invoke-HookCommand $commands.UserPromptSubmit ''
Assert-True 'inject hook ignores empty stdin' ($r.ExitCode -eq 0 -and $r.StdoutBytes -eq 0) ("exit=" + $r.ExitCode + " bytes=" + $r.StdoutBytes)

Write-Host 'Guard hook (PreToolUse)'

function New-PreToolEvent {
    param([string]$ToolName, [string]$ToolInputJson)
    return '{"hook_event_name":"PreToolUse","tool_name":"' + $ToolName + '","tool_input":' + $ToolInputJson + ',"cwd":"E:\\\\demo"}'
}

$allowCases = @(
    @{ Name = 'allows plain pytest run';        Event = (New-PreToolEvent 'shell' '{"command":"python -m pytest"}') },
    @{ Name = 'allows pytest with -k selector'; Event = (New-PreToolEvent 'shell' '{"command":"python -m pytest -k framing"}') },
    @{ Name = 'allows git status';              Event = (New-PreToolEvent 'shell' '{"command":"git status --short"}') },
    @{ Name = 'allows git commit';              Event = (New-PreToolEvent 'shell' '{"command":"git commit -m \"feat: hooks\""}') },
    @{ Name = 'allows reading test files';      Event = (New-PreToolEvent 'shell' '{"command":"Get-Content tests\\test_foo.py"}') },
    @{ Name = 'allows patch of source file';    Event = (New-PreToolEvent 'apply_patch' '{"input":"*** Begin Patch\n*** Update File: src/app.py\n+print(1)\n*** End Patch\n"}') },
    @{ Name = 'allows empty tool_input';        Event = (New-PreToolEvent 'shell' '{}') }
)
foreach ($case in $allowCases) {
    $r = Invoke-HookCommand $commands.PreToolUse $case.Event
    Assert-True $case.Name ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
}

$denyCases = @(
    @{ Name = 'blocks Remove-Item tests';        Event = (New-PreToolEvent 'shell' '{"command":"Remove-Item -Recurse -Force tests"}') },
    @{ Name = 'blocks rm of test file';          Event = (New-PreToolEvent 'shell' '{"command":"rm tests/test_foo.py"}') },
    @{ Name = 'blocks git rm of tests';          Event = (New-PreToolEvent 'shell' '{"command":"git rm -r tests"}') },
    @{ Name = 'blocks pytest --deselect';        Event = (New-PreToolEvent 'shell' '{"command":"python -m pytest --deselect tests/test_foo.py"}') },
    @{ Name = 'blocks pytest -k not';            Event = (New-PreToolEvent 'shell' '{"command":"python -m pytest -k \"not slow\""}') },
    @{ Name = 'blocks pytest --ignore';          Event = (New-PreToolEvent 'shell' '{"command":"python -m pytest --ignore=tests/test_slow.py"}') },
    @{ Name = 'blocks git reset --hard';         Event = (New-PreToolEvent 'shell' '{"command":"git reset --hard HEAD~1"}') },
    @{ Name = 'blocks git checkout --';          Event = (New-PreToolEvent 'shell' '{"command":"git checkout -- src/app.py"}') },
    @{ Name = 'blocks git clean -fd';            Event = (New-PreToolEvent 'shell' '{"command":"git clean -fd"}') },
    @{ Name = 'blocks git stash drop';           Event = (New-PreToolEvent 'shell' '{"command":"git stash drop"}') },
    @{ Name = 'blocks git push --force';         Event = (New-PreToolEvent 'shell' '{"command":"git push --force origin main"}') },
    @{ Name = 'blocks git branch -D';            Event = (New-PreToolEvent 'shell' '{"command":"git branch -D feature"}') },
    @{ Name = 'blocks git commit --no-verify';   Event = (New-PreToolEvent 'shell' '{"command":"git commit --no-verify -m x"}') },
    @{ Name = 'blocks patch deleting a test';    Event = (New-PreToolEvent 'apply_patch' '{"input":"*** Begin Patch\n*** Delete File: tests/test_foo.py\n*** End Patch\n"}') }
)
foreach ($case in $denyCases) {
    $r = Invoke-HookCommand $commands.PreToolUse $case.Event
    $denyOk = $false
    $denyJson = $null
    if ($r.ExitCode -eq 0 -and $r.StdoutBytes -gt 0) {
        try { $denyJson = $r.Stdout | ConvertFrom-Json; $denyOk = $true } catch { }
    }
    Assert-True $case.Name ($denyOk -and $denyJson.decision -eq 'block' -and $denyJson.reason.Length -gt 0) ("exit=" + $r.ExitCode + " out=" + $r.Stdout + " err=" + $r.Stderr)
    if ($denyOk) {
        Assert-True ($case.Name + ' denies PreToolUse') ($denyJson.hookSpecificOutput.hookEventName -eq 'PreToolUse' -and $denyJson.hookSpecificOutput.permissionDecision -eq 'deny') $r.Stdout
    }
    Assert-True ($case.Name + ' is silent on stderr') ($r.Stderr.Length -eq 0) $r.Stderr
}

$r = Invoke-HookCommand $commands.PreToolUse ''
Assert-True 'guard ignores empty stdin' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode)

Write-Host ''
Write-Host ("checks: " + $total + "  failures: " + $failures)
if ($failures -gt 0) { exit 1 }
Write-Host 'HOOK SELFTEST PASS'
exit 0
