# ============================================================================
# build.ps1 - Build and push Docker images for TB Chest Scanner
#
# Usage:
#   .\build.ps1 base              # Build base image (Playwright+deps)
#   .\build.ps1 scanner           # Build scanner image (code layer only) via ACR
#   .\build.ps1 scanner -Local    # Build locally with Docker Desktop and push
#   .\build.ps1 all               # Build both base + scanner
#   .\build.ps1 promote           # Retag candidate to latest
#   .\build.ps1 smoke             # Trigger smoke test job in ACA
# ============================================================================

param(
    [Parameter(Position = 0)]
    [ValidateSet("base", "scanner", "all", "promote", "smoke")]
    [string]$Command,

    [switch]$Local,

    [string]$AcrName = "tbdevacrb7jbhj",
    [string]$BaseTag = "v1",
    [string]$ResourceGroup = "rg-tb-chest-counter-dev"
)

$ErrorActionPreference = "Stop"

# --- Derived values ---
$AcrServer = "$AcrName.azurecr.io"
$BaseImage = "tb-scanner-base"
$ScannerImage = "tb-chest-scanner"

# --- Helpers ---
function Write-Step($msg)  { Write-Host "[build] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[build] $msg" -ForegroundColor Green }

function Get-GitSha {
    try {
        $sha = git rev-parse --short HEAD 2>&1
        if ($LASTEXITCODE -eq 0) { return $sha.Trim() }
        return "unknown"
    }
    catch {
        return "unknown"
    }
}

# --- Base image ---
function Build-Base {
    $baseFullTag = $AcrServer + "/" + $BaseImage + ":" + $BaseTag

    if ($Local) {
        Write-Step "Building base image locally..."
        docker build -f Dockerfile.base -t $baseFullTag .

        Write-Step "Pushing base image to ACR..."
        az acr login --name $AcrName
        docker push $baseFullTag
    }
    else {
        Write-Step "Building base image in ACR (Playwright + Chromium + deps)..."
        Write-Step "This takes 2-3 minutes. Only needed when requirements.txt changes."

        $imageTag = $BaseImage + ":" + $BaseTag
        az acr build --registry $AcrName --image $imageTag --file Dockerfile.base "."
    }

    Write-Ok "Base image pushed: $baseFullTag"
}

# --- Scanner image ---
function Build-Scanner {
    $sha = Get-GitSha
    $candidateTag = $ScannerImage + ":candidate"
    $shaTag = $ScannerImage + ":sha-" + $sha
    $candidateFull = $AcrServer + "/" + $candidateTag
    $shaFull = $AcrServer + "/" + $shaTag

    if ($Local) {
        Write-Step "Building scanner image locally with Docker Desktop..."

        docker build `
            -f Dockerfile.scanner `
            --build-arg "ACR_SERVER=$AcrServer" `
            --build-arg "BASE_TAG=$BaseTag" `
            -t $candidateFull `
            -t $shaFull `
            .

        Write-Step "Pushing to ACR..."
        az acr login --name $AcrName
        docker push $candidateFull
        docker push $shaFull

        Write-Ok "Local build + push completed - much faster than remote az acr build!"
    }
    else {
        Write-Step "Building scanner image in ACR (code layer only)..."

        az acr build `
            --registry $AcrName `
            --image $candidateTag `
            --image $shaTag `
            --file Dockerfile.scanner `
            --build-arg "ACR_SERVER=$AcrServer" `
            --build-arg "BASE_TAG=$BaseTag" `
            "."
    }

    Write-Ok ("Scanner image pushed: " + $candidateFull + " (sha-" + $sha + ")")
    Write-Step "Next: .\build.ps1 smoke  then  .\build.ps1 promote"
}

# --- Promote candidate to latest ---
function Invoke-Promote {
    Write-Step "Promoting candidate to latest..."

    $sourceTag = $AcrServer + "/" + $ScannerImage + ":candidate"
    $destTag = $ScannerImage + ":latest"
    $latestFull = $AcrServer + "/" + $ScannerImage + ":latest"

    az acr import --name $AcrName --source $sourceTag --image $destTag --force

    Write-Ok ("Promoted: " + $ScannerImage + " candidate to latest")
    Write-Step "ACA Jobs referencing :latest will pick this up on next trigger."
    Write-Host ""
    Write-Step "To force immediate update:"
    Write-Host ("  az containerapp job update --name tbdev-scan-for-main --resource-group " + $ResourceGroup + " --image " + $latestFull)
}

# --- Trigger smoke test ---
function Invoke-Smoke {
    Write-Step "Triggering smoke test job..."

    az containerapp job start --name tb-smoke-test --resource-group $ResourceGroup

    Write-Ok "Smoke test triggered. Check logs in ~2 min:"
    Write-Host ""
    Write-Host '  az containerapp job execution list --name tb-smoke-test --resource-group rg-tb-chest-counter-dev --output table' -ForegroundColor Gray
    Write-Host ""
    Write-Host '  az monitor log-analytics query `' -ForegroundColor Gray
    Write-Host '    --workspace 84afec13-9a92-4daf-af9f-620e7cd84767 `' -ForegroundColor Gray
    Write-Host '    --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(5m) | order by TimeGenerated desc | take 30" `' -ForegroundColor Gray
    Write-Host '    --output table' -ForegroundColor Gray
}

# --- Dispatch ---
if (-not $Command) {
    Write-Host 'Usage: .\build.ps1 [base|scanner|all|promote|smoke] [-Local]' -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  base       Build base image (Playwright+Chromium+deps)"
    Write-Host "  scanner    Build scanner image (code layer only)"
    Write-Host "  all        Build base + scanner"
    Write-Host "  promote    Retag candidate to latest"
    Write-Host "  smoke      Trigger smoke test ACA job"
    Write-Host ""
    Write-Host "Flags:"
    Write-Host "  -Local     Build with Docker Desktop instead of ACR"
    Write-Host ""
    Write-Host "Typical workflow:"
    Write-Host '  .\build.ps1 base                 # one-time' -ForegroundColor Cyan
    Write-Host '  .\build.ps1 scanner -Local        # edit code, rebuild (seconds)' -ForegroundColor Cyan
    Write-Host '  .\build.ps1 smoke                 # verify' -ForegroundColor Cyan
    Write-Host '  .\build.ps1 promote               # ship it' -ForegroundColor Cyan
    exit 0
}

switch ($Command) {
    "base"    { Build-Base }
    "scanner" { Build-Scanner }
    "all"     { Build-Base; Build-Scanner }
    "promote" { Invoke-Promote }
    "smoke"   { Invoke-Smoke }
}
