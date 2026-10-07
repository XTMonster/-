# Codex PreToolUse guard.
# Blocks (exit 2 + reason on stderr) destructive VCS/filesystem actions and
# any attempt to delete or skip tests instead of making them pass.
# stdin  : PreToolUse event JSON (UTF-8)
# stdout : nothing (silent allow)

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

if (-not $raw) { exit 0 }

$toolName = ''
try {
    $evt = $raw | ConvertFrom-Json
    if ($evt -and $evt.tool_name) { $toolName = [string]$evt.tool_name }
} catch {
    $toolName = ''
}

# --- identity probe (temporary, key names only; no tool arguments) ---------- #
# We need to know whether the PreToolUse event can tell a sub-agent from the
# root thread.  Only NAMES and short identity-ish values are logged - never
# command text - so this stays safe to keep around while we tune the rule.
try {
    if ($evt) {
        $probe = [ordered]@{ ts = (Get-Date).ToString('s'); tool = $toolName; fields = @() }
        foreach ($prop in $evt.PSObject.Properties) {
            $name = [string]$prop.Name
            $value = $prop.Value
            $flat = if ($value -is [string]) { [string]$value } else { $value.GetType().Name }
            if ($flat.Length -gt 80) { $flat = $flat.Substring(0, 80) }
            $probe.fields += ($name + '=' + $flat)
        }
        $line = ($probe | ConvertTo-Json -Depth 3 -Compress)
        $logPath = Join-Path $PSScriptRoot 'guard.log'
        [System.IO.File]::AppendAllText($logPath, $line + "`n", $utf8)
    }
} catch { }

$isPatch = $toolName -match '(?i)patch|edit|write|delete'

# --- no-grandchildren rule -------------------------------------------------- #
# User ruling (2026-10-07): a SUB-AGENT must never be allowed to spawn another
# agent.  Observed on 2026-10-07: spawned agents started
# dispatching their own children, which then fought over the same files, mutated
# the dispatch-board state markers of cards nobody was working, and wandered off
# into other task cards.  Dispatch authority belongs to the root thread only.
#
# How the caller is identified: the PreToolUse payload carries `agent_id` and
# `agent_type` for sub-agent turns and carries NEITHER for the root thread
# (verified against real payloads: 4 sub-agent events had agent_id, 2 root
# events did not).  Anything that looks like a sub-agent is blocked from the
# agent-spawning tools; the root thread is unaffected.
$agentId = ''
$agentType = ''
if ($evt) {
    if ($evt.agent_id) { $agentId = [string]$evt.agent_id }
    if ($evt.agent_type) { $agentType = [string]$evt.agent_type }
}
$isSubAgent = [bool]($agentId -or $agentType)
#: NOTE ON THE NAME: the app hands this hook the tool name with the namespace
#: glued on and the separator dropped - a real payload was literally
#: `tool_name=collaborationspawn_agent` (likewise `collaborationlist_agents`,
#: `collaborationinterrupt_agent`).  So "collaboration" must be an OPTIONAL
#: prefix with no required separator, and the match is anchored on
#: non-identifier boundaries so `interrupt_agent` / `list_agents` stay allowed.
$spawnToolPattern = '(?i)(^|[^A-Za-z0-9_])(collaboration)?(spawn_agent|agent_spawn|spawn_subagent|spawn_sub_agent|followup_task|follow_up_task)([^A-Za-z0-9_]|$)'
$violations = @()
if ($isSubAgent -and ($toolName -match $spawnToolPattern)) {
    $violations += ('sub-agent "' + $agentId + '" attempted to dispatch another agent via ' + $toolName)
}

$testPathPattern = '(?i)(^|[\\/\s"''=:(])(tests?|specs?)([\\/\s"''*),]|$)|test_[A-Za-z0-9_]*\.py|_test\.py|conftest\.py|\.spec\.[A-Za-z]+|\.test\.[A-Za-z]+'
$deleteVerbPattern = '(?i)(^|[\s;&|("''])(rm|del|erase|remove-item|ri|mv|move|move-item|ren|rename-item)(\s|$)'
$gitDeleteVerbPattern = '(?i)\bgit\s+rm\b'
$pytestSkipPattern = '(?i)(--deselect|--ignore[=\s]|--skip([=\s]|$)|-k\s*[=\s]\s*\\?["'']?not\b|x(|e)it\(|\.skip\(|mark\.skip)'
$pytestBinaryPattern = '(?i)\b(pytest|run_tests|run-tests)\b'
$gitDestructivePatterns = @(
    @{ Name = 'git reset --hard';                Pattern = '(?i)\bgit\b[^\r\n]*\breset\b[^\r\n]*--hard' },
    @{ Name = 'git checkout -- / git restore';    Pattern = '(?i)\bgit\b[^\r\n]*\b(checkout\s+--|checkout\s+\.(\s|$)|restore\s+(-s\s|--source|--worktree|--staged|\.(\s|$)))' },
    @{ Name = 'git clean -f';                     Pattern = '(?i)\bgit\b[^\r\n]*\bclean\b[^\r\n]*-\w*f' },
    @{ Name = 'git stash drop/clear';             Pattern = '(?i)\bgit\b[^\r\n]*\bstash\b[^\r\n]*\b(drop|clear)\b' },
    @{ Name = 'git push --force';                 Pattern = '(?i)\bgit\b[^\r\n]*\bpush\b[^\r\n]*(--force|--force-with-lease|\s-f(\s|$))' },
    @{ Name = 'git branch -D';                    Pattern = '(?i)\bgit\b[^\r\n]*\bbranch\b[^\r\n]*\s-D(\s|$)' },
    @{ Name = 'git commit --no-verify';           Pattern = '(?i)\bgit\b[^\r\n]*\bcommit\b[^\r\n]*(--no-verify|\s-n(\s|$))' }
)

$lines = $raw -split "`n|\\n"

if ($isPatch) {
    foreach ($line in $lines) {
        if ($line -match '(?i)^\s*[*]{3}\s*Delete File:\s*(.+?)\s*$') {
            $target = $Matches[1]
            if ($target -match $testPathPattern) {
                $violations += "delete of test file via patch ($target)"
            }
        }
    }
} else {
    foreach ($line in $lines) {
        if ($line -match $testPathPattern) {
            if ($line -match $deleteVerbPattern -or $line -match $gitDeleteVerbPattern) {
                $violations += 'deleting or moving test files'
            }
        }
        if ($line -match $pytestBinaryPattern -and $line -match $pytestSkipPattern) {
            $violations += 'running tests with skip/deselect/ignore flags'
        }
        foreach ($rule in $gitDestructivePatterns) {
            if ($line -match $rule.Pattern) {
                $violations += $rule.Name
            }
        }
    }
}

if ($violations.Count -gt 0) {
    $unique = $violations | Select-Object -Unique
    #: Leave a one-line audit trail of what was denied (name + reason only).
    #: "the guard blocked it" must be checkable after the fact, not inferred.
    try {
        $audit = [ordered]@{ ts = (Get-Date).ToString('s'); tool = $toolName
                             agent_id = $agentId; agent_type = $agentType
                             blocked = @($unique) }
        [System.IO.File]::AppendAllText((Join-Path $PSScriptRoot 'guard.log'),
            ('DENY ' + ($audit | ConvertTo-Json -Depth 3 -Compress) + "`n"), $utf8)
    } catch { }
    $reason = 'BLOCKED by Codex PreToolUse guard: ' + ($unique -join '; ') + '. ' +
              'The user workflow contract forbids deleting/skipping/weakening tests, ' +
              'destructive git history operations, and other destructive actions without explicit approval. ' +
              'It also forbids a SUB-AGENT from dispatching another agent: dispatch authority belongs to the ' +
              'root thread only (a spawned child that spawns its own children fights over the same files and ' +
              'corrupts the dispatch-board state). Do the work yourself, or report back to the root thread. ' +
              'Fix the underlying failure instead, or ask the user for explicit approval.'
    $deny = [ordered]@{
        decision           = 'block'
        reason             = $reason
        hookSpecificOutput = [ordered]@{
            hookEventName            = 'PreToolUse'
            permissionDecision       = 'deny'
            permissionDecisionReason = $reason
        }
    }
    $denyJson = $deny | ConvertTo-Json -Depth 5 -Compress
    $outStream = [Console]::OpenStandardOutput()
    $writer = New-Object System.IO.StreamWriter($outStream, $utf8)
    $writer.Write($denyJson)
    $writer.Flush()
    exit 0
}

exit 0
