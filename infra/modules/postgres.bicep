// ============================================================================
// Module: Azure PostgreSQL Flexible Server
// B1ms burstable tier, single database for all clans (multi-tenant by clan_id)
// ============================================================================

@description('Server name')
param serverName string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('Admin username')
param adminUser string

@secure()
@description('Admin password')
param adminPassword string

@description('Database name')
param databaseName string = 'tbchests'

@description('Enable public network access')
param enablePublicAccess bool = true

resource pgServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: serverName
  location: location
  tags: tags
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: adminUser
    administratorLoginPassword: adminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: enablePublicAccess ? 'Enabled' : 'Disabled'
    }
  }
}

// Allow Azure services (ACA Jobs, SWA Functions) to connect
resource firewallAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = if (enablePublicAccess) {
  parent: pgServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// Create the application database
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: pgServer
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

output serverId string = pgServer.id
output fqdn string = pgServer.properties.fullyQualifiedDomainName
output serverName string = pgServer.name
output databaseName string = database.name
