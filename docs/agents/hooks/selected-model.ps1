# Selected-session-model routing for the semantic hook. ASCII-only for PS 5.1.
# Functions only: dot-sourcing never reads config, starts a process or networks.

function Get-RouteString([string]$Text, [string]$Name) {
    # Read one scalar in the already-selected TOML table, never another table's
    # bearer token. Unsupported/multiline values fail closed instead of guessing.
    $pattern = '(?m)^[ \t]*' + [regex]::Escape($Name) +
        '[ \t]*=[ \t]*("(?:\\.|[^"\\\r\n])*"|''[^''\r\n]*'')[ \t]*(?:#[^\r\n]*)?\r?$'
    $values = [regex]::Matches($Text, $pattern)
    if ($values.Count -ne 1) { return '' }
    $value = $values[0].Groups[1].Value
    if ($value.StartsWith("'")) { return $value.Substring(1, $value.Length - 2) }
    try { return [string]($value | ConvertFrom-Json -ErrorAction Stop) }
    catch { return '' }
}

function Resolve-SelectedModelRoute {
    param($HookEvent, [string]$ConfigText)
    $selectedModel = [string]$HookEvent.model
    if (-not $selectedModel.Trim()) {
        return @{ Ok = $false; Error = 'selected model missing from hook event' }
    }
    $provider = [string]$HookEvent.model_provider
    if (-not $provider) {
        # Hooks do not always expose the effective provider. A global default
        # cannot prove which CLI/profile/session override is currently selected.
        return @{ Ok = $false; Error = 'effective provider missing from hook event' }
    }
    $escaped = [regex]::Escape($provider)
    $header = '(?m)^[ \t]*\[model_providers\.(?:' + $escaped +
        '|"' + $escaped + '"|''' + $escaped + ''')\][ \t]*(?:#[^\r\n]*)?\r?$'
    $section = [regex]::Matches($ConfigText, $header)
    if ($section.Count -ne 1) {
        return @{ Ok = $false; Error = 'selected provider is not configured' }
    }
    $tail = $ConfigText.Substring($section[0].Index + $section[0].Length)
    $table = [regex]::Split($tail, '(?m)^[ \t]*\[')[0]
    $baseUrl = Get-RouteString $table 'base_url'
    $wire = Get-RouteString $table 'wire_api'
    if (-not $wire) { $wire = 'responses' }
    $uri = $null
    if (-not [System.Uri]::TryCreate($baseUrl, [System.UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -notin @('https', 'http') -or
        ($uri.Scheme -eq 'http' -and -not $uri.IsLoopback) -or
        $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
        return @{ Ok = $false; Error = 'selected provider base_url is invalid' }
    }
    if ($wire -notin @('responses', 'chat')) {
        return @{ Ok = $false; Error = 'selected provider wire_api is unsupported' }
    }
    $apiKey = ''
    $envKey = Get-RouteString $table 'env_key'
    if ($envKey) {
        $apiKey = [Environment]::GetEnvironmentVariable($envKey, 'Process')
    } else {
        $apiKey = Get-RouteString $table 'experimental_bearer_token'
    }
    if (-not $apiKey) {
        return @{ Ok = $false; Error = 'selected provider credential unavailable' }
    }
    return @{
        Ok = $true; Error = ''; Model = $selectedModel
        Provider = $provider; BaseUrl = $baseUrl.TrimEnd('/')
        WireApi = $wire; ApiKey = $apiKey
    }
}

function New-SelectedModelRequest {
    param($Route, [string]$Instructions, [string]$PromptText)
    if ($Route.WireApi -eq 'responses') {
        return @{
            Url = $Route.BaseUrl.TrimEnd('/') + '/responses'
            Body = @{
                model = $Route.Model; instructions = $Instructions
                input = $PromptText; stream = $true
                max_output_tokens = 256
                text = @{ format = @{ type = 'json_object' } }
            }
        }
    }
    if ($Route.WireApi -eq 'chat') {
        return @{
            Url = $Route.BaseUrl.TrimEnd('/') + '/chat/completions'
            Body = @{
                model = $Route.Model
                messages = @(@{ role = 'system'; content = $Instructions },
                              @{ role = 'user'; content = $PromptText })
                max_tokens = 256
                response_format = @{ type = 'json_object' }
            }
        }
    }
    throw 'selected provider wire_api is unsupported'
}

function Get-SelectedModelResponseText {
    param([string]$WireApi, [string]$ResponseBody)
    $reply = $null
    if ($ResponseBody.TrimStart().StartsWith('{')) {
        $reply = $ResponseBody | ConvertFrom-Json -ErrorAction Stop
    } else {
        # Only a completed Responses event is a successful streamed response.
        # A delta followed by an error/incomplete event is never a verdict.
        foreach ($line in ($ResponseBody -split '\r?\n')) {
            if (-not $line.StartsWith('data:')) { continue }
            $data = $line.Substring(5).Trim()
            if ($data -eq '[DONE]') { continue }
            $item = $data | ConvertFrom-Json -ErrorAction Stop
            if ($item.type -in @('error', 'response.failed', 'response.incomplete')) {
                throw 'selected model stream did not complete'
            }
            if ($item.type -eq 'response.completed') { $reply = $item.response }
        }
    }
    if (-not $reply) { throw 'selected model response missing' }
    if ($WireApi -eq 'chat') {
        if ($reply.choices[0].finish_reason -ne 'stop') {
            throw 'selected model response did not finish successfully'
        }
        $content = [string]$reply.choices[0].message.content
    } else {
        if ($reply.status -ne 'completed') {
            throw 'selected model response did not complete'
        }
        $texts = @()
        foreach ($item in $reply.output) {
            if ($item.type -ne 'message') { continue }
            foreach ($part in $item.content) {
                if ($part.type -eq 'output_text') { $texts += [string]$part.text }
            }
        }
        $content = $texts -join ''
    }
    if (-not $content.Trim()) { throw 'selected model response empty' }
    return $content
}
