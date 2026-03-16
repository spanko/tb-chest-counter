# Deploy Admin API to Azure Container Apps
param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "rg-tb-chest-counter-dev",

    [Parameter(Mandatory=$false)]
    [string]$Location = "westus2",

    [Parameter(Mandatory=$false)]
    [string]$ContainerAppName = "tb-chest-admin-api",

    [Parameter(Mandatory=$false)]
    [string]$RegistryName = "tbdevacrb7jbhj"
)

Write-Host "Deploying Admin API to Azure Container Apps..." -ForegroundColor Cyan

# Build and push Docker image
$imageName = "$RegistryName.azurecr.io/tb-admin-api:latest"

Write-Host "Building Docker image..." -ForegroundColor Yellow
docker build -t $imageName .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed"
    exit 1
}

Write-Host "Logging into Azure Container Registry..." -ForegroundColor Yellow
az acr login --name $RegistryName

Write-Host "Pushing image to registry..." -ForegroundColor Yellow
docker push $imageName

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker push failed"
    exit 1
}

# Container App environment name
$containerEnvName = "tbdev-env-b7jbhj"

# Create or update the Container App
Write-Host "Creating/updating Container App..." -ForegroundColor Yellow

# Check if the app already exists
$appExists = az containerapp show `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --query name -o tsv 2>$null

if ($appExists) {
    Write-Host "Updating existing Container App..." -ForegroundColor Yellow

    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --image $imageName `
        --cpu 0.5 `
        --memory 1.0 `
        --min-replicas 1 `
        --max-replicas 3
} else {
    Write-Host "Creating new Container App..." -ForegroundColor Yellow

    az containerapp create `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --environment $containerEnvName `
        --image $imageName `
        --target-port 8080 `
        --ingress external `
        --cpu 0.5 `
        --memory 1.0 `
        --min-replicas 1 `
        --max-replicas 3 `
        --secrets "postgres-connection=keyvault-ref:https://kv-tb-chest-dev.vault.azure.net/secrets/postgres-connection,identityref:system" `
        --env-vars "POSTGRES_CONNECTION_STRING=secretref:postgres-connection" "PORT=8080"
}

# Get the app URL
$appUrl = az containerapp show `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --query "properties.configuration.ingress.fqdn" -o tsv

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Admin API deployed successfully!" -ForegroundColor Green
Write-Host "URL: https://$appUrl" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Update dashboard/.env with:" -ForegroundColor White
Write-Host "   VITE_API_URL=https://$appUrl" -ForegroundColor Yellow
Write-Host "2. Redeploy the dashboard" -ForegroundColor White
Write-Host ""