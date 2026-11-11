// Key Vault (secrets), Blob Storage (encrypted Notion tokens and project documents) and
// Cosmos DB (projects, sessions, messages). Every data plane is Entra-only: no keys.
targetScope = 'resourceGroup'

param location string
param tags object = {}
param keyVaultName string
param storageName string
param cosmosName string
param oauthContainerName string = 'notion-oauth'
param documentsContainerName string = 'documents'
param cosmosDatabaseName string = 'sa2'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }

  resource blobs 'blobServices' = {
    name: 'default'

    resource oauth 'containers' = {
      name: oauthContainerName
      properties: { publicAccess: 'None' }
    }

    resource documents 'containers' = {
      name: documentsContainerName
      properties: { publicAccess: 'None' }
    }
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableServerless' }
    ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: cosmosDatabaseName
  properties: {
    resource: { id: cosmosDatabaseName }
  }
}

// The partition key cannot change after creation. These match src/savant/workspace_store.py.
var cosmosContainers = [
  { name: 'projects', partitionKey: '/id' }
  { name: 'sessions', partitionKey: '/id' }
  { name: 'messages', partitionKey: '/sessionId' }
]

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [for container in cosmosContainers: {
  parent: database
  name: container.name
  properties: {
    resource: {
      id: container.name
      partitionKey: {
        paths: [container.partitionKey]
        kind: 'Hash'
      }
    }
  }
}]

output keyVaultName string = vault.name
output keyVaultUrl string = vault.properties.vaultUri
output storageName string = storage.name
output storageId string = storage.id
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output cosmosName string = cosmos.name
output cosmosEndpoint string = cosmos.properties.documentEndpoint
