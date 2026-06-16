param(
    [string]$BaseUrl = "http://localhost:8009",
    [string]$Prompt = "Create a simple calculator MCP server with add and subtract tools",
    [string]$ApiKey = "",
    [int]$HealthTimeoutSeconds = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$headers = @{}
if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    if (-not [string]::IsNullOrWhiteSpace($env:API_KEY)) {
        $ApiKey = $env:API_KEY
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:FUSIONAL_API_KEY)) {
        $ApiKey = $env:FUSIONAL_API_KEY
    }
}
if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
    $headers["X-API-Key"] = $ApiKey
}

$body = @{
    prompt = $Prompt
    sandbox = $true
} | ConvertTo-Json -Depth 4

Write-Host "[1/3] Calling $BaseUrl/generate ..."
try {
    $generateResponse = Invoke-RestMethod -Method Post -Uri "$BaseUrl/generate" -Headers $headers -ContentType "application/json" -Body $body
}
catch {
    Write-Error "Generate request failed: $($_.Exception.Message)"
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        Write-Host "Server response: $($_.ErrorDetails.Message)"
    }
    exit 1
}

if ($generateResponse.status -ne "success") {
    $errorMessage = if ($generateResponse.error) { $generateResponse.error } else { "Unknown generate error" }
    Write-Error "Generate endpoint returned error: $errorMessage"
    exit 1
}

$serverName = [string]$generateResponse.server_name
$port = [int]$generateResponse.port
$tools = @($generateResponse.tools)
$logs = [string]$generateResponse.logs

if (-not $port) {
    Write-Error "Generate response missing port"
    exit 1
}

$generatedBase = "http://localhost:$port"
Write-Host "[2/3] Generated server: $serverName on port $port"
Write-Host "Tools: $($tools -join ', ')"

$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
$healthy = $false
$healthPayload = $null

while ((Get-Date) -lt $deadline) {
    try {
        $healthPayload = Invoke-RestMethod -Method Get -Uri "$generatedBase/health"
        $healthy = $true
        break
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $healthy) {
    Write-Error "Generated server health check failed at $generatedBase/health after $HealthTimeoutSeconds seconds"
    Write-Host "Startup logs: $logs"
    exit 1
}

Write-Host "[3/3] Health check passed for $generatedBase/health"
Write-Host ""
Write-Host "Smoke test PASSED"

$result = [ordered]@{
    status = "success"
    server_name = $serverName
    port = $port
    tools = $tools
    logs = $logs
    generated_health = $healthPayload
}

$result | ConvertTo-Json -Depth 6
