// ============================================================================
// Module: ACA Smoke Test Job
// Manual-trigger job that validates the candidate image against a real TB login.
// Runs the scanner in smoke mode — login, navigate, screenshot, extract,
// but never writes to the chests table.
// ============================================================================

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('ACA Environment resource ID')
param environmentId string

@description('ACR login server')
param registryLoginServer string

@description('ACR registry name')
param registryName string

@description('Default image (overridden by CI on each run)')
param imageName string = 'tb-chest-scanner:candidate'

@description('Clan ID to smoke test against')
param smokeClanId string

@description('Clan name')
param smokeClanName string

@description('Kingdom')
param smokeKingdom int

@description('Key Vault name')
param keyVaultName string

@description('PostgreSQL FQDN')
param postgresHost string

@description('PostgreSQL database')
param postgresDatabase string

@description('PostgreSQL user')
param postgresUser string

// Managed identity
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'tb-smoke-test-identity'
  location: location
  tags: tags
}

resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAcr.id, identity.id, 'AcrPull-smoke')
  scope: existingAcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource existingKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource kvAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingKv.id, identity.id, 'KVSecretsUser-smoke')
  scope: existingKv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource smokeJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'tb-smoke-test'
  location: location
  tags: union(tags, { purpose: 'smoke-test' })
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
      triggerType: 'Manual'      // Only triggered by CI or manual dispatch
      replicaTimeout: 300        // 5 min max — smoke should be fast
      replicaRetryLimit: 0       // No retries — fail fast for CI
      registries: [
        {
          server: registryLoginServer
          identity: identity.id
        }
      ]
      secrets: [
        {
          name: 'tb-username'
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/tb-${smokeClanId}-username'
          identity: identity.id
        }
        {
          name: 'tb-password'
          keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/tb-${smokeClanId}-password'
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
          name: 'smoke'
          image: '${registryLoginServer}/${imageName}'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          command: [ 'python', 'src/main.py', 'smoke', '--cloud' ]
          env: [
            { name: 'SCAN_MODE', value: 'smoke' }
            { name: 'CLAN_ID', value: smokeClanId }
            { name: 'CLAN_NAME', value: smokeClanName }
            { name: 'KINGDOM', value: string(smokeKingdom) }
            { name: 'TB_USERNAME', secretRef: 'tb-username' }
            { name: 'TB_PASSWORD', secretRef: 'tb-password' }
            { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
            { name: 'PG_HOST', value: postgresHost }
            { name: 'PG_DATABASE', value: postgresDatabase }
            { name: 'PG_USER', value: postgresUser }
            { name: 'PG_PASSWORD', secretRef: 'pg-password' }
            { name: 'PG_SSLMODE', value: 'require' }
            { name: 'SCAN_MAX_PAGES', value: '1' }    // Only scan page 1
            { name: 'VISION_MODEL_ROUTINE', value: 'claude-haiku-4-5-20251001' }
          ]
        }
      ]
    }
  }
  dependsOn: [
    acrPull
    kvAccess
  ]
}

output jobName string = smokeJob.name
