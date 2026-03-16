# Create Static Web App with custom hostname
param(
    [string]$AppName = "tb-chest-for",  # This will be part of the URL
    [string]$ResourceGroup = "rg-tb-chest-counter-dev",
    [string]$Location = "westus2"
)

Write-Host "Creating Static Web App with custom name..." -ForegroundColor Cyan
Write-Host "This will create: $AppName.azurestaticapps.net" -ForegroundColor Yellow
Write-Host ""

# Create the Static Web App
$result = az staticwebapp create `
    --name $AppName `
    --resource-group $ResourceGroup `
    --location $Location `
    --sku Standard `
    --output json 2>$null

if ($LASTEXITCODE -eq 0) {
    $swa = $result | ConvertFrom-Json
    Write-Host "[OK] Static Web App created!" -ForegroundColor Green
    Write-Host "URL: https://$($swa.defaultHostname)" -ForegroundColor Yellow

    # Get deployment token
    $secrets = az staticwebapp secrets list `
        --name $AppName `
        --resource-group $ResourceGroup `
        --output json | ConvertFrom-Json

    Write-Host ""
    Write-Host "=== Deployment Token ===" -ForegroundColor Cyan
    Write-Host $secrets.properties.apiKey -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Update your GitHub secret SWA_DEPLOYMENT_TOKEN with this token" -ForegroundColor Green

    # Try to copy to clipboard
    $secrets.properties.apiKey | Set-Clipboard -ErrorAction SilentlyContinue
    if ($?) {
        Write-Host "[OK] Token copied to clipboard!" -ForegroundColor Green
    }
} else {
    Write-Host "Failed to create Static Web App" -ForegroundColor Red
    Write-Host "The name might already be taken. Try a different name." -ForegroundColor Yellow
}