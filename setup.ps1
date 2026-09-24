<#
.SYNOPSIS
    One-command Windows setup for DRISHTA (Slicktrace).
.DESCRIPTION
    The Windows equivalent of `make setup`, for machines that have neither
    make nor bash. Idempotent: every step skips work already done. It builds
    the backend virtual environment, downloads the segmentation model weights
    (~205 MB, once), generates the synthetic data, seeds the precomputed demo
    bundle, and installs the frontend dependencies.
.PARAMETER Force
    Rebuild the synthetic data and re-seed the demo bundle even if present.
.PARAMETER Reinstall
    Reinstall the backend Python dependencies even when requirements.txt is
    unchanged since the last successful install (normally that step is skipped).
.PARAMETER SkipModel
    Skip the model-weights download. The pipeline will not run without them.
.PARAMETER SkipSeed
    Skip seeding the precomputed demo bundle (the slow full-pipeline step).
.PARAMETER SkipFrontend
    Skip `npm install`.
.PARAMETER QuickSeed
    Seed only the default case instead of every case study (much faster). A later
    run without -QuickSeed detects the partial seed and reseeds every case.
.PARAMETER Python
    Path to a Python 3.11 interpreter to use when building the venv.
.PARAMETER AllowUnsupportedPython
    Build the venv with a non-3.11 Python. Untested: the dependency set is
    pinned to 3.11, so this may fail to install or to run.
.EXAMPLE
    .\setup.ps1
.EXAMPLE
    .\setup.ps1 -QuickSeed
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Reinstall,
    [switch]$SkipModel,
    [switch]$SkipSeed,
    [switch]$SkipFrontend,
    [switch]$QuickSeed,
    [string]$Python = "",
    [switch]$AllowUnsupportedPython
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$RepoRoot    = $PSScriptRoot
$BackendDir  = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$VenvDir     = Join-Path $BackendDir '.venv'
$VenvPython  = Join-Path $VenvDir 'Scripts\python.exe'
$script:StartTime = Get-Date

function Write-Head([string]$text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}
function Write-Ok([string]$text)   { Write-Host "    [ok] $text" -ForegroundColor Green }
function Write-Info([string]$text) { Write-Host "    $text"       -ForegroundColor Gray  }
function Write-Note([string]$text) { Write-Host "    ! $text"     -ForegroundColor Yellow }

# Runs a native executable and throws on a non-zero exit code. Error action is
# forced to Continue around the call so a tool writing to stderr (pip, npm) is
# not itself treated as a terminating error under $ErrorActionPreference='Stop'.
function Exec {
    param(
        [Parameter(Mandatory)][string]$File,
        [string[]]$Arguments = @(),
        [string]$WorkDir
    )
    if ($WorkDir) { Push-Location $WorkDir }
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $File @Arguments
        $code = $LASTEXITCODE
        if ($null -ne $code -and $code -ne 0) {
            throw "command failed (exit $code): $File $($Arguments -join ' ')"
        }
    } finally {
        $ErrorActionPreference = $prevEAP
        if ($WorkDir) { Pop-Location }
    }
}

function Test-NodeVersion([string]$v) {
    # Vite 8 engines: "^20.19.0 || >=22.12.0"
    if ($v -match '(\d+)\.(\d+)\.(\d+)') {
        $maj = [int]$Matches[1]; $min = [int]$Matches[2]
        if ($maj -eq 20 -and $min -ge 19) { return $true }
        if ($maj -eq 22 -and $min -ge 12) { return $true }
        if ($maj -ge 23) { return $true }
        return $false
    }
    return $false
}
function Get-PyVersion([string]$file, [string[]]$preArgs) {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $file @preArgs -c "import sys;print(sys.version_info[0],sys.version_info[1])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $p = (($out | Select-Object -First 1).ToString().Trim() -split '\s+')
            if ($p.Count -ge 2) { return "$($p[0]).$($p[1])" }
        }
    } catch { } finally { $ErrorActionPreference = $prevEAP }
    return $null
}

# Finds a usable interpreter, preferring an exact 3.11. Returns a hashtable
# @{ File; PreArgs; Version } so the caller can invoke `py -3.11` or a bare
# python.exe uniformly. Throws with actionable guidance if 3.11 is absent.
function Resolve-Python {
    $cands = @()
    if ($Python) {
        $cands += ,@{ File = $Python; PreArgs = @() }
    } else {
        if (Get-Command py      -ErrorAction SilentlyContinue) { $cands += ,@{ File = 'py';      PreArgs = @('-3.11') } }
        if (Get-Command python  -ErrorAction SilentlyContinue) { $cands += ,@{ File = 'python';  PreArgs = @() } }
        if (Get-Command python3 -ErrorAction SilentlyContinue) { $cands += ,@{ File = 'python3'; PreArgs = @() } }
    }
    foreach ($c in $cands) {
        $v = Get-PyVersion $c.File $c.PreArgs
        if ($v -eq '3.11') { $c.Version = $v; return $c }
    }
    if ($AllowUnsupportedPython) {
        # The exact-3.11 pass above may have only tried `py -3.11`; on a machine
        # where the launcher exists but its default is 3.12/3.13, add an
        # unpinned `py` so the override actually finds an interpreter.
        $fallback = @($cands)
        if (-not $Python -and (Get-Command py -ErrorAction SilentlyContinue)) {
            $fallback += ,@{ File = 'py'; PreArgs = @() }
        }
        foreach ($c in $fallback) {
            $v = Get-PyVersion $c.File $c.PreArgs
            if ($v) {
                Write-Note "using unsupported Python $v; the dependency set is pinned to 3.11."
                $c.Version = $v; return $c
            }
        }
    }
    throw "Python 3.11 not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run. Override with -Python <path> or -AllowUnsupportedPython (untested)."
}
try {
    Write-Host ""
    Write-Host "  DRISHTA (Slicktrace) - Windows setup" -ForegroundColor White
    Write-Host "  repo: $RepoRoot" -ForegroundColor DarkGray

    if (-not (Test-Path $BackendDir) -or -not (Test-Path $FrontendDir)) {
        throw "run this from the repository root (backend\ and frontend\ must sit next to setup.ps1)."
    }

    Write-Head "Checking prerequisites"
    if (Get-Command node -ErrorAction SilentlyContinue) {
        $nv = (& node --version 2>$null | Select-Object -First 1)
        if (Test-NodeVersion $nv) { Write-Ok "Node $nv" }
        else { Write-Note "Node $nv may be too old for Vite 8 (needs 20.19+ or 22.12+); the dev server may refuse to start." }
    } elseif ($SkipFrontend) {
        Write-Note "Node.js not found (skipping frontend anyway)."
    } else {
        throw "Node.js not found. Install Node 22 LTS from https://nodejs.org/ , then re-run (or pass -SkipFrontend)."
    }
    if (-not $SkipFrontend -and -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm not found (it ships with Node.js). Install Node from https://nodejs.org/ ."
    }
    if (Get-Command docker -ErrorAction SilentlyContinue) { Write-Info "Docker present (optional; only the ledger view uses it)." }
    else { Write-Info "Docker not found (optional; only the ledger view uses it)." }

    Write-Head "Backend environment file"
    $envExample = Join-Path $BackendDir '.env.example'
    $envFile    = Join-Path $BackendDir '.env'
    if ((Test-Path $envExample) -and -not (Test-Path $envFile)) {
        Copy-Item $envExample $envFile
        Write-Ok "created backend\.env from .env.example"
    } else { Write-Ok "backend\.env already present (or no template)" }
    Write-Head "Backend virtual environment"
    $venvOk = $false
    if (Test-Path $VenvPython) {
        if (Get-PyVersion $VenvPython @()) {
            $venvOk = $true
            Write-Ok ".venv already present"
        } else {
            Write-Note "existing .venv interpreter does not run; rebuilding it"
        }
    }
    if (-not $venvOk) {
        if (Test-Path $VenvDir) { Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue }
        $py = Resolve-Python
        Write-Info "using Python $($py.Version) ($($py.File) $($py.PreArgs -join ' '))"
        Exec -File $py.File -Arguments (@($py.PreArgs) + @('-m', 'venv', '.venv')) -WorkDir $BackendDir
        if (-not (Test-Path $VenvPython)) { throw "venv creation did not produce $VenvPython" }
        Write-Ok "created $VenvDir"
    }

    Write-Head "Installing backend dependencies (first run downloads ~1.5 GB, several minutes)"
    # Skip pip when the venv already worked and requirements.txt is unchanged, so
    # idempotent re-runs need no network (pip --upgrade always reaches PyPI).
    $reqStamp = Join-Path $VenvDir '.requirements.sha256'
    $reqHash  = (Get-FileHash -LiteralPath (Join-Path $BackendDir 'requirements.txt') -Algorithm SHA256).Hash
    $haveHash = if (Test-Path $reqStamp) { ([string](Get-Content -LiteralPath $reqStamp -Raw)).Trim() } else { '' }
    if ($venvOk -and -not $Reinstall -and $reqHash -eq $haveHash) {
        Write-Ok "backend dependencies up to date (requirements.txt unchanged); skipping (use -Reinstall to force)"
    } else {
        Exec -File $VenvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', '-q') -WorkDir $BackendDir
        Exec -File $VenvPython -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt') -WorkDir $BackendDir
        Set-Content -LiteralPath $reqStamp -Value $reqHash -Encoding ASCII
        Write-Ok "backend dependencies installed"
    }

    Write-Head "Segmentation model weights"
    $modelPath = Join-Path $BackendDir 'data\models\oil-spill-deeplab\model.keras'
    if ($SkipModel) {
        Write-Note "skipped (-SkipModel); the pipeline will not run until these are downloaded."
    } elseif (Test-Path $modelPath) {
        Write-Ok "already present, skipping"
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path $modelPath) | Out-Null
        $fetchPy = Join-Path ([System.IO.Path]::GetTempPath()) 'drishta_fetch_model.py'
        $code = @(
            'import os, shutil'
            'from huggingface_hub import hf_hub_download'
            'dst = "data/models/oil-spill-deeplab/model.keras"'
            'tmp = dst + ".part"'
            'p = hf_hub_download("sahilvishwa2108/oil-spill-deeplab", "model.keras")'
            '# Copy to a sibling temp then atomically rename, so an interrupted'
            '# copy never leaves a truncated model.keras that the skip check trusts.'
            'try:'
            '    shutil.copy(p, tmp)'
            '    os.replace(tmp, dst)'
            'except BaseException:'
            '    if os.path.exists(tmp):'
            '        os.remove(tmp)'
            '    raise'
            'print("downloaded to " + dst)'
        ) -join "`n"
        Set-Content -LiteralPath $fetchPy -Value $code -Encoding UTF8
        Write-Info "downloading from HuggingFace (no account needed) ..."
        try { Exec -File $VenvPython -Arguments @($fetchPy) -WorkDir $BackendDir }
        finally { Remove-Item -LiteralPath $fetchPy -ErrorAction SilentlyContinue }
        Write-Ok "model weights downloaded"
    }
    Write-Head "Synthetic data (SAR scene, wind, currents, origin field)"
    $synArgs = @('scripts\make_synthetic_data.py')
    if ($Force) { $synArgs += '--force' }
    Exec -File $VenvPython -Arguments $synArgs -WorkDir $BackendDir
    Write-Ok "synthetic inputs ready"

    Write-Head "Frontend dependencies"
    # Installed before the seed step so a seed failure never also costs the
    # frontend install (the seed runs the full detection pipeline and can fail).
    if ($SkipFrontend) {
        Write-Note "skipped (-SkipFrontend)"
    } else {
        Exec -File 'npm' -Arguments @('install') -WorkDir $FrontendDir
        Write-Ok "node_modules installed"
    }

    Write-Head "Precomputed demo bundle"
    $b1 = Join-Path $BackendDir 'data\precomputed\demo_bundle.json'
    $b2 = Join-Path $BackendDir 'data\precomputed\scene_preview.png'
    $b3 = Join-Path $BackendDir 'data\precomputed\cases.json'
    $scopeFile = Join-Path $BackendDir 'data\precomputed\.seed_scope'
    $wantScope = if ($QuickSeed) { 'quick' } else { 'all' }
    $haveScope = if (Test-Path $scopeFile) { ([string](Get-Content -LiteralPath $scopeFile -Raw)).Trim() } else { '' }
    $bundlePresent = (Test-Path $b1) -and (Test-Path $b2) -and (Test-Path $b3)
    # A 'quick' request is satisfied by any existing bundle; 'all' only by a prior
    # 'all' seed - so upgrading quick -> all reseeds instead of silently skipping,
    # since -QuickSeed writes the same three sentinel files as a full seed.
    $scopeSatisfied = ($wantScope -eq 'quick') -or ($haveScope -eq 'all')
    if ($SkipSeed) {
        Write-Note "skipped (-SkipSeed); the console will have no data until you seed it."
    } elseif (-not (Test-Path $modelPath)) {
        Write-Note "model weights absent; skipping seed (it runs the detection pipeline). Re-run without -SkipModel to seed the console."
    } elseif ($bundlePresent -and $scopeSatisfied -and -not $Force) {
        $shown = if ($haveScope) { $haveScope } else { 'existing' }
        Write-Ok "already present ($shown seed); skipping (use -Force to regenerate)"
    } else {
        if ($bundlePresent -and -not $scopeSatisfied -and -not $Force) {
            Write-Info "existing seed is '$haveScope'; '$wantScope' requested, reseeding"
        }
        if ($QuickSeed) { Write-Info "seeding the default case only (-QuickSeed)" }
        else { Write-Info "seeding every case study; this runs the full pipeline and can take several minutes" }
        $prevPP = $env:PYTHONPATH
        $env:PYTHONPATH = '.'
        try {
            $seedArgs = @('scripts\seed_demo.py')
            if (-not $QuickSeed) { $seedArgs += '--all' }
            Exec -File $VenvPython -Arguments $seedArgs -WorkDir $BackendDir
            Exec -File $VenvPython -Arguments @('scripts\publish_cases.py') -WorkDir $BackendDir
            Set-Content -LiteralPath $scopeFile -Value $wantScope -Encoding ASCII
        } finally {
            if ($null -eq $prevPP) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
            else { $env:PYTHONPATH = $prevPP }
        }
        Write-Ok "demo bundle seeded ($wantScope) and published to frontend\public\data"
    }

    $elapsed = [int]((Get-Date) - $script:StartTime).TotalSeconds
    Write-Host ""
    Write-Host "Setup complete in ${elapsed}s." -ForegroundColor Green
    Write-Host ""
    Write-Host "Start the app:" -ForegroundColor Cyan
    Write-Host "    .\run.bat            (core :8000 + console :5173, Ctrl+C stops both)"
    Write-Host "    or: python scripts\dev.py"
    Write-Host ""
    Write-Host "Quick detection smoke test:" -ForegroundColor Cyan
    Write-Host "    backend\.venv\Scripts\python backend\scripts\process_sample.py"
    Write-Host ""
    exit 0
}
catch {
    Write-Host ""
    Write-Host "SETUP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "If a dependency or interpreter step failed, delete backend\.venv and re-run." -ForegroundColor Yellow
    Write-Host "Troubleshooting: docs\SETUP.md ('When something goes wrong')." -ForegroundColor Yellow
    exit 1
}
