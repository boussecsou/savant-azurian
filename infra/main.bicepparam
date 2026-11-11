using './main.bicep'

// azd exports its environment (.azure/<env>/.env) as process variables while it deploys.
// Everything personal comes from there; nothing personal lives in this file.
param environmentName = readEnvironmentVariable('AZURE_ENV_NAME')
param location = readEnvironmentVariable('AZURE_LOCATION')
param principalId = readEnvironmentVariable('AZURE_PRINCIPAL_ID', '')
param githubRepository = readEnvironmentVariable('OIDC_GITHUB_REPOSITORY', '')
param ownerKey = readEnvironmentVariable('NOTION_OWNER_ID', '')
param ownerObjectId = readEnvironmentVariable('BFF_OWNER_OBJECT_ID', '')
param agentResponsesUrl = readEnvironmentVariable('AGENT_RESPONSES_URL', '')
param bffEncryptionKeyReady = toLower(readEnvironmentVariable('BFF_ENCRYPTION_KEY_READY', 'false')) == 'true'
param pwaOrigin = readEnvironmentVariable('PWA_ORIGIN', 'http://localhost:5173')

param chatDeploymentName = readEnvironmentVariable('AZURE_AI_MODEL_DEPLOYMENT_NAME', 'chat')
param chatModelName = readEnvironmentVariable('MODEL_NAME', 'gpt-6-luna')
param chatModelVersion = readEnvironmentVariable('MODEL_VERSION', '2026-09-22')
param chatSkuName = readEnvironmentVariable('MODEL_SKU', 'GlobalStandard')
param chatCapacity = int(readEnvironmentVariable('MODEL_CAPACITY', '150'))

param bffImage = readEnvironmentVariable('BFF_IMAGE', 'mcr.microsoft.com/k8se/quickstart:latest')
