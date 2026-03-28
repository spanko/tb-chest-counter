# Setup custom domain for TB Chest Counter Dashboard
param(
    [string]$CustomDomain = "tb-dashboard.tbchestsforfor.com",  # Change this to your domain
    [string]$ResourceGroup = "rg-tb-chest-counter-dev",
    [string]$AppName = "tbdash-for-dev"
)

Write-Host "Setting up custom domain for Static Web App..." -ForegroundColor Cyan
Write-Host ""

# Get the current Static Web App
Write-Host "Getting Static Web App details..." -ForegroundColor Yellow
$swa = az staticwebapp show `
    --name $AppName `
    --resource-group $ResourceGroup `
    --output json | ConvertFrom-Json

if (!$swa) {
    Write-Host "Static Web App not found!" -ForegroundColor Red
    exit 1
}

$defaultHostname = $swa.defaultHostname
Write-Host "[OK] Found Static Web App: $defaultHostname" -ForegroundColor Green
Write-Host ""

# Display CNAME instructions
Write-Host "=== STEP 1: Configure your DNS ===" -ForegroundColor Cyan
Write-Host "Add a CNAME record in your DNS provider:" -ForegroundColor White
Write-Host ""
Write-Host "  Type:   CNAME" -ForegroundColor Yellow
Write-Host "  Name:   $($CustomDomain.Split('.')[0])" -ForegroundColor Yellow
Write-Host "  Value:  $defaultHostname" -ForegroundColor Yellow
Write-Host ""
Write-Host "Example DNS record:" -ForegroundColor Gray
Write-Host "  tb-dashboard  CNAME  $defaultHostname" -ForegroundColor Gray
Write-Host ""

# Wait for user confirmation
Write-Host "Press Enter once you've added the CNAME record..." -ForegroundColor Cyan
Read-Host

# Add custom domain to Static Web App
Write-Host ""
Write-Host "=== STEP 2: Adding custom domain to Static Web App ===" -ForegroundColor Cyan

$result = az staticwebapp hostname add `
    --hostname $CustomDomain `
    --name $AppName `
    --resource-group $ResourceGroup `
    --output json 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Custom domain added successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "=== Domain Configuration Complete ===" -ForegroundColor Green
    Write-Host "Your dashboard will be available at:" -ForegroundColor White
    Write-Host "  https://$CustomDomain" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Note: SSL certificate provisioning may take 5-10 minutes" -ForegroundColor Gray
    Write-Host ""

    # List all domains
    Write-Host "All configured domains:" -ForegroundColor Cyan
    az staticwebapp hostname list `
        --name $AppName `
        --resource-group $ResourceGroup `
        --output table
} else {
    Write-Host "Failed to add custom domain" -ForegroundColor Red
    Write-Host "Common issues:" -ForegroundColor Yellow
    Write-Host "  - CNAME record not propagated yet (wait a few minutes)" -ForegroundColor Gray
    Write-Host "  - Domain already in use by another Azure resource" -ForegroundColor Gray
    Write-Host "  - Invalid domain format" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== Alternative: Use Azure Portal ===" -ForegroundColor Cyan
Write-Host "1. Go to Azure Portal > Static Web Apps > $AppName" -ForegroundColor White
Write-Host "2. Click 'Custom domains' in the left menu" -ForegroundColor White
Write-Host "3. Click '+ Add'" -ForegroundColor White
Write-Host "4. Enter your domain: $CustomDomain" -ForegroundColor White
Write-Host "5. Follow the validation steps" -ForegroundColor White