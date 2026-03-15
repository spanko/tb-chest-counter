using '../main.bicep'

param prefix = 'tb'
param suffix = 'prod'
param tags = {
  project: 'tb-chest-counter'
  environment: 'prod'
  owner: 'adam'
}

// Replace with your AAD Object ID
param deployerObjectId = '<YOUR_AAD_OBJECT_ID>'

param pgAdminUser = 'tbadmin'
// pgAdminPassword provided at deploy time

// Full FOR clan family — add/remove as needed
param clans = [
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
  {
    id: 'for-reserves'
    name: 'FOR Reserves'
    kingdom: 225
    scanIntervalHours: 4
    scanOffsetMinutes: 20
  }
  // Allied clans
  {
    id: 'allied-clan-1'
    name: 'Allied Clan 1'
    kingdom: 225
    scanIntervalHours: 6
    scanOffsetMinutes: 30
  }
  {
    id: 'allied-clan-2'
    name: 'Allied Clan 2'
    kingdom: 225
    scanIntervalHours: 6
    scanOffsetMinutes: 40
  }
]

param enablePublicAccess = false  // Private endpoints in prod
