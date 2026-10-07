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
. (Join-Path $root 'selected-model.ps1')

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
# execution inherits the user's currently selected model). Injected on all events, so
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
    @{ Kind = 'verdict'; Roles = '\u9886\u57df\u8bb2\u89e3,\u89c4\u683c\u4e00\u81f4\u6027'
       Pattern = '(\u88c1\u51b3|\u88c1\u5b9a|\u4eba\u5de5\u5ba1\u6838|\u4eba\u5ba1|\u7ec8\u5ba1|\u4eba\u5de5\u5224\u65ad|verdict|adjudicat)' },
    @{ Kind = 'hard';   Roles = '\u9886\u57df\u8bb2\u89e3,\u7ea2\u961f\u53cd\u65b9,\u5b9e\u73b0\u987e\u95ee'
       Pattern = '(\u96be\u9898|\u5361\u4f4f|\u963b\u585e|\u4e3a\u4ec0\u4e48|\u8bca\u65ad|\u6392\u67e5|\u6b7b\u7ed3|\u6839\u56e0|\u62a5\u9519|\u5d29\u6e83|\u7591\u96be|stuck|blocker|root cause|diagnose|deadlock)' },
    @{ Kind = 'review'; Roles = '\u6d4b\u8bd5\u4e0e\u9a8c\u6536,\u89c4\u683c\u4e00\u81f4\u6027'
       Pattern = '(\u5ba1\u67e5|\u5ba1\u6838|\u590d\u6838|\u9a8c\u6536|\u5bf9\u6297|\u590d\u7b97|\u6821\u9a8c|review|audit|verify|cross-check)' },
    @{ Kind = 'idea';   Roles = '\u9886\u57df\u8bb2\u89e3,\u5b9e\u73b0\u987e\u95ee'
       Pattern = '(\u65b9\u6848|\u53d6\u820d|\u6743\u8861|\u601d\u8def|\u67b6\u6784|\u600e\u4e48\u505a|\u8bbe\u8ba1|\u89c4\u5212|\u8ba1\u5212|\u6267\u884c\u6587\u6863|\u91cd\u6784|\u9009\u578b|design|approach|tradeoff)' }
)

$promptText = ''
if ($raw) {
    try { $promptText = Get-EventText $evt } catch { $promptText = '' }
}

$REUSE_PATTERN = '(\u8bbe\u8ba1|\u89c4\u5212|\u8ba1\u5212|\u6267\u884c\u6587\u6863|\u67b6\u6784|\u7a0b\u5e8f|\u5b9e\u73b0|\u91cd\u6784|\u9009\u578b|\u6846\u67b6|\u4f9d\u8d56|\u590d\u7528|\u73b0\u6210|\u5f00\u6e90|\u7b2c\u4e09\u65b9|\u8f6e\u5b50|\u9b54\u6539|\u79fb\u690d|\u6539\u9020|\u4e8c\u6b21\u5f00\u53d1|design|plan|architect|refactor|library|framework|dependency|upstream|github|fork|vendor|patch)'

#: "Write me an execution plan / spec document" (2026-10-05).  High-precision
#: keywords only -- the semantic classifier catches the paraphrase tail.  A plan
#: request is also a design request, so the GitHub reuse check fires with it.
$PLAN_PATTERN = '(\u6267\u884c\u8ba1\u5212|\u8ba1\u5212\u4e66|\u5f00\u53d1\u8ba1\u5212|\u6280\u672f\u65b9\u6848|\u8bbe\u8ba1\u6587\u6863|\u9700\u6c42\u6587\u6863|\u5b9e\u65bd\u65b9\u6848|\u8def\u7ebf\u56fe|\u91cc\u7a0b\u7891|\u6392\u671f|\u4efb\u52a1\u62c6\u89e3|prd|roadmap|milestone|tdd)'

# Repair ladder (user 2026-10-06): the SAME problem escalates by attempt count --
# 1st = current model alone, 2nd = + GLM-5.3 low, 3rd+ = + GLM-5.3 high.
# External relay is opt-in only. The key is supplied
# by the agent as `repair-key: <slug>` (add ` done` to reset).  ASCII-only on purpose.
$REPAIR_KEY_PATTERN = '(?i)repair-key\s*[:=]\s*([A-Za-z0-9_.\-]{2,64})'
$REPAIR_DONE_PATTERN = '(?i)repair-key\s*[:=]\s*[A-Za-z0-9_.\-]{2,64}\s+done'
$REPAIR_STATE = Join-Path $PSScriptRoot '.repair-ladder.json'

# --------------------------------------------------------------------------- #
# Request classification: keywords (fast, deterministic, no network) UNION one
# selected-session-model call (semantic). The semantic call is strictly
# budgeted: 8 s socket timeout inside a 20 s hook budget, and on ANY failure the
# hook falls back to keywords alone -- a classifier must never break a turn.
# CODEX_CLASSIFY_STUB=<file with {"kinds":[...]}> replaces the network call, so
# the offline selftest can drive both paths without a key.
# ASCII-only (PowerShell 5.1 reads a BOM-less UTF-8 .ps1 as ANSI): the Chinese
# side of the classifier lives in classify-prompt.md (read as UTF-8).
# --------------------------------------------------------------------------- #
function Get-KeywordKinds([string]$text) {
    $found = @()
    $hits = @()
    if ($text) {
        foreach ($candidate in $CONSULT_TRIGGERS) {
            $match = [regex]::Matches($text, $candidate.Pattern, 'IgnoreCase')
            if ($match.Count -gt 0) {
                $found += $candidate.Kind
                $hits += (($match | ForEach-Object { $_.Value }) | Select-Object -Unique)
            }
        }
        $reuse = [regex]::Matches($text, $REUSE_PATTERN, 'IgnoreCase')
        if ($reuse.Count -gt 0) {
            $found += 'design'
            $hits += (($reuse | ForEach-Object { $_.Value }) | Select-Object -Unique)
        }
        $plan = [regex]::Matches($text, $PLAN_PATTERN, 'IgnoreCase')
        if ($plan.Count -gt 0) {
            $found += 'plan'
            $hits += (($plan | ForEach-Object { $_.Value }) | Select-Object -Unique)
        }
    }
    return @{ Kinds = @($found | Select-Object -Unique)
              Hits  = @($hits | Select-Object -Unique) }
}

function Invoke-PromptClassify([string]$text) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    if (-not $text -or $text.Trim().Length -lt 4) {
        return @{ Ok = $false; Kinds = @(); Ms = 0; Error = 'prompt too short' }
    }
    if ($env:CODEX_CLASSIFY_STUB) {
        try {
            #: The stub is either inline JSON (starts with "{", keeps the selftest
            #: hermetic with no temp files) or a path to a JSON file.
            $rawStub = [string]$env:CODEX_CLASSIFY_STUB
            if ($rawStub.TrimStart().StartsWith('{')) {
                $stub = $rawStub | ConvertFrom-Json
            } else {
                #: $ErrorActionPreference is 'Continue', so a missing file is a
                #: NON-terminating error: without this guard the pipe yields $null
                #: and the stub silently looks like "no kinds" (a false success).
                if (-not (Test-Path -LiteralPath $rawStub)) { throw 'stub file missing' }
                $stub = (Get-Content -LiteralPath $rawStub -Raw -ErrorAction Stop) |
                        ConvertFrom-Json
            }
            if (-not $stub) { throw 'stub empty' }
            return @{ Ok = $true; Kinds = @($stub.kinds | ForEach-Object { [string]$_ })
                      Ms = 0; Error = '' }
        } catch {
            return @{ Ok = $false; Kinds = @(); Ms = 0; Error = 'stub unreadable' }
        }
    }
    $configRoot = Join-Path $env:USERPROFILE '.codex'
    if ($env:CODEX_HOME) { $configRoot = $env:CODEX_HOME }
    $configPath = Join-Path $configRoot 'config.toml'
    $configText = ''
    if (Test-Path -LiteralPath $configPath) {
        $configText = [System.IO.File]::ReadAllText($configPath, $utf8)
    }
    $route = Resolve-SelectedModelRoute -HookEvent $evt -ConfigText $configText
    if (-not $route.Ok) {
        return @{ Ok = $false; Kinds = @(); Ms = 0; Error = $route.Error }
    }
    $instructions = Get-ContractText 'classify-prompt.md'
    if (-not $instructions) {
        return @{ Ok = $false; Kinds = @(); Ms = 0; Error = 'classify-prompt.md missing' }
    }
    $request = New-SelectedModelRequest -Route $route -Instructions $instructions -PromptText $text
    $url = $request.Url
    $body = $request.Body | ConvertTo-Json -Depth 8 -Compress
    $client = $null
    $handler = $null
    $payload = $null
    $response = $null
    try {
        #: Do NOT use Invoke-RestMethod here: PowerShell 5.1 decodes the body with
        #: the charset from Content-Type, and this endpoint omits it -> Latin-1 ->
        #: Chinese turns into mojibake and ConvertFrom-Json dies with
        #: "Invalid JSON primitive".  Read the raw bytes and decode UTF-8 ourselves.
        Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
        $handler = New-Object System.Net.Http.HttpClientHandler
        $handler.AllowAutoRedirect = $false
        $client = New-Object System.Net.Http.HttpClient($handler)
        $client.Timeout = [System.TimeSpan]::FromSeconds(8)
        $client.DefaultRequestHeaders.TryAddWithoutValidation(
            'Authorization', ("Bearer " + $route.ApiKey)) | Out-Null
        $client.DefaultRequestHeaders.TryAddWithoutValidation(
            'User-Agent', 'Mozilla/5.0 CodexHook/1.0') | Out-Null
        $payload = New-Object System.Net.Http.StringContent(
            $body, [System.Text.Encoding]::UTF8, 'application/json')
        $response = $client.PostAsync($url, $payload).GetAwaiter().GetResult()
        $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
        if (-not $response.IsSuccessStatusCode) {
            return @{ Ok = $false; Kinds = @()
                      Ms = [int]$watch.Elapsed.TotalMilliseconds
                      Error = ('selected model HTTP ' + [int]$response.StatusCode) }
        }
        $content = Get-SelectedModelResponseText -WireApi $route.WireApi -ResponseBody $text
        $content = ($content -replace '(?s)^\s*```(json)?', '' -replace '(?s)```\s*$', '').Trim()
        #: Belt and braces: take the first balanced-looking {...} even if the model
        #: wrapped it in prose.  (JSON mode makes this rare, not impossible.)
        if ($content -notmatch '^\s*\{') {
            $open = $content.IndexOf('{')
            $close = $content.LastIndexOf('}')
            if ($open -ge 0 -and $close -gt $open) {
                $content = $content.Substring($open, $close - $open + 1)
            }
        }
        $verdict = $content | ConvertFrom-Json -ErrorAction Stop
        if (-not $verdict -or -not ($verdict.PSObject.Properties.Name -contains 'kinds') -or
            $verdict.kinds -isnot [array]) {
            throw 'selected model classification missing kinds array'
        }
        foreach ($kind in $verdict.kinds) {
            if ($kind -notin @('design', 'idea', 'review', 'hard', 'plan', 'verdict')) {
                throw 'selected model classification has an unknown kind'
            }
        }
        return @{ Ok = $true; Kinds = @($verdict.kinds | ForEach-Object { [string]$_ })
                  Ms = [int]$watch.Elapsed.TotalMilliseconds; Error = '' }
    } catch {
        return @{ Ok = $false; Kinds = @()
                  Ms = [int]$watch.Elapsed.TotalMilliseconds
                  Error = ('selected model request or response failed: ' + $_.Exception.GetType().Name) }
    } finally {
        if ($response) { $response.Dispose() }
        if ($payload) { $payload.Dispose() }
        if ($client) { $client.Dispose() }
        elseif ($handler) { $handler.Dispose() }
    }
}

function Write-ClassifyLog($record) {
    #: One JSONL line per prompt; NO prompt text (only length) -- it is a hook log.
    try {
        $path = Join-Path $root 'classify.log'
        $line = ($record | ConvertTo-Json -Compress -Depth 5)
        [System.IO.File]::AppendAllText($path, $line + "`n", $utf8)
    } catch {
        #: logging must never break the hook
    }
}

$keyword = Get-KeywordKinds $promptText
$semantic = Invoke-PromptClassify $promptText

$kinds = @($keyword.Kinds)
if ($semantic.Ok) { $kinds += $semantic.Kinds }
$kinds = @($kinds | Where-Object { $_ } | Select-Object -Unique)

#: A plan request is by definition design + idea: it must carry the GitHub reuse
#: check and (per the routing contract) the two-sided panel as well.
if ($kinds -contains 'plan') {
    if (-not ($kinds -contains 'design')) { $kinds += 'design' }
    if (-not ($kinds -contains 'idea')) { $kinds += 'idea' }
}

$sourceNote = 'keyword'
if ($semantic.Ok) {
    $sourceNote = 'keyword+semantic'
    if (-not $keyword.Kinds -and -not $semantic.Kinds) { $sourceNote = 'both: none' }
    elseif (-not $keyword.Kinds) { $sourceNote = 'semantic' }
    elseif (-not $semantic.Kinds) { $sourceNote = 'keyword (semantic: none)' }
} else {
    $why = [string]$semantic.Error
    if ($why.Length -gt 40) { $why = $why.Substring(0, 40) }
    $sourceNote = 'keyword (semantic unavailable: ' + $why + ')'
}

$hits = @($keyword.Hits)
if ($semantic.Ok) { $hits += @($semantic.Kinds | ForEach-Object { 'semantic:' + $_ }) }
$hitsText = (($hits | Where-Object { $_ } | Select-Object -Unique |
              Select-Object -First 8) -join '/')
if (-not $hitsText) { $hitsText = 'none' }
$hitsText = $hitsText + ' [source=' + $sourceNote + '; semantic_ms=' + $semantic.Ms + ']'

$consultKind = $null
foreach ($kind in @('hard', 'review', 'idea')) {
    if ($kinds -contains $kind) { $consultKind = $kind; break }
}
if ($consultKind) {
    $template = Get-ContractText 'consult-trigger.md'
    if ($template) {
        $roles = ($CONSULT_TRIGGERS | Where-Object { $_.Kind -eq $consultKind }).Roles
        $tick = [char]96
        $paths = @([regex]::Matches(
            $promptText,
            '[A-Za-z0-9_\-./\\]+\.(py|md|json|jsonl|ps1|ya?ml|toml)') |
            ForEach-Object { $_.Value } | Select-Object -Unique | Select-Object -First 6)
        $sourceLines = ''
        foreach ($item in $paths) {
            $sourceLines += '    --source ' + $item + ' ' + $tick + "`n"
        }
        if (-not $sourceLines) {
            $sourceLines = '    --source <file:start-end> ' + $tick + "`n"
        }
        $parts += $template.Replace('{{KIND}}', $consultKind).
                            Replace('{{HITS}}', $hitsText).
                            Replace('{{ROLES}}', [string]$roles).
                            Replace('{{SOURCES}}', $sourceLines).
                            Replace('{{SLUG}}', $consultKind)
    }
}

if ($kinds -contains 'design') {
    $reuseTemplate = Get-ContractText 'github-reuse.md'
    if ($reuseTemplate) {
        $parts += $reuseTemplate.Replace('{{HITS}}', $hitsText)
    }
}

if ($kinds -contains 'plan') {
    $planTemplate = Get-ContractText 'plan-contract.md'
    if ($planTemplate) {
        $parts += $planTemplate.Replace('{{HITS}}', $hitsText)
    }
}

# Repair ladder: current model / +GLM-5.3 low / +GLM-5.3 high.
# The key travels in the prompt as `repair-key: <slug>`; `... done` resets.
if ($promptText) {
    try {
        $keyMatch = [regex]::Match($promptText, $REPAIR_KEY_PATTERN)
        if ($keyMatch.Success) {
            $repairKey = $keyMatch.Groups[1].Value.ToLower()
            $repairState = @{}
            if (Test-Path $REPAIR_STATE) {
                $rawState = Get-Content -Raw -Encoding UTF8 $REPAIR_STATE
                if ($rawState -and $rawState.Trim()) {
                    $parsedState = $rawState | ConvertFrom-Json
                    foreach ($prop in $parsedState.PSObject.Properties) {
                        $repairState[$prop.Name] = [int]$prop.Value
                    }
                }
            }
            $attempts = 1
            if ([regex]::IsMatch($promptText, $REPAIR_DONE_PATTERN)) {
                if ($repairState.ContainsKey($repairKey)) { $repairState.Remove($repairKey) }
                $attempts = 0
            } else {
                if ($repairState.ContainsKey($repairKey)) {
                    $attempts = [int]$repairState[$repairKey] + 1
                }
                $repairState[$repairKey] = $attempts
            }
            ($repairState | ConvertTo-Json) | Set-Content -Path $REPAIR_STATE -Encoding UTF8
            if ($attempts -ge 1) {
                $ladder = Get-ContractText 'repair-ladder.md'
                if ($ladder) {
                    $s1 = ' '; $s2 = ' '; $s3 = ' '
                    if ($attempts -eq 1) { $s1 = 'x' }
                    elseif ($attempts -eq 2) { $s2 = 'x' }
                    else { $s3 = 'x' }
                    $parts += $ladder.Replace('{{ATTEMPTS}}', [string]$attempts).
                                      Replace('{{KEY}}', $repairKey).
                                      Replace('{{S1}}', $s1).
                                      Replace('{{S2}}', $s2).
                                      Replace('{{S3}}', $s3)
                }
            }
        }
    } catch { }
}

# Human verdict (2026-10-06, corrected 2026-10-08): the user delegated "stand in for my
# human review" to the third-party adjudication channel.  That channel is GLM-5.3 by
# DEFAULT.  The user explicitly said NOT to use the relay GPT-6A any more, so relay is
# opt-in only (spell it out with --partner relay / --provider relay when asked by name).
# Inject the rule explicitly so it does not depend on anyone remembering it.
# NOTE: this file MUST stay ASCII-only (PS 5.1 reads BOM-less UTF-8 as ANSI).
if ($kinds -contains 'verdict') {
    $verdictTemplate = Get-ContractText 'verdict-rule.md'
    if ($verdictTemplate) {
        $parts += $verdictTemplate.Replace('{{HITS}}', $hitsText)
    }
}

Write-ClassifyLog ([ordered]@{
    ts           = (Get-Date).ToString('s')
    prompt_chars = $promptText.Length
    source       = $sourceNote
    kinds        = @($kinds)
    keyword      = @($keyword.Kinds)
    semantic     = @($semantic.Kinds)
    semantic_ms  = $semantic.Ms
    semantic_ok  = [bool]$semantic.Ok
    model        = [string]$evt.model
    error        = [string]$semantic.Error
})

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
