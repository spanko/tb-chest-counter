# ============================================================================
# setup-dashboard.ps1 - Create Azure Static Web App and configure deployment
# ============================================================================

param(
    [string]$ResourceGroup = "rg-tb-chest-counter-dev",
    [string]$AppName = "tbdev-dashboard",
    [string]$Location = "centralus"
)

Write-Host "Setting up Azure Static Web App for TB Chest Counter Dashboard" -ForegroundColor Cyan
Write-Host ""

# Check if logged in to Azure
$account = az account show 2>$null
if (!$account) {
    Write-Host "Please log in to Azure first:" -ForegroundColor Yellow
    az login
}

# Create the Static Web App
Write-Host "Creating Static Web App: $AppName" -ForegroundColor Green
$swa = az staticwebapp create `
    --name $AppName `
    --resource-group $ResourceGroup `
    --source "https://github.com/$env:GITHUB_REPOSITORY" `
    --location $Location `
    --branch main `
    --app-location "/dashboard" `
    --api-location "/dashboard/api" `
    --output-location "build" `
    --sku Free `
    --output json 2>$null | ConvertFrom-Json

if (!$swa) {
    # If it already exists, get the existing one
    Write-Host "Static Web App may already exist, fetching..." -ForegroundColor Yellow
    $swa = az staticwebapp show `
        --name $AppName `
        --resource-group $ResourceGroup `
        --output json | ConvertFrom-Json
}

if ($swa) {
    Write-Host "✓ Static Web App ready: $($swa.defaultHostname)" -ForegroundColor Green

    # Get the deployment token
    Write-Host ""
    Write-Host "Getting deployment token..." -ForegroundColor Cyan
    $secrets = az staticwebapp secrets list `
        --name $AppName `
        --resource-group $ResourceGroup `
        --output json | ConvertFrom-Json

    if ($secrets.properties.apiKey) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Yellow
        Write-Host "DEPLOYMENT TOKEN (KEEP THIS SECRET!):" -ForegroundColor Yellow
        Write-Host "========================================" -ForegroundColor Yellow
        Write-Host $secrets.properties.apiKey -ForegroundColor Cyan
        Write-Host "========================================" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Green
        Write-Host "1. Go to your GitHub repository settings" -ForegroundColor White
        Write-Host "2. Navigate to Settings > Secrets and variables > Actions" -ForegroundColor White
        Write-Host "3. Click 'New repository secret'" -ForegroundColor White
        Write-Host "4. Name: SWA_DEPLOYMENT_TOKEN" -ForegroundColor White
        Write-Host "5. Value: (paste the token above)" -ForegroundColor White
        Write-Host "6. Click 'Add secret'" -ForegroundColor White
        Write-Host ""
        Write-Host "Dashboard URL: https://$($swa.defaultHostname)" -ForegroundColor Green
        Write-Host "Access Code: FOR2026 (configured in dashboard/src/App.jsx)" -ForegroundColor Green

        # Also save to clipboard if possible
        $secrets.properties.apiKey | Set-Clipboard 2>$null
        if ($?) {
            Write-Host ""
            Write-Host "✓ Token copied to clipboard!" -ForegroundColor Green
        }
    }
} else {
    Write-Host "Failed to create or find Static Web App" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Once you've added the secret to GitHub, the dashboard will deploy automatically on push to main branch." -ForegroundColor Cyan