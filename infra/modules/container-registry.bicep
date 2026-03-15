// ============================================================================
// Module: Azure Container Registry (Basic SKU)
// Stores the tb-chest-scanner Docker image
// ============================================================================

@description('Registry name (alphanumeric only)')
param registryName string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false  // Use managed identity, not admin creds
    publicNetworkAccess: 'Enabled'
  }
}

output registryId string = acr.id
output registryName string = acr.name
output loginServer string = acr.properties.loginServer
