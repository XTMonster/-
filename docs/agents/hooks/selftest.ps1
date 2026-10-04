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

#: Keep the whole selftest hermetic: the semantic classifier is stubbed to "no
#: kinds" so every assertion below exercises the *keyword* path only.  The
#: semantic path gets its own stubs in the dedicated section further down.
$env:CODEX_CLASSIFY_STUB = '{"kinds":[]}'

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

Write-Host 'GitHub reuse check trigger (UserPromptSubmit)'

#: A design / planning / execution-doc prompt must pull **both** blocks: the joint
#: consultation (bucket `idea`) and the GitHub reuse checklist (user ruling 2026-10-05).
$designWord = From-CodePoints @(0x8bbe, 0x8ba1)        # "design"
$planWord = From-CodePoints @(0x89c4, 0x5212)          # "plan"
$licenceGate = From-CodePoints @(0x4e0d, 0x5f97, 0x5f15, 0x5165, 0x672c, 0x4ed3, 0x5e93)  # "must not be brought into this repo"
$remixWord = From-CodePoints @(0x9b54, 0x6539)        # "remix / modify-then-adopt"
$derivativeRule = From-CodePoints @(0x884d, 0x751f, 0x8bb8, 0x53ef)  # "derivative licence"
$projectCheck = From-CodePoints @(0x672c, 0x9879, 0x76ee, 0x5f53, 0x524d, 0x7684, 0x5b9e, 0x9645, 0x60c5, 0x51b5)  # "this project's actual situation"
$perCandidate = From-CodePoints @(0x9b54, 0x6539, 0x540e, 0x80fd, 0x5426, 0x7528)  # "can a remix work" column
$sameAction = From-CodePoints @(0x540c, 0x4e00, 0x4e2a, 0x52a8, 0x4f5c)              # "the same act"
$reuseMarker = First-Line (Join-Path $root 'github-reuse.md')

$designEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $designWord +
    ' a new module, then ' + $planWord + ' docs/plan.md","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $designEvent
Assert-True 'reuse: design prompt exit 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$designOk = $false
try { $designJson = $r.Stdout | ConvertFrom-Json; $designOk = $true } catch { }
Assert-True 'reuse: design prompt stdout is json' $designOk $r.Stdout
if ($designOk) {
    $ctx = $designJson.hookSpecificOutput.additionalContext
    Assert-True 'reuse: design prompt pulls the GitHub checklist' `
        ($ctx -and $ctx.Contains($reuseMarker)) 'missing github-reuse block'
    Assert-True 'reuse: design prompt also pulls the panel' `
        ($ctx -and $ctx.Contains('--out work/_panel_idea')) 'design prompt did not trigger the idea bucket'
    Assert-True 'reuse: checklist keeps the licence gate' `
        ($ctx -and $ctx.Contains($licenceGate)) 'licence gate missing'
    Assert-True 'reuse: checklist offers the remix option' `
        ($ctx -and $ctx.Contains($remixWord)) 'the modify-then-adopt option is missing'
    Assert-True 'reuse: checklist states the derivative-licence rule' `
        ($ctx -and $ctx.Contains($derivativeRule)) 'derivative licence rule missing'
    Assert-True 'reuse: judge remixes against this project reality' `
        ($ctx -and $ctx.Contains($projectCheck)) 'project-specific constraint table missing'
    Assert-True 'reuse: the remix verdict is a column of the candidate table' `
        ($ctx -and $ctx.Contains($perCandidate)) 'the per-candidate remix column is missing'
    Assert-True 'reuse: surveying and remix-judging are one act' `
        ($ctx -and $ctx.Contains($sameAction)) 'the one-act rule is missing'
}

#: A prompt that asks about remixing an upstream project must pull the checklist too.
$remixEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $remixWord +
    ' upstream repo ok? ' + $designWord + '","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $remixEvent
$remixOk = $false
try { $remixJson = $r.Stdout | ConvertFrom-Json; $remixOk = $true } catch { }
Assert-True 'reuse: remix prompt stdout is json' $remixOk $r.Stdout
if ($remixOk) {
    $ctx = $remixJson.hookSpecificOutput.additionalContext
    Assert-True 'reuse: remix prompt pulls the checklist' `
        ($ctx -and $ctx.Contains($reuseMarker)) 'remix prompt did not trigger the checklist'
}

$r = Invoke-HookCommand $commands.UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"hi","session_id":"s1"}'
$plainOk = $false
try { $plainJson = $r.Stdout | ConvertFrom-Json; $plainOk = $true } catch { }
Assert-True 'reuse: plain prompt stdout is json' $plainOk $r.Stdout
if ($plainOk) {
    $ctx = $plainJson.hookSpecificOutput.additionalContext
    Assert-True 'reuse: plain prompt stays free of the checklist' `
        ($ctx -and (-not $ctx.Contains($reuseMarker))) 'reuse block leaked into a plain prompt'
}

Write-Host 'Semantic classifier (stubbed - the selftest never calls the network)'

#: The keyword tables cannot see "just redo this thing" as a design request; the
#: semantic verdict must be able to add it on its own.
$plainRewrite = From-CodePoints @(0x628a, 0x8fd9, 0x4e1c, 0x897f, 0x91cd, 0x505a, 0x4e00, 0x904d)  # "just redo this thing"
$semanticEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $plainRewrite + '","session_id":"s1"}'

$env:CODEX_CLASSIFY_STUB = '{"kinds":["design","idea"]}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $semanticEvent
$semanticOk = $false
try { $semanticJson = $r.Stdout | ConvertFrom-Json; $semanticOk = $true } catch { }
Assert-True 'semantic: keyword-less prompt stdout is json' $semanticOk $r.Stdout
if ($semanticOk) {
    $ctx = $semanticJson.hookSpecificOutput.additionalContext
    Assert-True 'semantic: verdict alone pulls the GitHub checklist' `
        ($ctx -and $ctx.Contains($reuseMarker)) 'design verdict did not inject the checklist'
    Assert-True 'semantic: verdict alone pulls the panel' `
        ($ctx -and $ctx.Contains('--out work/_panel_idea')) 'idea verdict did not inject the panel'
    Assert-True 'semantic: the block shows where the verdict came from' `
        ($ctx -and $ctx.Contains('semantic:design')) 'missing the per-kind provenance note'
}

#: Keyword and semantic are a UNION: an empty semantic verdict must not cancel a
#: keyword hit (this is the case that a semantic-only design would have broken).
$env:CODEX_CLASSIFY_STUB = '{"kinds":[]}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $designEvent
$unionOk = $false
try { $unionJson = $r.Stdout | ConvertFrom-Json; $unionOk = $true } catch { }
if ($unionOk) {
    $ctx = $unionJson.hookSpecificOutput.additionalContext
    Assert-True 'semantic: an empty verdict keeps the keyword hit' `
        ($ctx -and $ctx.Contains($reuseMarker)) 'keyword hit was cancelled by an empty verdict'
    Assert-True 'semantic: the empty verdict is visible in the note' `
        ($ctx -and $ctx.Contains('semantic: none')) 'the empty verdict is not disclosed'
}

#: Fail-open: a broken/unreachable classifier must still let the keyword path run,
#: and the injected text must say the semantic half was unavailable.
$env:CODEX_CLASSIFY_STUB = (Join-Path $env:TEMP ('codex-hook-stub-missing-' + [guid]::NewGuid().ToString('N') + '.json'))
$r = Invoke-HookCommand $commands.UserPromptSubmit $designEvent
$fallbackOk = $false
try { $fallbackJson = $r.Stdout | ConvertFrom-Json; $fallbackOk = $true } catch { }
Assert-True 'semantic: classifier failure still exits 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode)
if ($fallbackOk) {
    $ctx = $fallbackJson.hookSpecificOutput.additionalContext
    Assert-True 'semantic: failure falls back to the keyword path' `
        ($ctx -and $ctx.Contains($reuseMarker)) 'keyword path lost when the classifier failed'
    Assert-True 'semantic: the failure is disclosed in the note' `
        ($ctx -and $ctx.Contains('semantic unavailable')) 'classifier failure is not disclosed'
}
$env:CODEX_CLASSIFY_STUB = '{"kinds":[]}'

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
