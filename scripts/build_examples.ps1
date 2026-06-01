#!/usr/bin/env pwsh
Write-Host "Building example MCP server Docker images..."

docker build -t dice-mcp-server .\examples\dice-roller
docker build -t weather-mcp-server .\examples\weather-api
docker build -t file-utils-mcp-server .\examples\file-utils

Write-Host "Building fusional gateway image (optional)..."
docker build -t fusional .

Write-Host "Done."
