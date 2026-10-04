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

$isPatch = $toolName -match '(?i)patch|edit|write|delete'

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

$violations = @()

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
    $reason = 'BLOCKED by Codex PreToolUse guard: ' + ($unique -join '; ') + '. ' +
              'The user workflow contract forbids deleting/skipping/weakening tests, ' +
              'destructive git history operations, and other destructive actions without explicit approval. ' +
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
