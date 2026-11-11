// The BFF Container App. It starts from a public placeholder image because the real image does
// not exist until `bff/publish.sh` (or the Publish BFF workflow) has pushed it to the registry.
// Rolling out the real image is a separate, deliberate step: see docs/deployment.md.
targetScope = 'resourceGroup'

param location string
param tags object = {}
param name string
param environmentId string
param environmentDomain string
param registryLoginServer string
param identityId string
param identityClientId string
param image string
param minReplicas int

param keyVaultUrl string
param storageBlobEndpoint string
param oauthContainerName string
param documentsContainerName string
param cosmosEndpoint string
param cosmosDatabaseName string
param searchEndpoint string
param speechEndpoint string
param speechRegion string
param pwaOrigin string
@description('True once the Key Vault secret exists. The app then receives it as NOTION_OAUTH_ENCRYPTION_KEY through a Container Apps secret reference.')
param encryptionKeyReady bool = false
param ownerKey string
param ownerObjectId string
@description('Agent /responses URL. Set it last: the BFF refuses to start without the two owner values.')
param agentResponsesUrl string = ''

var oauthStoreUrl = '${storageBlobEndpoint}${oauthContainerName}/notion-oauth.enc'
var callbackUrl = 'https://${name}.${environmentDomain}/oauth/notion/callback'

var baseEnv = [
  { name: 'NOTION_OAUTH_CALLBACK_URL', value: callbackUrl }
  { name: 'NOTION_OAUTH_STORE_URL', value: oauthStoreUrl }
  { name: 'NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID', value: identityClientId }
  { name: 'NOTION_OWNER_ID', value: ownerKey }
  { name: 'BFF_OWNER_OBJECT_ID', value: ownerObjectId }
  { name: 'PWA_ORIGIN', value: pwaOrigin }
  { name: 'SPEECH_ENDPOINT', value: speechEndpoint }
  { name: 'SPEECH_REGION', value: speechRegion }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'COSMOS_DATABASE', value: cosmosDatabaseName }
  { name: 'DOCUMENTS_ACCOUNT_URL', value: storageBlobEndpoint }
  { name: 'DOCUMENTS_CONTAINER', value: documentsContainerName }
  { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
]

// The BFF image has no Key Vault SDK (Dockerfile.bff prunes it). Container Apps resolves the Key Vault
// secret with the BFF identity and injects it as an environment variable. The secret must exist before the
// reference is added, which is why this waits for `encryptionKeyReady`.
var keySecretName = 'notion-oauth-encryption-key'
var appSecrets = encryptionKeyReady ? [
  {
    name: keySecretName
    keyVaultUrl: '${keyVaultUrl}secrets/${keySecretName}'
    identity: identityId
  }
] : []
var keyEnv = encryptionKeyReady ? [
  { name: 'NOTION_OAUTH_ENCRYPTION_KEY', secretRef: keySecretName }
] : []

// Only when the owner values exist, so the app can never start half configured.
var agentEnv = !empty(agentResponsesUrl) && !empty(ownerKey) && !empty(ownerObjectId) ? [
  { name: 'AGENT_RESPONSES_URL', value: agentResponsesUrl }
] : []

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: appSecrets
      ingress: {
        external: true
        targetPort: 8090
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryLoginServer
          identity: identityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'bff'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(baseEnv, keyEnv, agentEnv)
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: 1
      }
    }
  }
}

output name string = app.name
output fqdn string = app.properties.configuration.ingress.fqdn
output callbackUrl string = callbackUrl
output oauthStoreUrl string = oauthStoreUrl
