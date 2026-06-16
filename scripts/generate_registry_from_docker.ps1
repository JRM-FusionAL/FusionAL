#!/usr/bin/env pwsh
<#
Generates `core/mcp_registry.json` from running Docker containers on Docker Desktop.

Usage:
  # From repo root (PowerShell)
  .\scripts\generate_registry_from_docker.ps1 [-Label <label>] [-ImageRegex <regex>]

Parameters:
  -Label: Docker label filter (example: "mcp=true"). Will call `docker ps --filter "label=<label>"`.
  -ImageRegex: Regex to match the container image name (case-insensitive). Example: "^my-mcp-.*$"

If neither `-Label` nor `-ImageRegex` are provided, the script will include all running containers.

The script will:
  - Backup existing `core/mcp_registry.json` to `core/mcp_registry.json.bak`
  - Enumerate running containers (optionally filtered)
  - Create registry entries with URL `docker://<container_name>`
  - Write a new `core/mcp_registry.json`
#>

param(
    [string]$Label = "",
    [string]$ImageRegex = ""
)

Set-StrictMode -Version Latest
Push-Location (Split-Path -Path $MyInvocation.MyCommand.Path -Parent) | Out-Null
Pop-Location | Out-Null

$repoRoot = (Resolve-Path "..\").Path
$registryPath = Join-Path $repoRoot "core\mcp_registry.json"
$backupPath = "$registryPath.bak"

if (-Not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker CLI not found in PATH. Install Docker Desktop and ensure `docker` is available in PowerShell."
    exit 1
}

Write-Host "Backing up existing registry (if present) to $backupPath"
if (Test-Path $registryPath) { Copy-Item -Path $registryPath -Destination $backupPath -Force }

if ($Label) {
    Write-Host "Listing containers with label: $Label"
    $lines = docker ps --filter "label=$Label" --format "{{.Names}} {{.Image}}"
} elseif ($ImageRegex) {
    Write-Host "Listing containers with image matching regex: $ImageRegex"
    $all = docker ps --format "{{.Names}} {{.Image}}"
    $lines = $all | Where-Object { $_ -match $ImageRegex }
} else {
    Write-Host "Listing all running containers"
    $lines = docker ps --format "{{.Names}} {{.Image}}"
}

if (-Not $lines) {
    Write-Warning "No running containers matched the criteria. The registry will contain only the existing `test-server` if present."
}

$obj = @{}

# Keep existing test-server entry if present in backup
if (Test-Path $backupPath) {
    try {
        $existing = Get-Content $backupPath -Raw | ConvertFrom-Json -ErrorAction Stop
        if ($existing.PSObject.Properties.Name -contains 'test-server') {
            $obj['test-server'] = $existing.'test-server'
        }
    } catch {
        # ignore parse errors
    }
}

foreach ($line in $lines) {
    if (-not $line) { continue }
    $parts = $line -split "\s+"
    $name = $parts[0]
    $image = if ($parts.Length -gt 1) { $parts[1] } else { "" }

    $entry = [ordered]@{
        description = "Docker container $name (image: $image)"
        url = "docker://$name"
        metadata = @{ version = "unknown"; tools = @() }
        registered_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $obj[$name] = $entry
}

$json = $obj | ConvertTo-Json -Depth 5
Set-Content -Path $registryPath -Value $json -Encoding UTF8
Write-Host "Wrote registry to $registryPath"
