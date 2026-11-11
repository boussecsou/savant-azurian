// Every role assignment the deployment owns, in one place. Least privilege: blob roles are
// scoped to a container, not to the storage account.
//
// Not here, because the identity does not exist until the agent is deployed: the hosted
// agent's own roles. They are granted by scripts/setup/grant-agent-roles.sh.
targetScope = 'resourceGroup'

param keyVaultName string
param storageName string
param oauthContainerName string
param documentsContainerName string
param cosmosName string
param searchName string
param foundryAccountName string
param registryName string

param bffPrincipalId string
param ciPrincipalId string
param searchPrincipalId string
@description('Object ID of the person deploying. Empty skips the deployer roles.')
param deployerPrincipalId string = ''

// Built-in role definition IDs (https://learn.microsoft.com/azure/role-based-access-control/built-in-roles).
var roles = {
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  speechContributor: '0e75ca1e-0464-4b4d-8b93-68208a576181'
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
}
var cosmosDataContributor = '00000000-0000-0000-0000-000000000002'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: keyVaultName }
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageName

  resource blobs 'blobServices' existing = {
    name: 'default'

    resource oauth 'containers' existing = { name: oauthContainerName }
    resource documents 'containers' existing = { name: documentsContainerName }
  }
}
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = { name: cosmosName }
resource search 'Microsoft.Search/searchServices@2023-11-01' existing = { name: searchName }
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = { name: foundryAccountName }
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: registryName }

var roleBase = '/subscriptions/${subscription().subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/'

// ---- BFF identity -------------------------------------------------------------------------
resource bffVault 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, bffPrincipalId, roles.keyVaultSecretsUser)
  properties: {
    principalId: bffPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.keyVaultSecretsUser}'
  }
}

resource bffOauthBlobs 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage::blobs::oauth
  name: guid(storage::blobs::oauth.id, bffPrincipalId, roles.storageBlobDataContributor)
  properties: {
    principalId: bffPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.storageBlobDataContributor}'
  }
}

resource bffDocumentBlobs 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage::blobs::documents
  name: guid(storage::blobs::documents.id, bffPrincipalId, roles.storageBlobDataContributor)
  properties: {
    principalId: bffPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.storageBlobDataContributor}'
  }
}

resource bffSearchIndex 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, bffPrincipalId, roles.searchIndexDataContributor)
  properties: {
    principalId: bffPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.searchIndexDataContributor}'
  }
}

resource bffSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, bffPrincipalId, roles.searchServiceContributor)
  properties: {
    principalId: bffPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.searchServiceContributor}'
  }
}

// Contributor, not User: the BFF issues the browser's 10-minute Speech token.
resource bffSpeech 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, bffPrincipalId, roles.speechContributor)
  properties: {
    principalId: bffPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.speechContributor}'
  }
}

resource bffRegistry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, bffPrincipalId, roles.acrPull)
  properties: {
    principalId: bffPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.acrPull}'
  }
}

// Cosmos DB data-plane roles are not Azure RBAC: they use their own role assignment resource.
resource bffCosmos 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, bffPrincipalId, cosmosDataContributor)
  properties: {
    principalId: bffPrincipalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributor}'
    scope: cosmos.id
  }
}

// ---- Search service identity (indexer and vectorizer) --------------------------------------
resource searchBlobs 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, searchPrincipalId, roles.storageBlobDataReader)
  properties: {
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.storageBlobDataReader}'
  }
}

resource searchEmbeddings 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, searchPrincipalId, roles.openAiUser)
  properties: {
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.openAiUser}'
  }
}

// ---- CI identity (GitHub Actions through OIDC) ----------------------------------------------
resource ciFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, ciPrincipalId, roles.foundryUser)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.foundryUser}'
  }
}

resource ciRegistryPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, ciPrincipalId, roles.acrPush)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.acrPush}'
  }
}

resource ciRegistryReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, ciPrincipalId, roles.reader)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: '${roleBase}${roles.reader}'
  }
}

// ---- The person deploying: run the setup scripts, call the model locally ----------------------
resource deployerVault 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: vault
  name: guid(vault.id, deployerPrincipalId, roles.keyVaultSecretsOfficer)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: '${roleBase}${roles.keyVaultSecretsOfficer}'
  }
}

resource deployerFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: foundry
  name: guid(foundry.id, deployerPrincipalId, roles.foundryUser)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: '${roleBase}${roles.foundryUser}'
  }
}

resource deployerSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: search
  name: guid(search.id, deployerPrincipalId, roles.searchServiceContributor)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: '${roleBase}${roles.searchServiceContributor}'
  }
}

resource deployerSearchIndex 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: search
  name: guid(search.id, deployerPrincipalId, roles.searchIndexDataContributor)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: '${roleBase}${roles.searchIndexDataContributor}'
  }
}
