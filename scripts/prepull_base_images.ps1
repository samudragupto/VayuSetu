<#
.SYNOPSIS
    Pre-pull every image the VayuSetu Compose stack needs, with retries.

.DESCRIPTION
    `docker compose up --build` fails with `lookup registry-1.docker.io: no such
    host` or `failed to compute cache key` when the Docker Desktop VM cannot
    resolve or reach the registry. Build containers then re-download the same
    ~120 MB of base-image layers per target and abort halfway through.

    Pulling the images first (retries included) puts the layers in the local
    image store, so `docker compose build` only needs `RUN` steps to reach the
    network - and with DOCKER_BUILDKIT=0 Compose does not even resolve tags
    against the registry.

    Re-run this script after changing a FROM line, or with `-NoCache` after
    `docker builder prune`.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\prepull_base_images.ps1
    $env:DOCKER_BUILDKIT=0; docker compose up --build
#>
[CmdletBinding()]
param(
    [int]$Attempts = 3,
    [int]$SleepSeconds = 10,
    [switch]$NoCache
)

$ErrorActionPreference = 'Continue'

# Keep in sync with the FROM lines in */Dockerfile and the image: keys in
# docker-compose.yml.
$Images = @(
    'node:20-bookworm-slim',            # api-gateway, firebase emulator
    'node:20-alpine',                   # mock-twilio, mock-google-ai
    'python:3.10-slim',                 # functions/*, prediction-service
    'fsouza/fake-gcs-server:1.56.1',    # gcs
    'curlimages/curl:8.10.1'            # scheduler
)

if ($NoCache) {
    Write-Host '--- pulling with --no-cache (fresh digests)' -ForegroundColor Yellow
    $NoCacheFlag = @('--no-cache')
} else {
    $NoCacheFlag = @()
}

$failed = @()
foreach ($image in $Images) {
    $pulled = $false
    for ($i = 1; $i -le $Attempts; $i++) {
        Write-Host ("--- docker pull {0}  (attempt {1}/{2})" -f $image, $i, $Attempts) -ForegroundColor Cyan
        & docker pull @NoCacheFlag $image
        if ($LASTEXITCODE -eq 0) { $pulled = $true; break }
        Start-Sleep -Seconds $SleepSeconds
    }
    if (-not $pulled) { $failed += $image }
}

if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host ('FAILED after {0} attempts: {1}' -f $Attempts, ($failed -join ', ')) -ForegroundColor Red
    Write-Host 'Registry DNS is unreachable from the Docker VM. In Docker Desktop:' -ForegroundColor Yellow
    Write-Host '  Settings -> Resources -> Proxies: fill BOTH Web Proxy (HTTP) and' -ForegroundColor Yellow
    Write-Host '  Secure Web Proxy (HTTPS), or clear both if only HTTP was set.' -ForegroundColor Yellow
    Write-Host '  Settings -> Resources -> Network -> DNS server: 8.8.8.8, 1.1.1.1' -ForegroundColor Yellow
    Write-Host '  Then "Restart" Docker Desktop and re-run this script.' -ForegroundColor Yellow
    exit 1
}

Write-Host ''
Write-Host 'All base images available locally.' -ForegroundColor Green
Write-Host 'Next:  $env:DOCKER_BUILDKIT=0; docker compose up --build' -ForegroundColor Green
Write-Host '       (or plain `docker compose up --build` once DNS is healthy)' -ForegroundColor Green
