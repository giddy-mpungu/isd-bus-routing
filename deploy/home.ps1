<#
.SYNOPSIS
  Install and run isd-bus-routing on this Windows PC, reachable from this
  PC and other devices on the same Wi-Fi. See docs/home-install.md.

.DESCRIPTION
  up           (the default) Check Docker, build and start everything, apply
               migrations, load the fictional demo district the first time,
               open the firewall for the home network, and print the logins.
  update       Get the latest code (git pull) and run `up` again. Data is kept.
  stop         Stop everything. Data is kept; `up` starts it again.
  status       Show what's running.
  logs         Follow the logs (Ctrl+C to stop following).
  credentials  Print the demo logins again.
  trust        Trust this install's HTTPS certificate on this PC (no more warnings
               in this PC's browsers).
  backup       Back up the database now (also nightly, and before every update).
  reset        Delete ALL data and secrets of this install and start over.

.EXAMPLE
  deploy.cmd
  deploy.cmd update
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'update', 'stop', 'status', 'logs', 'credentials', 'trust', 'backup', 'reset')]
    [string]$Command = 'up',
    # For testing on a PC whose firewall you manage yourself.
    [switch]$SkipFirewall
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$EnvFile = Join-Path $RepoRoot '.env.home'
$PgPasswordFile = Join-Path $RepoRoot 'secrets\home_postgres_password.txt'
$ResticPasswordFile = Join-Path $RepoRoot 'secrets\home_restic_password.txt'
$CredentialsJson = Join-Path $RepoRoot 'secrets\home-credentials.json'
$CaFile = Join-Path $RepoRoot 'secrets\home-ca.crt'
$FirewallRule = 'isd-bus-routing (home) HTTPS'
$ComposeArgs = @('compose', '--env-file', $EnvFile, '-f', 'docker-compose.prod.yml', '-f', 'docker-compose.home.yml')

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Note([string]$Message) { Write-Host $Message -ForegroundColor Yellow }

function Invoke-Compose {
    # Docker writes progress to stderr; only the exit code decides success.
    & docker @ComposeArgs @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed (exit code $LASTEXITCODE)." }
}

function New-RandomHex([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return (($buffer | ForEach-Object { $_.ToString('x2') }) -join '')
}

function New-FernetKey {
    # 32 random bytes, url-safe base64: what ISD_API_MFA_ENCRYPTION_KEY needs.
    $buffer = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer).Replace('+', '-').Replace('/', '_')
}

function Write-TextFile([string]$Path, [string]$Text) {
    # UTF-8 without a BOM and LF line endings: a BOM would corrupt the first
    # variable name in .env.home.
    [System.IO.File]::WriteAllText($Path, $Text.Replace("`r`n", "`n"))
}

function Test-DockerEngine {
    # Windows PowerShell 5.1 turns a redirected native stderr line into an
    # error record, which 'Stop' would make fatal; scope it to 'Continue'.
    $ErrorActionPreference = 'Continue'
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Confirm-Step([string]$Question) {
    $answer = Read-Host "$Question [Y/n]"
    return ($answer -eq '' -or $answer -match '^(y|yes)$')
}

function Install-Docker {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Docker Desktop is needed. Install it from https://www.docker.com/products/docker-desktop/ and run deploy.cmd again.'
    }
    if (-not (Confirm-Step 'Docker Desktop is needed and not installed. Install it now with winget?')) {
        throw 'Docker Desktop is needed. Install it, then run deploy.cmd again.'
    }
    Write-Step 'Installing Docker Desktop (Windows asks for permission)...'
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Installing Docker Desktop failed (winget exit code $LASTEXITCODE)." }
    Write-Host ''
    Write-Note 'Docker Desktop is installed. Before running deploy.cmd again:'
    Write-Note '  1. Restart this PC if Windows asks you to.'
    Write-Note '  2. Open Docker Desktop once and accept its terms; wait until it says "Engine running".'
    exit 0
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Install-Docker }
    if (Test-DockerEngine) { return }
    $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path $desktop)) { throw 'Docker is installed but not running. Start Docker Desktop and run this again.' }
    Write-Step 'Starting Docker Desktop (this can take a minute)...'
    Start-Process $desktop
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 2
        if (Test-DockerEngine) { return }
    }
    throw 'Docker Desktop did not finish starting. Wait for it to say "Engine running" (and accept its terms if it asks), then run this again.'
}

function Get-HomeAddress {
    # The IPv4 address of the connection that reaches the internet (it has a
    # default gateway): that's the one other devices on the Wi-Fi can use.
    $config = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } |
        Select-Object -First 1
    if ($null -eq $config) { return $null }
    return ($config.IPv4Address | Select-Object -First 1).IPAddress
}

function Set-EnvSetting([string]$Name, [string]$Value) {
    # Replaces the line if it's there, adds it if not; leaves the rest alone.
    $lines = @()
    if (Test-Path $EnvFile) { $lines = [System.IO.File]::ReadAllText($EnvFile).Split("`n") }
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^$Name=") { $found = $true; "$Name=$Value" } else { $line }
    }
    $text = ($out -join "`n").TrimEnd("`n")
    if (-not $found) { $text += "`n$Name=$Value" }
    Write-TextFile $EnvFile ($text + "`n")
}

function Initialize-Secrets {
    # Generated once, on the first run, and never printed. All gitignored.
    New-Item -ItemType Directory -Force (Split-Path $PgPasswordFile) | Out-Null
    if (-not ((Test-Path $EnvFile) -and (Test-Path $PgPasswordFile))) {
        Write-Step 'Generating this install''s secrets (first run only)...'
        $dbSecret = New-RandomHex 24  # hex only: no escaping inside the URL
        Write-TextFile $PgPasswordFile $dbSecret
        Write-TextFile $EnvFile (@(
                '# Generated by deploy\home.ps1 for this home install. Never commit or share it.',
                'POSTGRES_USER=isd',
                'POSTGRES_DB=isd_api',
                ('ISD_API_DATABASE_URL=postgresql+psycopg://isd:' + $dbSecret + '@postgres:5432/isd_api'),
                "ISD_API_JWT_SECRET_KEY=$(New-RandomHex 32)",
                "ISD_API_MFA_ENCRYPTION_KEY=$(New-FernetKey)",
                '# The web app calls the api on its own origin under /api.',
                'PUBLIC_API_ORIGIN=/api',
                '# Backups go to .\home-backups on this PC.',
                'RESTIC_REPOSITORY=/backups/restic',
                ''
            ) -join "`n")
    }
    if (-not (Test-Path $ResticPasswordFile)) {
        # Never printed. Losing it makes this install's backups unreadable.
        Write-TextFile $ResticPasswordFile (New-RandomHex 32)
    }
}

function Set-Addresses([string]$HomeIp) {
    # Rewritten on every run: home routers hand out a new address now and then.
    $sites = @('localhost')
    $origins = @('"https://localhost"')
    if ($HomeIp) { $sites += $HomeIp; $origins += "`"https://$HomeIp`"" }
    Set-EnvSetting 'CADDY_DOMAIN' ($sites -join ', ')
    Set-EnvSetting 'ISD_API_CORS_ALLOWED_ORIGINS' ('[' + ($origins -join ',') + ']')
    $webUrl = 'https://localhost'
    if ($HomeIp) { $webUrl = "https://$HomeIp" }
    Set-EnvSetting 'ISD_API_PUBLIC_WEB_URL' $webUrl
    # Connections by IP carry no server name; Caddy then shows this one's certificate.
    $sni = 'localhost'
    if ($HomeIp) { $sni = $HomeIp }
    Set-EnvSetting 'CADDY_DEFAULT_SNI' $sni
}

function Assert-PortsFree {
    foreach ($port in 80, 443) {
        $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -eq $owner) { continue }
        $process = Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue
        $name = if ($process) { $process.ProcessName } else { "process $($owner.OwningProcess)" }
        if ($name -match 'docker|wslrelay|vpnkit') { continue }  # this install, already running
        throw "Port $port is already used by $name. Stop it (or uninstall it) and run this again."
    }
}

function Test-PortFree([int]$Port) {
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -eq $listening)
}

function Test-OwnInbox {
    $ErrorActionPreference = 'Continue'  # see Test-DockerEngine
    $id = & docker @ComposeArgs ps -q mailpit 2>$null
    return [bool]$id
}

function Set-InboxPort {
    # Keeps the port it had (this install's own Mailpit may hold it), else
    # the first free one from 8025: another program, or a laptop demo on
    # the same PC, may already use 8025.
    $current = Select-String -Path $EnvFile -Pattern '^HOME_INBOX_PORT=(\d+)' -ErrorAction SilentlyContinue
    if ($current) {
        $port = [int]$current.Matches[0].Groups[1].Value
        if ((Test-OwnInbox) -or (Test-PortFree $port)) { return $port }
    }
    foreach ($port in 8025..8045) {
        if (Test-PortFree $port) {
            Set-EnvSetting 'HOME_INBOX_PORT' "$port"
            return $port
        }
    }
    throw 'No free port between 8025 and 8045 for the test inbox.'
}

function Open-Firewall {
    if ($SkipFirewall) { return }
    if (Get-NetFirewallRule -DisplayName $FirewallRule -ErrorAction SilentlyContinue) { return }
    if (-not (Confirm-Step 'Let other devices on your home network reach it? (opens port 443 for the local network only; Windows asks for permission)')) {
        Write-Note 'Skipped: only this PC can reach it. Run deploy.cmd again to change your mind.'
        return
    }
    $rule = "New-NetFirewallRule -DisplayName '$FirewallRule' -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow -Profile Private -RemoteAddress LocalSubnet | Out-Null"
    Start-Process powershell -Verb RunAs -Wait -ArgumentList @('-NoProfile', '-Command', $rule)
    if (-not (Get-NetFirewallRule -DisplayName $FirewallRule -ErrorAction SilentlyContinue)) {
        Write-Note 'The firewall wasn''t changed, so only this PC can reach it.'
    }
}

function Test-NetworkPrivate {
    $public = Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.NetworkCategory -eq 'Public' }
    if ($public) {
        Write-Note "Windows treats the network '$($public[0].Name)' as Public, so other devices can't reach this PC."
        Write-Note 'If it''s your home Wi-Fi: Settings > Network & internet > Wi-Fi > (your network) > Private network.'
    }
}

function Wait-ForApp {
    # Caddy's own certificate isn't trusted yet, so this check skips verification.
    Add-Type -TypeDefinition @'
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class IsdTrustAll : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint s, X509Certificate c, WebRequest r, int p) { return true; }
}
'@ -ErrorAction SilentlyContinue
    [System.Net.ServicePointManager]::CertificatePolicy = New-Object IsdTrustAll
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri 'https://localhost/api/health' -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return }
        }
        catch { Start-Sleep -Seconds 2 }
    }
    throw 'The app did not answer at https://localhost. See: deploy.cmd logs'
}

function Show-Credentials {
    if (-not (Test-Path $CredentialsJson)) {
        Write-Note 'No logins saved yet. Run: deploy.cmd'
        return
    }
    $accounts = Get-Content $CredentialsJson -Raw | ConvertFrom-Json
    Write-Host ''
    Write-Host 'Logins (one per role; saved in secrets\home-credentials.json):' -ForegroundColor Green
    $accounts | Format-Table -AutoSize -Wrap @{ Label = 'Role'; Expression = { $_.role } },
    @{ Label = 'Email'; Expression = { $_.email } },
    @{ Label = 'Password'; Expression = { $_.password } },
    @{ Label = 'What to try'; Expression = { $_.note } } | Out-Host
}

function Start-Home {
    Assert-Docker
    Assert-PortsFree
    Initialize-Secrets
    $homeIp = Get-HomeAddress
    Set-Addresses $homeIp
    $inboxPort = Set-InboxPort

    Write-Step 'Building and starting everything (the first build takes several minutes)...'
    Invoke-Compose up -d --build --wait postgres routing mailpit api worker web caddy

    Write-Step 'Backing up the database before applying migrations...'
    Invoke-Compose up -d --build backup
    Invoke-Compose exec -T backup backup.sh pre-migration

    Write-Step 'Applying database migrations...'
    Invoke-Compose exec -T api alembic upgrade head

    if (-not (Test-Path $CredentialsJson)) {
        Write-Step 'Loading the fictional demo district...'
        $output = & docker @ComposeArgs exec -T api python scripts/seed_demo.py
        $code = $LASTEXITCODE
        if ($code -eq 0) { Write-TextFile $CredentialsJson (($output | Out-String).Trim()) }
        elseif ($code -eq 3) { Write-Note 'The database already has users, so the demo district was not loaded again.' }
        else { throw "Loading the demo district failed (exit code $code). See the messages above." }
    }

    Write-Step 'Checking it answers over HTTPS...'
    Wait-ForApp
    Open-Firewall
    Test-NetworkPrivate

    Write-Host ''
    Write-Host 'isd-bus-routing is running:' -ForegroundColor Green
    Write-Host '  On this PC:            https://localhost' -ForegroundColor Green
    if ($homeIp) { Write-Host "  On your home network:  https://$homeIp" -ForegroundColor Green }
    Write-Host "  Test inbox (emails):   http://localhost:$inboxPort (this PC only)" -ForegroundColor Green
    Write-Note 'Browsers warn about the certificate the first time (it comes from this PC, not the internet).'
    Write-Note 'Choose "Advanced" then "Continue", or run "deploy.cmd trust" to trust it on this PC.'
    Show-Credentials
}

switch ($Command) {
    'up' { Start-Home }
    'update' {
        if (-not (Test-Path (Join-Path $RepoRoot '.git'))) {
            throw 'This folder isn''t a git checkout. Download the latest version again, copy your .env.home and secrets folder into it, and run deploy.cmd.'
        }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            throw 'Git is needed to update. Install it (winget install -e --id Git.Git) and run "deploy.cmd update" again.'
        }
        Write-Step 'Getting the latest version...'
        & git pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw 'git pull failed; see the message above.' }
        Start-Home
    }
    'stop' {
        Invoke-Compose down
        Write-Host 'Stopped. Your data is kept; "deploy.cmd" starts it again.' -ForegroundColor Green
    }
    'status' { Invoke-Compose ps }
    'logs' { Invoke-Compose logs -f --tail 100 }
    'credentials' { Show-Credentials }
    'trust' {
        Write-Step 'Fetching this install''s certificate authority from Caddy...'
        $pem = & docker @ComposeArgs exec -T caddy cat /data/caddy/pki/authorities/local/root.crt
        if ($LASTEXITCODE -ne 0) { throw 'Start it first: deploy.cmd' }
        Write-TextFile $CaFile (($pem | Out-String).Trim() + "`n")
        Write-Note 'Windows asks you to confirm installing the certificate: choose Yes.'
        Import-Certificate -FilePath $CaFile -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
        Write-Host 'Trusted on this PC; restart the browser. For a phone or another PC, copy secrets\home-ca.crt to it and install it there.' -ForegroundColor Green
    }
    'backup' { Invoke-Compose exec -T backup backup.sh manual }
    'reset' {
        Write-Note 'This permanently deletes ALL data of this install (database, logins, backups) and its secrets.'
        $answer = Read-Host 'Type RESET to continue'
        if ($answer -cne 'RESET') { Write-Host 'Cancelled; nothing was deleted.'; return }
        if (Test-Path $EnvFile) { Invoke-Compose down -v }
        foreach ($f in @($EnvFile, $PgPasswordFile, $ResticPasswordFile, $CredentialsJson, $CaFile)) {
            if (Test-Path $f) { Remove-Item $f }
        }
        $backups = Join-Path $RepoRoot 'home-backups'
        if (Test-Path $backups) { Remove-Item -Recurse -Force $backups }
        Write-Host 'Reset. Run "deploy.cmd" to start fresh.' -ForegroundColor Green
    }
}
