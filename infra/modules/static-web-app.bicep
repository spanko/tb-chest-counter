// ============================================================================
// Module: Azure Static Web App (Dashboard)
// Free tier — hosts the multi-clan leaderboard dashboard.
// Built-in Azure Functions API backend queries PostgreSQL.
// ============================================================================

@description('Static Web App name')
param appName string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('PostgreSQL FQDN for the Functions API backend')
param postgresHost string

@description('PostgreSQL database name')
param postgresDatabase string

@description('PostgreSQL username')
param postgresUser string

@description('Key Vault name for PG password reference')
param keyVaultName string

resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: appName
  location: location
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
    buildProperties: {
      appLocation: '/dashboard'           // Frontend source
      apiLocation: '/dashboard/api'       // Azure Functions API
      outputLocation: 'build'             // Build output folder
    }
  }
}

// App settings for the Functions API backend
resource swaSettings 'Microsoft.Web/staticSites/config@2023-12-01' = {
  parent: swa
  name: 'appsettings'
  properties: {
    PG_HOST: postgresHost
    PG_DATABASE: postgresDatabase
    PG_USER: postgresUser
    PG_SSLMODE: 'require'
    KEY_VAULT_NAME: keyVaultName
    // PG_PASSWORD is fetched from Key Vault at runtime by the Functions code
  }
}

output defaultHostname string = swa.properties.defaultHostname
output swaId string = swa.id
output swaName string = swa.name
