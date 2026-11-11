// Savant Azurian: every Azure resource the project needs, in one resource group.
//
//   azd provision        deploys this file (azure.yaml: infra.path = infra)
//   azd down             deletes it all
//
// Outputs are written to the azd environment (.azure/<env>/.env) and read back by azure.yaml,
// the setup scripts and the GitHub variables script. See docs/configuration.md and docs/deployment.md.
targetScope = 'subscription'

@minLength(1)
@maxLength(32)
@description('Name of the azd environment. It prefixes the resource group and the resource names.')
param environmentName string

@description('Azure region. Pick one where your chat model and hosted agents are available.')
param location string

@description('Object ID of the person running the deployment (azd sets AZURE_PRINCIPAL_ID).')
param principalId string = ''

@description('GitHub repository as owner/name for OIDC. Empty skips the federated credential.')
param githubRepository string = ''

@description('Fixed server-side key of the single owner (NOTION_OWNER_ID): any stable string, same value for the BFF and the agent.')
param ownerKey string = ''

@description('Entra object ID of the single owner (BFF_OWNER_OBJECT_ID).')
param ownerObjectId string = ''

@description('Agent /responses URL (AGENT_RESPONSES_URL). Leave empty until the agent is deployed and Easy Auth is on.')
param agentResponsesUrl string = ''

@description('Set to true after scripts/setup/generate-notion-key.sh has created the key in Key Vault: the BFF then receives it by secret reference.')
param bffEncryptionKeyReady bool = false

@description('Origin of the locally running web interface, for CORS.')
param pwaOrigin string = 'http://localhost:5173'

param projectName string = 'savant'
param toolboxName string = 'sa2-web'

param chatDeploymentName string = 'chat'
param chatModelName string = 'gpt-6-luna'
param chatModelVersion string = '2026-09-22'
param chatSkuName string = 'GlobalStandard'
param chatCapacity int = 150

param embeddingDeploymentName string = 'text-embedding-3-small'
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param embeddingCapacity int = 120

@allowed(['basic', 'standard'])
param searchSkuName string = 'basic'

@description('BFF image. The placeholder is replaced when you publish and roll out the real one.')
param bffImage string = 'mcr.microsoft.com/k8se/quickstart:latest'
@minValue(0)
@maxValue(1)
param bffMinReplicas int = 0

var tags = {
  'azd-env-name': environmentName
  project: 'savant-azurian'
}
var token = toLower(uniqueString(subscription().id, environmentName, location))
var oauthContainerName = 'notion-oauth'
var documentsContainerName = 'documents'
var cosmosDatabaseName = 'sa2'
var foundryAccountName = 'fdy-${take(token, 12)}'
var searchName = 'srch-${take(token, 12)}'
var registryName = 'acr${take(token, 20)}'
var appName = 'ca-${take(environmentName, 20)}-bff'

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: group
  name: 'monitoring'
  params: {
    name: environmentName
    location: location
    tags: tags
  }
}

module identity 'modules/identity.bicep' = {
  scope: group
  name: 'identity'
  params: {
    name: environmentName
    location: location
    tags: tags
    githubRepository: githubRepository
  }
}

module data 'modules/data.bicep' = {
  scope: group
  name: 'data'
  params: {
    location: location
    tags: tags
    keyVaultName: 'kv-${take(token, 12)}'
    storageName: 'st${take(token, 20)}'
    cosmosName: 'cosmos-${take(token, 12)}'
    oauthContainerName: oauthContainerName
    documentsContainerName: documentsContainerName
    cosmosDatabaseName: cosmosDatabaseName
  }
}

module foundry 'modules/foundry.bicep' = {
  scope: group
  name: 'foundry'
  params: {
    location: location
    tags: tags
    accountName: foundryAccountName
    projectName: projectName
    appInsightsName: monitoring.outputs.appInsightsName
    chatDeploymentName: chatDeploymentName
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    chatSkuName: chatSkuName
    chatCapacity: chatCapacity
    embeddingDeploymentName: embeddingDeploymentName
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingCapacity: embeddingCapacity
  }
}

module search 'modules/search.bicep' = {
  scope: group
  name: 'search'
  params: {
    location: location
    tags: tags
    name: searchName
    skuName: searchSkuName
  }
}

module registry 'modules/registry.bicep' = {
  scope: group
  name: 'registry'
  params: {
    location: location
    tags: tags
    registryName: registryName
    environmentName: 'cae-${environmentName}'
    workspaceName: monitoring.outputs.workspaceName
  }
}

module rbac 'modules/rbac.bicep' = {
  scope: group
  name: 'rbac'
  params: {
    keyVaultName: data.outputs.keyVaultName
    storageName: data.outputs.storageName
    oauthContainerName: oauthContainerName
    documentsContainerName: documentsContainerName
    cosmosName: data.outputs.cosmosName
    searchName: search.outputs.name
    foundryAccountName: foundry.outputs.accountName
    registryName: registry.outputs.registryName
    bffPrincipalId: identity.outputs.bffPrincipalId
    ciPrincipalId: identity.outputs.ciPrincipalId
    searchPrincipalId: search.outputs.principalId
    deployerPrincipalId: principalId
  }
}

// The app pulls its image with its own identity, so AcrPull must exist before the app does.
module app 'modules/app.bicep' = {
  scope: group
  name: 'app'
  dependsOn: [rbac]
  params: {
    location: location
    tags: tags
    name: appName
    environmentId: registry.outputs.environmentId
    environmentDomain: registry.outputs.defaultDomain
    registryLoginServer: registry.outputs.loginServer
    identityId: identity.outputs.bffId
    identityClientId: identity.outputs.bffClientId
    image: bffImage
    minReplicas: bffMinReplicas
    keyVaultUrl: data.outputs.keyVaultUrl
    storageBlobEndpoint: data.outputs.storageBlobEndpoint
    oauthContainerName: oauthContainerName
    documentsContainerName: documentsContainerName
    cosmosEndpoint: data.outputs.cosmosEndpoint
    cosmosDatabaseName: cosmosDatabaseName
    searchEndpoint: search.outputs.endpoint
    speechEndpoint: foundry.outputs.speechEndpoint
    speechRegion: location
    pwaOrigin: pwaOrigin
    encryptionKeyReady: bffEncryptionKeyReady
    ownerKey: ownerKey
    ownerObjectId: ownerObjectId
    agentResponsesUrl: agentResponsesUrl
  }
}

// ---- Outputs: written to the azd environment. Names match docs/configuration.md. -------------
output AZURE_RESOURCE_GROUP string = group.name
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_AI_PROJECT_ID string = foundry.outputs.projectId
output AZURE_OPENAI_BASE_URL string = foundry.outputs.openAiBaseUrl
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = chatDeploymentName
output TOOLBOX_ENDPOINT string = '${foundry.outputs.projectEndpoint}/toolboxes/${toolboxName}/mcp?api-version=v1'
output NOTION_OAUTH_CALLBACK_URL string = app.outputs.callbackUrl
output NOTION_OAUTH_STORE_URL string = app.outputs.oauthStoreUrl
output KEY_VAULT_NAME string = data.outputs.keyVaultName
output APP_INSIGHTS_NAME string = monitoring.outputs.appInsightsName
output STORAGE_ACCOUNT_NAME string = data.outputs.storageName
output SEARCH_SERVICE_NAME string = search.outputs.name
output KEY_VAULT_URL string = data.outputs.keyVaultUrl
output SEARCH_ENDPOINT string = search.outputs.endpoint
output SEARCH_STORAGE_RESOURCE_ID string = data.outputs.storageId
output SEARCH_EMBEDDING_ENDPOINT string = foundry.outputs.foundryEndpoint
output SEARCH_EMBEDDING_DEPLOYMENT string = embeddingDeploymentName
output SPEECH_ENDPOINT string = foundry.outputs.speechEndpoint
output SPEECH_REGION string = location
output COSMOS_ENDPOINT string = data.outputs.cosmosEndpoint
output DOCUMENTS_ACCOUNT_URL string = data.outputs.storageBlobEndpoint
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.accountName
output ACR_NAME string = registry.outputs.registryName
output ACR_LOGIN_SERVER string = registry.outputs.loginServer
output BFF_APP_NAME string = app.outputs.name
output BFF_URL string = 'https://${app.outputs.fqdn}'
output BFF_IDENTITY_PRINCIPAL_ID string = identity.outputs.bffPrincipalId
output OIDC_CLIENT_ID string = identity.outputs.ciClientId
