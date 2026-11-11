// Two user-assigned managed identities, so nothing in the repository needs a password:
//  - the BFF identity, used by the Container App at runtime;
//  - the CI identity, trusted by GitHub Actions through OpenID Connect (no stored secret).
targetScope = 'resourceGroup'

param name string
param location string
param tags object = {}

@description('GitHub repository as owner/name. Empty skips the federated credential.')
param githubRepository string = ''

resource bff 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}-bff'
  location: location
  tags: tags
}

resource ci 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}-ci'
  location: location
  tags: tags
}

// Only runs from the main branch can sign in. Widen the subject yourself if you need more.
resource githubMain 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: ci
  name: 'github-main'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:ref:refs/heads/main'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

output bffId string = bff.id
output bffPrincipalId string = bff.properties.principalId
output bffClientId string = bff.properties.clientId
output ciPrincipalId string = ci.properties.principalId
output ciClientId string = ci.properties.clientId
