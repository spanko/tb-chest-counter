// ============================================================================
// Module: Role Assignments
// Grants deployer access to ACR and Key Vault.
// Per-job RBAC (AcrPull, KV Secrets User) is handled in aca-scanner-job.bicep.
// ============================================================================

@description('Container Registry resource ID')
param registryId string

@description('Deployer AAD Object ID')
param deployerObjectId string

// ---------------------------------------------------------------------------
// Deployer gets AcrPush (to push scanner images)
// ---------------------------------------------------------------------------

resource deployerAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registryId, deployerObjectId, 'AcrPush')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8311e382-0749-4cb8-b61a-304f252e45ec') // AcrPush
    principalId: deployerObjectId
    principalType: 'User'
  }
}

// Note: Deployer Key Vault Administrator role is granted in key-vault.bicep
// Note: Per-job AcrPull and KV Secrets User roles are granted in aca-scanner-job.bicep
