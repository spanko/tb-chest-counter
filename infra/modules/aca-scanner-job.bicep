// ============================================================================
// Module: ACA Scanner Job (one per clan)
// Timer-triggered Container Apps Job that runs the Playwright chest scanner.
// Pulls creds from Key Vault via managed identity. Writes results to PostgreSQL.
// ============================================================================

@description('Job name')
param jobName string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('ACA Environment resource ID')
param environmentId string

@description('ACR login server (e.g., tbprodacr123456.azurecr.io)')
param registryLoginServer string

@description('ACR registry name (for RBAC)')
param registryName string

@description('Scanner container image (e.g., tb-chest-scanner:latest)')
param imageName string

@description('Clan identifier (used as partition key + KV secret prefix)')
param clanId string

@description('Clan display name')
param clanName string

@description('TB kingdom number')
param kingdom int

@description('Cron expression for scan schedule (e.g., "0 */4 * * *")')
param cronExpression string

@description('Key Vault name for secret references')
param keyVaultName string

@description('PostgreSQL FQDN')
param postgresHost string

@description('PostgreSQL database name')
param postgresDatabase string

@description('PostgreSQL admin user')
param postgresUser string

@description('Azure Storage connection string for screenshots')
@secure()
param storageConnectionString string = ''

// ---------------------------------------------------------------------------
// Managed Identity — used for ACR pull + Key Vault secret access
// ---------------------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${jobName}-identity'
  location: location
  tags: tags
}

// Grant AcrPull on the container registry
resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAcr.id, identity.id, 'AcrPull')
  scope: existingAcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Grant Key Vault Secrets User on the vault
resource existingKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingKv.id, identity.id, 'KVSecretsUser')
  scope: existingKv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// ACA Job — scheduled Playwright scanner
// ---------------------------------------------------------------------------

resource scannerJob 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: {
        cronExpression: cronExpression
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaTimeout: 600  // 10 min max per scan
      replicaRetryLimit: 1
      registries: [
        {
          server: registryLoginServer
          identity: identity.id
        }
      ]
      secrets: [
        {
          name: 'tb-username'
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/tb-${clanId}-username'
          identity: identity.id
        }
        {
          name: 'tb-password'
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/tb-${clanId}-password'
          identity: identity.id
        }
        {
          name: 'anthropic-api-key'
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/anthropic-api-key'
          identity: identity.id
        }
        {
          name: 'pg-password'
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/pg-password'
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'scanner'
          image: '${registryLoginServer}/${imageName}'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'  // Playwright + Chromium needs headroom
          }
          env: [
            { name: 'CLAN_ID', value: clanId }
            { name: 'CLAN_NAME', value: clanName }
            { name: 'KINGDOM', value: string(kingdom) }
            { name: 'TB_USERNAME', secretRef: 'tb-username' }
            { name: 'TB_PASSWORD', secretRef: 'tb-password' }
            { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
            { name: 'PG_HOST', value: postgresHost }
            { name: 'PG_DATABASE', value: postgresDatabase }
            { name: 'PG_USER', value: postgresUser }
            { name: 'PG_PASSWORD', secretRef: 'pg-password' }
            { name: 'PG_SSLMODE', value: 'require' }
            { name: 'VISION_MODEL_ROUTINE', value: 'claude-haiku-4-5-20251001' }
            { name: 'VISION_MODEL_VERIFY', value: 'claude-sonnet-4-5-20250929' }
            { name: 'VISION_VERIFY_THRESHOLD', value: '0.85' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', value: storageConnectionString }
          ]
        }
      ]
    }
  }
  dependsOn: [
    acrPull
    kvSecretsUser
  ]
}

output jobName string = scannerJob.name
output jobId string = scannerJob.id
output identityPrincipalId string = identity.properties.principalId
