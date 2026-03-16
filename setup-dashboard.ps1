# Setup Azure Static Web App for TB Chest Counter Dashboard
param(
    [string]$ResourceGroup = "rg-tb-chest-counter-dev",
    [string]$AppName = "tbdev-dashboard",
    [string]$Location = "centralus"
)

Write-Host "Setting up Azure Static Web App for TB Chest Counter Dashboard" -ForegroundColor Cyan

# Check if logged in
$account = az account show 2>$null
if (!$account) {
    Write-Host "Please log in to Azure first:" -ForegroundColor Yellow
    az login
}

# Create Static Web App
Write-Host "Creating Static Web App: $AppName" -ForegroundColor Green
$result = az staticwebapp create `
    --name $AppName `
    --resource-group $ResourceGroup `
    --location $Location `
    --sku Free `
    --output json 2>$null

if (!$result) {
    Write-Host "Static Web App may already exist, fetching..." -ForegroundColor Yellow
    $result = az staticwebapp show `
        --name $AppName `
        --resource-group $ResourceGroup `
        --output json 2>$null
}

if (!$result) {
    Write-Host "Failed to create or find Static Web App" -ForegroundColor Red
    exit 1
}

$swa = $result | ConvertFrom-Json
Write-Host "[OK] Static Web App ready: $($swa.defaultHostname)" -ForegroundColor Green

# Get deployment token
Write-Host "Getting deployment token..." -ForegroundColor Cyan
$secrets = az staticwebapp secrets list `
    --name $AppName `
    --resource-group $ResourceGroup `
    --output json | ConvertFrom-Json

if (!$secrets.properties.apiKey) {
    Write-Host "Could not retrieve deployment token" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Yellow
Write-Host "DEPLOYMENT TOKEN (KEEP THIS SECRET!):" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host $secrets.properties.apiKey -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Next steps to deploy the dashboard:" -ForegroundColor Green
Write-Host "1. Go to GitHub repository settings" -ForegroundColor White
Write-Host "2. Navigate to Settings -> Secrets -> Actions" -ForegroundColor White
Write-Host "3. Add new secret: SWA_DEPLOYMENT_TOKEN" -ForegroundColor White
Write-Host "4. Paste the token above as the value" -ForegroundColor White
Write-Host ""
Write-Host "Dashboard URL: https://$($swa.defaultHostname)" -ForegroundColor Green
Write-Host "Access Code: FOR2026" -ForegroundColor Green

# Try clipboard
$secrets.properties.apiKey | Set-Clipboard -ErrorAction SilentlyContinue
if ($?) {
    Write-Host "[OK] Token copied to clipboard!" -ForegroundColor Green
}

Write-Host ""
Write-Host "Once the secret is added, push to main branch to deploy." -ForegroundColor Cyan