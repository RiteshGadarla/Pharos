<#
.SYNOPSIS
    Start DRISHTA (Slicktrace) locally on Windows.
.DESCRIPTION
    Runs the core service (http://localhost:8000) and the frontend dev server
    (http://localhost:5173) together via scripts\dev.py. Ctrl+C stops both.
    With -Offline, builds the frontend and serves the static bundle with
    `vite preview` and no backend - the "DEMO MODE: OFFLINE" path that has no
    moving parts, useful for a demo on an unreliable network.
.PARAMETER Offline
    Build and preview the static frontend only (no backend process).
.EXAMPLE
    .\run.ps1
.EXAMPLE
    .\run.ps1 -Offline
#>
[CmdletBinding()]
param([switch]$Offline)

# Continue (not Stop): the dev servers stream to stderr for their whole
# lifetime, and that must not be mistaken for a terminating error.
$ErrorActionPreference = 'Continue'

$RepoRoot    = $PSScriptRoot
$BackendDir  = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$VenvPython  = Join-Path $BackendDir '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host "No backend venv found at $VenvPython" -ForegroundColor Red
    Write-Host "Run .\setup.bat first." -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
    Write-Host "No frontend node_modules found." -ForegroundColor Red
    Write-Host "Run .\setup.bat first." -ForegroundColor Yellow
    exit 1
}

if ($Offline) {
    Write-Host "Building the static frontend, then serving it with vite preview ..." -ForegroundColor Cyan
    Push-Location $FrontendDir
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) { Write-Host "npm run build failed." -ForegroundColor Red; exit 1 }
        & npx vite preview
        exit $LASTEXITCODE
    } finally { Pop-Location }
}

& $VenvPython (Join-Path $RepoRoot 'scripts\dev.py')
exit $LASTEXITCODE
