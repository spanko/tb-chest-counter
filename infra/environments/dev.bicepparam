using '../main.bicep'

param prefix = 'tb'
param suffix = 'dev'
param tags = {
  project: 'tb-chest-counter'
  environment: 'dev'
  owner: 'adam'
}

param deployerObjectId = 'd9a4dcc0-50de-4c43-b46b-4d81233e3b1b'

param pgAdminUser = 'tbadmin'
param pgAdminPassword = ''  // Override at deploy: --parameters pgAdminPassword="YourP@ss"

param clans = [
  {
    id: 'for-main'
    name: 'FOR'
    kingdom: 225
    scanIntervalHours: 4
    scanOffsetMinutes: 0
  }
]

param enablePublicAccess = true
