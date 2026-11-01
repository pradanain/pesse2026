[CmdletBinding()]
param([switch]$Pull)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-PortalDocker {
    param([string[]]$DockerArguments)
    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw ('Perintah Docker gagal (exit ' + $LASTEXITCODE + '). Deployment dihentikan.')
    }
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI tidak ditemukan. Pasang/jalankan Docker Desktop terlebih dahulu.'
    }
    $engineType = & docker info --format '{{.OSType}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or $engineType.Trim() -ne 'linux') {
        throw 'Docker belum siap atau belum memakai Linux containers. Jalankan Docker Desktop dengan Linux containers.'
    }
    if (-not (Test-Path -LiteralPath 'deploy.env')) {
        Copy-Item -LiteralPath 'deploy.env.example' -Destination 'deploy.env'
    }
    $settings = @{}
    foreach ($line in Get-Content -LiteralPath 'deploy.env') {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $settings[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    $networkName = $settings['TRAEFIK_NETWORK']
    if (-not $networkName) { $networkName = 'proxy' }
    & docker network inspect $networkName *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Network Traefik '$networkName' tidak ditemukan. Sesuaikan TRAEFIK_NETWORK di deploy.env."
    }
    foreach ($name in @('portal.sqlite3', 'secret.key', 'manifest.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path 'private\seed' $name) -PathType Leaf)) {
            throw 'Paket data privat belum lengkap. Ekstrak paket PRIVATE atau SERVER-READY ke folder ini; jangan generate akun/secret baru.'
        }
    }
    New-Item -ItemType Directory -Path 'private\backups' -Force | Out-Null
    $composeArguments = @('compose', '--env-file', 'deploy.env', '-f', 'compose.server.yml')
    $imageName = $settings['PORTAL_IMAGE']
    if (-not $imageName) { $imageName = 'ghcr.io/pradanain/pesse2026:latest' }
    $loaded = $false
    if ((Test-Path -LiteralPath 'images\portal-amd64.tar') -and -not $Pull) {
        Invoke-PortalDocker @('load', '-i', 'images/portal-amd64.tar')
        $loaded = $true
    }
    if ($imageName -eq 'pesse-se2026:local') {
        Invoke-PortalDocker ($composeArguments + @('build', 'portal'))
    } elseif (-not $loaded) {
        & docker @composeArguments pull
        if ($LASTEXITCODE -ne 0) {
            & docker image inspect $imageName *> $null
            if ($LASTEXITCODE -ne 0) {
                throw 'Image belum dapat ditarik dan belum tersedia secara lokal.'
            }
            Write-Output 'Registry belum dapat diakses; memakai image yang sudah tersedia secara lokal.'
        }
    }
    Invoke-PortalDocker ($composeArguments + @('up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '180'))
    Invoke-PortalDocker ($composeArguments + @('ps'))
    Write-Output 'Portal siap pada origin Traefik. Tunnel: pesse.databenuanta.id -> http://traefik:80.'
} catch {
    Write-Host ('Gagal: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
