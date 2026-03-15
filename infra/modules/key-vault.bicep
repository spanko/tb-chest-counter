// ============================================================================
// Module: Azure Key Vault
// Stores: TB utility account creds per clan, Anthropic API key, PG password
// ============================================================================

@description('Key Vault name')
param keyVaultName string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('Deployer AAD Object ID — gets full admin access')
param deployerObjectId string

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true  // Use RBAC, not access policies
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// Grant deployer full Key Vault admin
resource deployerAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, deployerObjectId, 'KeyVaultAdmin')
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00482a5a-887f-4fb3-b363-3b7fe8e74483') // Key Vault Administrator
    principalId: deployerObjectId
    principalType: 'User'
  }
}

output keyVaultId string = kv.id
output keyVaultName string = kv.name
output keyVaultUri string = kv.properties.vaultUri
