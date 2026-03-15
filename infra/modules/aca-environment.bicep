// ============================================================================
// Module: Container Apps Environment
// Shared environment for all scanner jobs (consumption plan = pay per execution)
// ============================================================================

@description('Environment name')
param environmentName string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

// Log Analytics workspace for ACA logs
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${environmentName}-logs'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

output environmentId string = acaEnv.id
output environmentName string = acaEnv.name
output logWorkspaceId string = logWorkspace.id
