<#
.SYNOPSIS
    Pre-pull every image the VayuSetu Compose stack needs, with retries.

.DESCRIPTION
    `docker compose up --build` fails with `lookup registry-1.docker.io: no such
    host` or `lookup production.cloudfront.docker.com: no such host` when the
    Docker Desktop VM cannot resolve the registry or its layer CDN. BuildKit then
    re-downloads the same ~120 MB of base-image layers for every target and aborts
    halfway through ("failed to compute cache key").

    `docker pull` retries fill the local image store, and the classic builder honours
    it - BuildKit does not, it streams layers per target regardless. That is why the
    mock images succeed from cache while firebase/api-gateway fail in the same run.
    Pass -Build to run `docker compose build` with DOCKER_BUILDKIT=0 immediately,
    so only the RUN layers (deb.debian.org, pypi.org, registry.npmjs.org - separate
    hosts from the registry CDN) need network access.

    Re-run after changing a FROM line, or with -NoCache after `docker builder prune`.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\prepull_base_images.ps1 -Build
#>
[CmdletBinding()]
param(
    [int]$Attempts = 3,
    [int]$SleepSeconds = 10,
    [switch]$NoCache,
    [switch]$Build
)

$ErrorActionPreference = 'Continue'

# Keep in sync with the FROM lines in */Dockerfile and the image: keys in
# docker-compose.yml.
$Images = @(
    # node:20-bookworm-slim  -> api-gateway, firebase emulator
    'node:20-bookworm-slim'
    # node:20-alpine         -> mock-twilio, mock-google-ai
    'node:20-alpine'
    # python:3.10-slim       -> functions/*, prediction-service
    'python:3.10-slim'
    # fsouza/fake-gcs-server -> gcs (runtime image)
    'fsouza/fake-gcs-server:1.56.1'
    # curlimages/curl        -> scheduler (runtime image)
    'curlimages/curl:8.10.1'
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
    Write-Host 'Registry/blob CDN DNS is unreachable from the Docker VM. In Docker Desktop:' -ForegroundColor Yellow
    Write-Host '  Settings -> Resources -> Proxies: fill BOTH Web Proxy (HTTP) and' -ForegroundColor Yellow
    Write-Host '  Secure Web Proxy (HTTPS), or clear both if only HTTP was set, then Restart.' -ForegroundColor Yellow
    Write-Host '  Settings -> Resources -> Network -> DNS server: 8.8.8.8, 1.1.1.1' -ForegroundColor Yellow
    Write-Host '  Confirm from inside the VM:' -ForegroundColor Yellow
    Write-Host '    docker run --rm alpine sh -c "nslookup production.cloudfront.docker.com"' -ForegroundColor Yellow
    Write-Host '  docker info --format "{{json .RegistryConfig.Mirrors}}"   # expect []' -ForegroundColor Yellow
    exit 1
}

Write-Host ''
Write-Host 'All base images available locally.' -ForegroundColor Green

if ($Build) {
    $previous = $env:DOCKER_BUILDKIT
    $env:DOCKER_BUILDKIT = '0'
    try {
        Write-Host '--- docker compose build (classic builder, reads the local image store)' -ForegroundColor Cyan
        docker compose build
        $code = $LASTEXITCODE
    } finally {
        if ($null -eq $previous) {
            Remove-Item Env:DOCKER_BUILDKIT -ErrorAction SilentlyContinue
        } else {
            $env:DOCKER_BUILDKIT = $previous
        }
    }
    if ($code -ne 0) {
        Write-Host 'Compose build still failing - the RUN layers need deb.debian.org,' -ForegroundColor Red
        Write-Host 'pypi.org and registry.npmjs.org, which are separate hosts from the' -ForegroundColor Red
        Write-Host 'registry blob CDN. Check them with:' -ForegroundColor Red
        Write-Host '  docker run --rm alpine sh -c "nslookup deb.debian.org; nslookup pypi.org"' -ForegroundColor Yellow
        exit $code
    }
    Write-Host 'Build done. Next:  docker compose up' -ForegroundColor Green
} else {
    Write-Host 'Next:  re-run with -Build, or set $env:DOCKER_BUILDKIT=0 before' -ForegroundColor Green
    Write-Host '       `docker compose up --build`. Plain BuildKit builds work again once' -ForegroundColor Green
    Write-Host '       Docker Desktop proxy/DNS settings are fixed and Docker is restarted.' -ForegroundColor Green
}
