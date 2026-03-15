// ============================================================================
// TB Chest Counter — Multi-Clan Azure Infrastructure
// Deploys: ACA Environment + Jobs, PostgreSQL Flex, Static Web App,
//          Key Vault, Container Registry, RBAC
// Repo: spanko/tb-chest-counter
// ============================================================================

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Resource naming prefix (e.g., "tb")')
param prefix string

@description('Environment suffix (dev, prod)')
param suffix string

@description('Primary Azure region')
param location string = resourceGroup().location

@description('Tags applied to every resource')
param tags object = {}

@description('Deployer AAD Object ID for RBAC + Key Vault access')
param deployerObjectId string

@description('PostgreSQL admin username')
param pgAdminUser string = 'tbadmin'

@secure()
@description('PostgreSQL admin password')
param pgAdminPassword string

@description('Clan configurations — each entry creates an ACA Job + Key Vault secrets')
param clans array
/* Example:
  [
    {
      id: 'for-main'
      name: 'FOR'
      kingdom: 225
      scanIntervalHours: 4
      scanOffsetMinutes: 0
    }
    {
      id: 'for-academy'
      name: 'FOR Academy'
      kingdom: 225
      scanIntervalHours: 4
      scanOffsetMinutes: 10
    }
  ]
*/

@description('Container image for the chest scanner (pushed to ACR)')
param scannerImage string = 'tb-chest-scanner:latest'

@description('Enable public network access to PostgreSQL (set false for prod)')
param enablePublicAccess bool = true

// ---------------------------------------------------------------------------
// Variables
// ---------------------------------------------------------------------------

var baseName = '${prefix}${suffix}'
var uniqueSuffix = substring(uniqueString(resourceGroup().id, baseName), 0, 6)

// ---------------------------------------------------------------------------
// Module: Container Registry
// ---------------------------------------------------------------------------

module acr 'modules/container-registry.bicep' = {
  name: 'deploy-acr'
  params: {
    registryName: replace('${baseName}acr${uniqueSuffix}', '-', '')
    location: location
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// Module: Key Vault
// ---------------------------------------------------------------------------

module keyVault 'modules/key-vault.bicep' = {
  name: 'deploy-keyvault'
  params: {
    keyVaultName: '${baseName}-kv-${uniqueSuffix}'
    location: location
    tags: tags
    deployerObjectId: deployerObjectId
  }
}

// ---------------------------------------------------------------------------
// Module: PostgreSQL Flexible Server
// ---------------------------------------------------------------------------

module postgres 'modules/postgres.bicep' = {
  name: 'deploy-postgres'
  params: {
    serverName: '${baseName}-pg-${uniqueSuffix}'
    location: location
    tags: tags
    adminUser: pgAdminUser
    adminPassword: pgAdminPassword
    databaseName: 'tbchests'
    enablePublicAccess: enablePublicAccess
  }
}

// ---------------------------------------------------------------------------
// Module: Container Apps Environment + Scanner Jobs
// ---------------------------------------------------------------------------

module acaEnvironment 'modules/aca-environment.bicep' = {
  name: 'deploy-aca-env'
  params: {
    environmentName: '${baseName}-env-${uniqueSuffix}'
    location: location
    tags: tags
  }
}

// Deploy one ACA Job per clan
module scannerJobs 'modules/aca-scanner-job.bicep' = [for (clan, i) in clans: {
  name: 'deploy-scanner-${clan.id}'
  params: {
    jobName: '${baseName}-scan-${clan.id}'
    location: location
    tags: union(tags, { clan: clan.id, kingdom: string(clan.kingdom) })
    environmentId: acaEnvironment.outputs.environmentId
    registryLoginServer: acr.outputs.loginServer
    registryName: acr.outputs.registryName
    imageName: scannerImage
    clanId: clan.id
    clanName: clan.name
    kingdom: clan.kingdom
    cronExpression: '${clan.scanOffsetMinutes} */${clan.scanIntervalHours} * * *'
    keyVaultName: keyVault.outputs.keyVaultName
    postgresHost: postgres.outputs.fqdn
    postgresDatabase: 'tbchests'
    postgresUser: pgAdminUser
  }
}]

// Deploy smoke test job (manual trigger, uses first clan's utility account)
module smokeTest 'modules/aca-smoke-test.bicep' = {
  name: 'deploy-smoke-test'
  params: {
    location: location
    tags: tags
    environmentId: acaEnvironment.outputs.environmentId
    registryLoginServer: acr.outputs.loginServer
    registryName: acr.outputs.registryName
    smokeClanId: clans[0].id
    smokeClanName: clans[0].name
    smokeKingdom: clans[0].kingdom
    keyVaultName: keyVault.outputs.keyVaultName
    postgresHost: postgres.outputs.fqdn
    postgresDatabase: 'tbchests'
    postgresUser: pgAdminUser
  }
}

// ---------------------------------------------------------------------------
// Module: Static Web App (Dashboard)
// ---------------------------------------------------------------------------

module dashboard 'modules/static-web-app.bicep' = {
  name: 'deploy-dashboard'
  params: {
    appName: '${baseName}-dash-${uniqueSuffix}'
    location: location
    tags: tags
    postgresHost: postgres.outputs.fqdn
    postgresDatabase: 'tbchests'
    postgresUser: pgAdminUser
    keyVaultName: keyVault.outputs.keyVaultName
  }
}

// ---------------------------------------------------------------------------
// Module: RBAC — wire managed identities to resources
// ---------------------------------------------------------------------------

module rbac 'modules/role-assignments.bicep' = {
  name: 'deploy-rbac'
  params: {
    registryId: acr.outputs.registryId
    deployerObjectId: deployerObjectId
    // ACA Jobs get identity from their module; RBAC is assigned there
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output ACR_LOGIN_SERVER string = acr.outputs.loginServer
output POSTGRES_FQDN string = postgres.outputs.fqdn
output POSTGRES_DATABASE string = 'tbchests'
output KEY_VAULT_NAME string = keyVault.outputs.keyVaultName
output KEY_VAULT_URI string = keyVault.outputs.keyVaultUri
output ACA_ENVIRONMENT_NAME string = acaEnvironment.outputs.environmentName
output DASHBOARD_URL string = dashboard.outputs.defaultHostname
output CLAN_JOBS array = [for (clan, i) in clans: {
  clanId: clan.id
  jobName: scannerJobs[i].outputs.jobName
}]
