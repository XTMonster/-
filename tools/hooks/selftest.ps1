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
$skillsMarker = First-Line (Join-Path $root 'mattpocock-skills.md')

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
    Assert-True 'session-start injects the mattpocock skills contract' `
        ($ctx -and $ctx.Contains($skillsMarker)) 'missing mattpocock skills contract'
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
    Assert-True 'prompt-submit injects the mattpocock skills contract' `
        ($ctx -and $ctx.Contains($skillsMarker)) 'missing mattpocock skills contract'
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
    #: GLM consultation removed (user ruling 2026-10-10): a hard prompt must NOT
    #: inject the panel block any more.
    Assert-True 'trigger: hard prompt no longer pulls the GLM panel' `
        ($ctx -and (-not $ctx.Contains('--out work/_panel_')) -and
         (-not $ctx.Contains('tools/glm_consult.py --roles'))) 'consultation block still injected'
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
    Assert-True 'trigger: review prompt no longer pulls the GLM panel' `
        ($ctx -and (-not $ctx.Contains('--out work/_panel_'))) 'consultation block still injected'
}

$ideaEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $tradeWord +
    ' build_cases.py","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $ideaEvent
$ideaOk = $false
try { $ideaJson = $r.Stdout | ConvertFrom-Json; $ideaOk = $true } catch { }
if ($ideaOk) {
    $ctx = $ideaJson.hookSpecificOutput.additionalContext
    Assert-True 'trigger: idea prompt no longer pulls the GLM panel' `
        ($ctx -and (-not $ctx.Contains('--out work/_panel_'))) 'consultation block still injected'
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
$requirementFirst = From-CodePoints @(0x9700, 0x6c42, 0x4f18, 0x5148)               # "requirements come first"
$upstreamOnly = From-CodePoints @(0x53ea, 0x6539, 0x4e0a, 0x6e38)                    # "only the upstream gets modified"
$ambiguousLabel = From-CodePoints @(0x6539, 0x4e00, 0x6bb5, 0x80fd, 0x6ee1, 0x8db3) # the old, ambiguous label
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
    Assert-True 'reuse: design prompt no longer pulls the GLM panel' `
        ($ctx -and (-not $ctx.Contains('--out work/_panel_'))) 'consultation block still injected'
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
    Assert-True 'reuse: remix is requirement-driven' `
        ($ctx -and $ctx.Contains($requirementFirst)) 'the requirement-first rule is missing'
    Assert-True 'reuse: the four buckets say which side gets modified' `
        ($ctx -and $ctx.Contains($upstreamOnly)) 'the "only the upstream is modified" wording is missing'
    Assert-True 'reuse: the ambiguous bucket label is gone' `
        ($ctx -and (-not $ctx.Contains($ambiguousLabel))) 'the ambiguous label is still shipped'
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
    Assert-True 'semantic: idea verdict no longer pulls the GLM panel' `
        ($ctx -and (-not $ctx.Contains('--out work/_panel_'))) 'consultation block still injected'
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

Write-Host 'Execution-plan contract (PRD + TDD + design doc)'

#: A request to WRITE a plan must pull three blocks at once: the plan template,
#: the GitHub reuse check (a plan is a design act) and the two-sided panel.
$planWord = From-CodePoints @(0x6267, 0x884c, 0x8ba1, 0x5212)      # "execution plan"
$userNeed = From-CodePoints @(0x7528, 0x6237, 0x9700, 0x6c42)      # "user requirement"
$execOrder = From-CodePoints @(0x6267, 0x884c, 0x987a, 0x5e8f)     # "execution order"
$ambiguity = From-CodePoints @(0x6b67, 0x4e49)                     # "ambiguity"
$literature = From-CodePoints @(0x6587, 0x732e)                    # "literature"
$selfRefine = From-CodePoints @(0x81ea, 0x6211, 0x7cbe, 0x70bc)    # "self-refine"
$planMarker = First-Line (Join-Path $root 'plan-contract.md')

$planEvent = '{"hook_event_name":"UserPromptSubmit","prompt":"' + $planWord +
    ' for the knowledge layer","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $planEvent
$planOk = $false
try { $planJson = $r.Stdout | ConvertFrom-Json; $planOk = $true } catch { }
Assert-True 'plan: request stdout is json' $planOk $r.Stdout
if ($planOk) {
    $ctx = $planJson.hookSpecificOutput.additionalContext
    Assert-True 'plan: request pulls the plan contract' `
        ($ctx -and $ctx.Contains($planMarker)) 'plan contract missing'
    Assert-True 'plan: a plan is also a design act (reuse check fires)' `
        ($ctx -and $ctx.Contains($reuseMarker)) 'reuse check missing for a plan request'
    Assert-True 'plan: a plan no longer pulls the GLM panel' `
        ($ctx -and (-not $ctx.Contains('--out work/_panel_'))) 'consultation block still injected'
    Assert-True 'plan: contract demands the user requirement' `
        ($ctx -and $ctx.Contains($userNeed)) 'user-requirement section missing'
    Assert-True 'plan: contract demands the execution order' `
        ($ctx -and $ctx.Contains($execOrder)) 'execution-order section missing'
    Assert-True 'plan: contract demands PRD' ($ctx -and $ctx.Contains('PRD')) 'PRD section missing'
    Assert-True 'plan: contract demands TDD' ($ctx -and $ctx.Contains('TDD')) 'TDD section missing'
    Assert-True 'plan: contract demands ambiguity control' `
        ($ctx -and $ctx.Contains($ambiguity)) 'ambiguity-control section missing'
    Assert-True 'plan: contract demands sources' `
        ($ctx -and $ctx.Contains($literature)) 'sources section missing'
    Assert-True 'plan: contract routes drafting through GLM-5.3' `
        ($ctx -and $ctx.Contains('plan_writer.py')) 'the GLM-5.3 plan writer is missing'
    Assert-True 'plan: contract demands five self-refinement rounds' `
        ($ctx -and $ctx.Contains($selfRefine)) 'the self-refinement rule is missing'
}

$r = Invoke-HookCommand $commands.UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"hi","session_id":"s1"}'
$noPlanOk = $false
try { $noPlanJson = $r.Stdout | ConvertFrom-Json; $noPlanOk = $true } catch { }
if ($noPlanOk) {
    $ctx = $noPlanJson.hookSpecificOutput.additionalContext
    Assert-True 'plan: a plain prompt stays free of the plan contract' `
        ($ctx -and (-not $ctx.Contains($planMarker))) 'plan contract leaked into a plain prompt'
}

Write-Host 'Dispatch ladder (UserPromptSubmit)'

#: Two root rejections of the same card -> the root implements the third
#: attempt itself. CODEX_DISPATCH_STATE points the hook at a temp state file,
#: so the user's real .dispatch-ladder.json counters are never touched.
$dispatchStatePath = Join-Path $env:TEMP ('codex-hook-dispatch-' + [guid]::NewGuid().ToString('N') + '.json')
$env:CODEX_DISPATCH_STATE = $dispatchStatePath
$dispatchMarker = 'dispatch-ladder: root takes over'
$twiceWord = From-CodePoints @(0x5df2, 0x88ab, 0x4e3b, 0x7ebf, 0x5426, 0x51b3)   # "already rejected by the root"

$dReject1 = '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-a rejected (evidence: rendered frame f0123.png)","session_id":"s1","model":"model-under-test-42"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $dReject1
Assert-True 'dispatch: first rejection exits 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$d1Ok = $false
try { $d1Json = $r.Stdout | ConvertFrom-Json; $d1Ok = $true } catch { }
Assert-True 'dispatch: first rejection stdout is json' $d1Ok $r.Stdout
if ($d1Ok) {
    $ctx = $d1Json.hookSpecificOutput.additionalContext
    Assert-True 'dispatch: first rejection stays a status line (no take-over block)' `
        ($ctx -and (-not $ctx.Contains($dispatchMarker))) 'take-over block appeared after one rejection'
    Assert-True 'dispatch: first rejection reports count 1' `
        ($ctx -and $ctx.Contains('card-a rejections=1')) $ctx
    Assert-True 'dispatch: first rejection says the next attempt is DeepSeek' `
        ($ctx -and $ctx.Contains('next attempt: DeepSeek')) $ctx
}

$dReject2 = '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-a rejected (second try still wrong)","session_id":"s1","model":"model-under-test-42"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $dReject2
Assert-True 'dispatch: second rejection exits 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$d2Ok = $false
try { $d2Json = $r.Stdout | ConvertFrom-Json; $d2Ok = $true } catch { }
Assert-True 'dispatch: second rejection stdout is json' $d2Ok $r.Stdout
if ($d2Ok) {
    $ctx = $d2Json.hookSpecificOutput.additionalContext
    Assert-True 'dispatch: second rejection injects the take-over block' `
        ($ctx -and $ctx.Contains($dispatchMarker)) 'take-over block missing at two rejections'
    Assert-True 'dispatch: take-over block names the card' `
        ($ctx -and $ctx.Contains('card-a')) $ctx
    Assert-True 'dispatch: take-over block shows count 2' `
        ($ctx -and $ctx.Contains($twiceWord + ' 2 ')) $ctx
    Assert-True 'dispatch: take-over block shows the session model' `
        ($ctx -and $ctx.Contains('model-under-test-42')) $ctx
}

$dAccept = '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-a accepted (verified)","session_id":"s1","model":"model-under-test-42"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $dAccept
Assert-True 'dispatch: accepted exits 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$acceptOk = $false
try { $acceptJson = $r.Stdout | ConvertFrom-Json; $acceptOk = $true } catch { }
Assert-True 'dispatch: accepted stdout is json' $acceptOk $r.Stdout
$stateAfterAccept = $null
try { $stateAfterAccept = Get-Content -Raw -Encoding UTF8 $dispatchStatePath | ConvertFrom-Json } catch { }
Assert-True 'dispatch: accepted resets the card to 0' `
    ($stateAfterAccept -and (-not ($stateAfterAccept.PSObject.Properties.Name -contains 'card-a'))) `
    (Get-Content -LiteralPath $dispatchStatePath -Raw -ErrorAction SilentlyContinue)
if ($acceptOk) {
    $ctx = $acceptJson.hookSpecificOutput.additionalContext
    Assert-True 'dispatch: accepted injection reports 0' `
        ($ctx -and $ctx.Contains('card-a rejections=0')) $ctx
}

#: `done` is the second reset word: seed one rejection, then reset it.
$dDoneSeed = '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-d rejected","session_id":"s1","model":"model-under-test-42"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $dDoneSeed | Out-Null
$r = Invoke-HookCommand $commands.UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-d done","session_id":"s1","model":"model-under-test-42"}'
Assert-True 'dispatch: done exits 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$stateAfterDone = $null
try { $stateAfterDone = Get-Content -Raw -Encoding UTF8 $dispatchStatePath | ConvertFrom-Json } catch { }
Assert-True 'dispatch: done resets the card to 0' `
    ($stateAfterDone -and (-not ($stateAfterDone.PSObject.Properties.Name -contains 'card-d'))) `
    (Get-Content -LiteralPath $dispatchStatePath -Raw -ErrorAction SilentlyContinue)

#: A bare key only reports; it must not create or advance a counter.
$dBare = '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-b","session_id":"s1","model":"model-under-test-42"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $dBare
$bareOk = $false
try { $bareJson = $r.Stdout | ConvertFrom-Json; $bareOk = $true } catch { }
if ($bareOk) {
    $ctx = $bareJson.hookSpecificOutput.additionalContext
    Assert-True 'dispatch: bare key reports count 0' `
        ($ctx -and $ctx.Contains('card-b rejections=0')) $ctx
}
$stateAfterBare = $null
try { $stateAfterBare = Get-Content -Raw -Encoding UTF8 $dispatchStatePath | ConvertFrom-Json } catch { }
Assert-True 'dispatch: bare key does not create a counter' `
    ($stateAfterBare -and (-not ($stateAfterBare.PSObject.Properties.Name -contains 'card-b'))) `
    (Get-Content -LiteralPath $dispatchStatePath -Raw -ErrorAction SilentlyContinue)

#: Without a model field the take-over block must show the ASCII placeholder.
$dFallback1 = '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-c rejected","session_id":"s1"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $dFallback1 | Out-Null
$r = Invoke-HookCommand $commands.UserPromptSubmit '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-c rejected","session_id":"s1"}'
$fallbackOk = $false
try { $fallbackJson = $r.Stdout | ConvertFrom-Json; $fallbackOk = $true } catch { }
Assert-True 'dispatch: model-less take-over stdout is json' $fallbackOk $r.Stdout
if ($fallbackOk) {
    $ctx = $fallbackJson.hookSpecificOutput.additionalContext
    Assert-True 'dispatch: missing model field falls back to the placeholder' `
        ($ctx -and $ctx.Contains('????????????')) $ctx
}

#: A corrupt state file must reset itself, disclose the reset and never crash.
[System.IO.File]::WriteAllText($dispatchStatePath, 'not-json{{{', $utf8NoBom)
$dCorrupt = '{"hook_event_name":"UserPromptSubmit","prompt":"dispatch-key: card-e","session_id":"s1","model":"model-under-test-42"}'
$r = Invoke-HookCommand $commands.UserPromptSubmit $dCorrupt
Assert-True 'dispatch: corrupt state exits 0' ($r.ExitCode -eq 0) ("exit=" + $r.ExitCode + " err=" + $r.Stderr)
$corruptOk = $false
try { $corruptJson = $r.Stdout | ConvertFrom-Json; $corruptOk = $true } catch { }
Assert-True 'dispatch: corrupt state stdout is json' $corruptOk $r.Stdout
if ($corruptOk) {
    $ctx = $corruptJson.hookSpecificOutput.additionalContext
    Assert-True 'dispatch: corrupt state reset is disclosed' `
        ($ctx -and $ctx.Contains('state file was corrupt')) $ctx
    Assert-True 'dispatch: corrupt state report still names the card' `
        ($ctx -and $ctx.Contains('card-e')) $ctx
}
$corruptRepaired = $false
try {
    $stateAfterCorrupt = Get-Content -Raw -Encoding UTF8 $dispatchStatePath | ConvertFrom-Json
    $corruptRepaired = ($stateAfterCorrupt -is [System.Management.Automation.PSCustomObject])
} catch { }
Assert-True 'dispatch: corrupt state file was reset to valid JSON' `
    $corruptRepaired (Get-Content -LiteralPath $dispatchStatePath -Raw -ErrorAction SilentlyContinue)

Remove-Item Env:CODEX_DISPATCH_STATE -ErrorAction SilentlyContinue
$dispatchCleanupOk = $true
try { Remove-Item -LiteralPath $dispatchStatePath -Force -ErrorAction Stop } catch { $dispatchCleanupOk = $false }
Assert-True 'dispatch: temp state cleaned up' `
    ($dispatchCleanupOk -and -not (Test-Path -LiteralPath $dispatchStatePath)) 'temp state file still present'

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

# --- no-grandchildren rule (user ruling 2026-10-07) ------------------------- #
# A sub-agent must never spawn another agent; the root thread still may.
# Sub-agent turns carry agent_id/agent_type in the PreToolUse payload (verified
# against real payloads); the root thread carries neither.
Write-Host 'Guard hook: sub-agents may not dispatch agents'

function New-AgentToolEvent {
    param([string]$ToolName, [string]$AgentId, [string]$AgentType)
    $fields = ',"tool_input":{"x":1},"cwd":"E:\\\\demo"'
    if ($AgentId) { $fields += ',"agent_id":"' + $AgentId + '"' }
    if ($AgentType) { $fields += ',"agent_type":"' + $AgentType + '"' }
    return '{"hook_event_name":"PreToolUse","tool_name":"' + $ToolName + '"' + $fields + '}'
}

function Assert-Blocked([string]$name, [string]$event) {
    $r = Invoke-HookCommand $commands.PreToolUse $event
    $ok = $false
    if ($r.ExitCode -eq 0 -and $r.StdoutBytes -gt 0) {
        try { $j = $r.Stdout | ConvertFrom-Json; $ok = ($j.decision -eq 'block') } catch { }
    }
    Assert-True $name $ok ("exit=" + $r.ExitCode + " out=" + $r.Stdout + " err=" + $r.Stderr)
}

function Assert-Allowed([string]$name, [string]$event) {
    $r = Invoke-HookCommand $commands.PreToolUse $event
    Assert-True $name ($r.ExitCode -eq 0 -and $r.StdoutBytes -eq 0) `
                ("exit=" + $r.ExitCode + " out=" + $r.Stdout + " err=" + $r.Stderr)
}

Assert-Blocked 'sub-agent may not call spawn_agent' `
    (New-AgentToolEvent 'spawn_agent' 'agent-1' 'default')
Assert-Blocked 'sub-agent may not call followup_task' `
    (New-AgentToolEvent 'followup_task' 'agent-1' 'default')
Assert-Blocked 'sub-agent may not call collaboration.spawn_agent' `
    (New-AgentToolEvent 'collaboration.spawn_agent' 'agent-1' 'default')
# The app hands the hook the namespaced name with the separator dropped - this
# is the exact spelling observed in a real payload on 2026-10-07.
Assert-Blocked 'sub-agent may not call collaborationspawn_agent (real name)' `
    (New-AgentToolEvent 'collaborationspawn_agent' 'agent-1' 'default')
Assert-Blocked 'sub-agent may not call collaborationfollowup_task (real name)' `
    (New-AgentToolEvent 'collaborationfollowup_task' 'agent-1' 'default')
Assert-Allowed 'sub-agent may call collaborationinterrupt_agent' `
    (New-AgentToolEvent 'collaborationinterrupt_agent' 'agent-1' 'default')
Assert-Allowed 'sub-agent may call collaborationlist_agents' `
    (New-AgentToolEvent 'collaborationlist_agents' 'agent-1' 'default')
Assert-Blocked 'sub-agent may not call spawn_agent (agent_type only)' `
    (New-AgentToolEvent 'spawn_agent' '' 'worker')
Assert-Allowed 'sub-agent may still run Bash' `
    (New-AgentToolEvent 'Bash' 'agent-1' 'default')
Assert-Allowed 'sub-agent may still apply_patch' `
    (New-AgentToolEvent 'apply_patch' 'agent-1' 'default')
Assert-Allowed 'root thread may call spawn_agent' `
    (New-AgentToolEvent 'spawn_agent' '' '')
Assert-Allowed 'root thread may call followup_task' `
    (New-AgentToolEvent 'followup_task' '' '')

Write-Host 'Transcript provider fallback (Get-TranscriptProvider)'

#: Dot-source the routing module directly: it is functions-only, so it never
#: reads config, starts a process or touches the network. These cases pin the
#: fail-closed transcript read, including a file another process still holds
#: open for writing (Codex keeps the live session transcript open like that).
. (Join-Path $root 'selected-model.ps1')

$transcriptDir = Join-Path $env:TEMP ('codex-hook-transcript-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $transcriptDir -ErrorAction Stop | Out-Null

function New-TranscriptFile([string]$name, [string]$firstLine) {
    $path = Join-Path $transcriptDir $name
    [System.IO.File]::WriteAllText($path, $firstLine + "`n", $utf8NoBom)
    return $path
}

$happyPath = New-TranscriptFile 'happy.jsonl' `
    '{"type":"session_meta","payload":{"id":"s-happy","model_provider":"linkai-claude"}}'
$happyProvider = Get-TranscriptProvider -HookEvent @{
    transcript_path = $happyPath; session_id = 's-happy' }
Assert-True 'transcript: happy path reads the provider' `
    ($happyProvider -eq 'linkai-claude') ('got=' + $happyProvider)

$heldPath = New-TranscriptFile 'held.jsonl' `
    '{"type":"session_meta","payload":{"id":"s-held","model_provider":"linkai-claude"}}'
$holdStream = [System.IO.File]::Open(
    $heldPath,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::ReadWrite)
try {
    $heldProvider = Get-TranscriptProvider -HookEvent @{
        transcript_path = $heldPath; session_id = 's-held' }
} finally {
    if ($holdStream) { $holdStream.Dispose() }
}
Assert-True 'transcript: reads while another handle holds it open for writing' `
    ($heldProvider -eq 'linkai-claude') ('got=' + $heldProvider)

$mismatchPath = New-TranscriptFile 'mismatch.jsonl' `
    '{"type":"session_meta","payload":{"id":"s-other","model_provider":"linkai-claude"}}'
$mismatchProvider = Get-TranscriptProvider -HookEvent @{
    transcript_path = $mismatchPath; session_id = 's-this' }
Assert-True 'transcript: session id mismatch fails closed' `
    ($mismatchProvider -eq '') ('got=' + $mismatchProvider)

$nonMetaPath = New-TranscriptFile 'nonmeta.jsonl' `
    '{"type":"event_msg","payload":{"x":1}}'
$nonMetaProvider = Get-TranscriptProvider -HookEvent @{
    transcript_path = $nonMetaPath; session_id = 's-this' }
Assert-True 'transcript: non-session_meta first line fails closed' `
    ($nonMetaProvider -eq '') ('got=' + $nonMetaProvider)

$missingPath = Join-Path $transcriptDir 'missing.jsonl'
$missingProvider = Get-TranscriptProvider -HookEvent @{
    transcript_path = $missingPath; session_id = 's-this' }
Assert-True 'transcript: missing file fails closed' `
    ($missingProvider -eq '') ('got=' + $missingProvider)

$cleanupOk = $true
try {
    Remove-Item -LiteralPath $transcriptDir -Recurse -Force -ErrorAction Stop
} catch {
    $cleanupOk = $false
}
Assert-True 'transcript: temp files cleaned up' `
    ($cleanupOk -and -not (Test-Path -LiteralPath $transcriptDir)) 'temp dir still present'

Write-Host 'ASCII audit (every .ps1 must be pure ASCII for PowerShell 5.1)'

$asciiOk = $true
$asciiDetail = ''
foreach ($asciiFile in (Get-ChildItem -LiteralPath $root -Filter '*.ps1' -File)) {
    $asciiBytes = [System.IO.File]::ReadAllBytes($asciiFile.FullName)
    for ($i = 0; $i -lt $asciiBytes.Length; $i++) {
        if ($asciiBytes[$i] -gt 127) {
            $asciiOk = $false
            $asciiDetail = ($asciiFile.Name + ' has byte ' + $asciiBytes[$i] + ' at offset ' + $i)
            break
        }
    }
    if (-not $asciiOk) { break }
}
Assert-True 'ascii: all .ps1 files are ASCII-only (no byte > 127)' $asciiOk $asciiDetail

Write-Host ''
Write-Host ("checks: " + $total + "  failures: " + $failures)
if ($failures -gt 0) { exit 1 }
Write-Host 'HOOK SELFTEST PASS'
exit 0
