// Azure AI Search for the per-project document index (the index itself is created by
// scripts/search_setup.py). Entra-only: API keys are disabled.
targetScope = 'resourceGroup'

param location string
param tags object = {}
param name string
@allowed(['basic', 'standard'])
param skuName string = 'basic'

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: skuName }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
  }
}

output name string = search.name
output id string = search.id
output principalId string = search.identity.principalId
output endpoint string = 'https://${name}.search.windows.net'
