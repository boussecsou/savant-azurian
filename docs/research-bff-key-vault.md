# The backend and the Fernet key in Key Vault: research of 8 October 2026

This note prepared the first step of the Notion OAuth rollout. It describes documented capabilities, not a validation of the runtime in Azure. No Azure operation was run. The result is applied in [notion-chat-oauth.md](notion-chat-oauth.md) and in the Bicep template ([deployment guide](deployment.md)).

## Decision

The backend keeps reading `NOTION_OAUTH_ENCRYPTION_KEY`: Azure Container Apps can inject the value of a Key Vault secret. The Hosted Agent reads the same secret with `azure-keyvault-secrets` and `azure-identity`. The storage of encrypted tokens and the OAuth protocol stay unchanged.

## Azure Container Apps: native injection

Container Apps lets you declare a secret with `keyVaultUrl` and `identity`, then expose that secret as an environment variable through `secretRef`. `identity` holds the **ARM resource ID** of the backend's user-assigned managed identity. The identity must be attached to the application and allowed to read the secret, for example with `Key Vault Secrets User`. The backend therefore needs no Key Vault SDK call for this injection. [Microsoft documentation](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets).

The configuration links `NOTION_OAUTH_ENCRYPTION_KEY` to this Container Apps secret. A URI without a version follows the latest version; Microsoft documents a synchronization that can take thirty minutes and a restart of the consuming revisions. A versioned URI freezes the value. [Key Vault reference rotation](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets#key-vault-secret-uri-and-secret-rotation).

## Hosted Agent: documented references and a limit

`azure.yaml` passes an `env` mapping of strings. `${VAR}` is substituted by `azd`; `${{ ... }}` is resolved on the Foundry side. The documentation describes no `keyVaultUrl` or `secretRef` field in a Hosted Agent's environment. [azure.yaml reference](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-yaml-reference#env). The [extension's official schema](https://github.com/Azure/azure-dev/blob/main/cli/azd/extensions/azure.ai.agents/schemas/azure.ai.agent.json) provides no direct Key Vault reference for this environment either.

Foundry does document the expressions `${{connections.<name>.credentials.<field>}}`, which inject a connection secret at startup. Microsoft specifies that Foundry chooses the name of the backing-store secret: a preexisting Key Vault secret cannot be referenced by name with this mechanism. [Deployment: connection references](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent#reference-project-connections-in-environment-variables).

Conclusion, limited to the sources consulted: no native reference **directly to the preexisting shared Fernet secret** is documented. A CustomKeys connection would be another mechanism, involving a copy to manage. To preserve the single key of [ADR-0009](adr/0009-bff-owns-user-facing-oauth.md), use `SecretClient.get_secret()` with the non-secret parameters `NOTION_OAUTH_KEY_VAULT_URL` and `NOTION_OAUTH_KEY_VAULT_SECRET_NAME`. [Official Python SDK](https://learn.microsoft.com/en-us/azure/key-vault/general/apps-api-keys-secrets#interact-with-azure-key-vault-using-python).

## Identity and authentication

Each Hosted Agent has an Entra identity dedicated to the runtime. The managed identity of the **project** serves infrastructure operations and must not be confused with the agent's. [Hosted Agent identities](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents#agent-identity-and-endpoint). `azure.yaml` forbids adding an `identity` block to the agent service. [Configuration rules](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-yaml-reference#platform-environment-identity-and-endpoints).

`DefaultAzureCredential` includes Azure CLI for development and Managed Identity for Azure. The parameter `managed_identity_client_id` selects an identity by **client ID**, with `AZURE_CLIENT_ID` as the default value. A principal or object ID used for RBAC is not a client ID. [Azure Identity API](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential?view=azure-python). Provide `NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID` as an optional explicit selector, without inventing an identity variable injected by Foundry. The agent object exposes `instance_identity.client_id` and `instance_identity.principal_id` as read-only: the configuration must use the first to select the credential and the second for RBAC. [Agent properties](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-agent?tabs=rest).

To avoid a fallback to another identity when this selector is given, using `ManagedIdentityCredential(client_id=...)` directly is also a deterministic option; `DefaultAzureCredential` stays suited to local development. [Microsoft recommendation for hosted Python apps](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/user-assigned-managed-identity). The Foundry sources consulted do not require an explicit client ID for its runtime identity endpoint and document no automatic `AZURE_CLIENT_ID` injection. The selector's compatibility with the real host therefore stays a criterion for later cloud validation.

In production, `AZURE_TOKEN_CREDENTIALS=ManagedIdentityCredential` restricts the chain to that method with `azure-identity >= 1.24`. Locally, `AZURE_TOKEN_CREDENTIALS=AzureCliCredential` can isolate the existing CLI session. [Credential chains and selecting a credential](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/credential-chains#use-a-specific-credential).

## Precautions and remaining validation

- Fail without showing the secret's value, the SDK response or a raw exception for a missing or invalid key, an impossible authentication or a denied access.
- Allow only reading the secret and the required blobs; do not grant Key Vault rights to the project's identity by confusion.
- Do not replace the Fernet key without migrating the existing tokens: rotating the secret alone would make the old blobs unreadable.
- The simulated tests verify the wiring and the errors. The real RBAC, the Foundry identity, the Container Apps injection and network access remain to be verified in a separately authorized Azure step.
