// Microsoft Foundry: one AI Services account (model deployments, Foundry project, Azure Speech)
// and the project that hosts the agent. Key authentication is disabled: Entra ID only.
targetScope = 'resourceGroup'

param location string
param tags object = {}
@description('Account name. It becomes the custom subdomain, so it must be globally unique.')
param accountName string
param projectName string
param appInsightsName string

@description('Chat model deployment. The deployment name is what AZURE_AI_MODEL_DEPLOYMENT_NAME holds.')
param chatDeploymentName string
param chatModelName string
param chatModelVersion string
param chatSkuName string
param chatCapacity int

@description('Embedding model used by Azure AI Search for integrated vectorization.')
param embeddingDeploymentName string
param embeddingModelName string
param embeddingModelVersion string
param embeddingCapacity int

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: projectName
    description: 'Savant Azurian: single-owner personal agent'
  }
}

// Deployments of one account are created one after the other.
resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: chatDeploymentName
  sku: {
    name: chatSkuName
    capacity: chatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: embeddingDeploymentName
  dependsOn: [chat]
  sku: {
    name: 'GlobalStandard'
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

// Lets the hosted agent export its telemetry to the project's Application Insights.
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: insights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: { key: insights.properties.ConnectionString }
    metadata: {
      ApiType: 'Azure'
      ResourceId: insights.id
    }
  }
}

output accountName string = account.name
output accountId string = account.id
output projectId string = project.id
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
output openAiBaseUrl string = 'https://${accountName}.openai.azure.com/openai/v1/'
output foundryEndpoint string = 'https://${accountName}.services.ai.azure.com'
output speechEndpoint string = 'https://${accountName}.cognitiveservices.azure.com'
