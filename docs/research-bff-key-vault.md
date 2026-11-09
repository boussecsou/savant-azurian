# BFF et clé Fernet Key Vault — recherche du 8 octobre 2026

Cette note prépare l'étape 0 de Task 26. Elle décrit des capacités documentées,
pas une validation du runtime dans Azure. Aucune opération Azure n'a été exécutée.

## Décision

Le BFF garde la lecture de `NOTION_OAUTH_ENCRYPTION_KEY` : Azure Container Apps
peut injecter la valeur d'un secret Key Vault. Le Hosted Agent lit le même secret
avec `azure-keyvault-secrets` et `azure-identity`. Le stockage des tokens chiffrés
et le protocole OAuth restent inchangés.

## Azure Container Apps : injection native

Container Apps permet de déclarer un secret avec `keyVaultUrl` et `identity`,
puis d'exposer ce secret en variable d'environnement via `secretRef`.
`identity` contient le **resource ID ARM** de l'UAMI `id-sa2-bff`.
L'identité doit être attachée à l'application et autorisée à lire le secret,
par exemple avec `Key Vault Secrets User`. Le BFF n'a donc pas besoin d'un
appel SDK Key Vault pour cette injection.
[Documentation Microsoft](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets).

La future configuration reliera `NOTION_OAUTH_ENCRYPTION_KEY` à ce secret ACA.
Une URI sans version suit la dernière version ; Microsoft documente une
synchronisation pouvant prendre trente minutes et un redémarrage des révisions
consommatrices. Une URI versionnée fige la valeur.
[Rotation des références Key Vault](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets#key-vault-secret-uri-and-secret-rotation).

## Hosted Agent : références documentées et limite

`azure.yaml` transmet un mapping `env` de chaînes. `${VAR}` est substitué par
`azd` ; `${{ ... }}` est résolu côté Foundry. La documentation ne décrit pas de
champ `keyVaultUrl`/`secretRef` dans l'environnement d'un Hosted Agent.
[Référence azure.yaml](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-yaml-reference#env).
Le [schéma officiel de l'extension](https://github.com/Azure/azure-dev/blob/main/cli/azd/extensions/azure.ai.agents/schemas/azure.ai.agent.json)
ne fournit pas non plus de référence directe Key Vault pour cet environnement.

Foundry documente cependant les expressions
`${{connections.<name>.credentials.<field>}}`, qui injectent un secret de
connexion au démarrage. Microsoft précise que Foundry choisit le nom du secret
de backing store : on ne peut pas référencer un secret Key Vault préexistant par
son nom avec ce mécanisme.
[Déploiement : références de connexion](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent#reference-project-connections-in-environment-variables).

Conclusion limitée aux sources consultées : aucune référence native **directe
au secret Fernet préexistant partagé** n'est documentée. Une connexion CustomKeys
serait un autre mécanisme, impliquant de gérer une copie. Pour préserver la clé
unique d'ADR-009, retenir `SecretClient.get_secret()` avec les paramètres non
secrets `NOTION_OAUTH_KEY_VAULT_URL` et `NOTION_OAUTH_KEY_VAULT_SECRET_NAME`.
[SDK Python officiel](https://learn.microsoft.com/en-us/azure/key-vault/general/apps-api-keys-secrets#interact-with-azure-key-vault-using-python).

## Identité et authentification

Chaque Hosted Agent possède une identité Entra dédiée au runtime. L'identité
managée du **projet** sert aux opérations d'infrastructure et ne doit pas être
confondue avec celle de l'agent.
[Identités des Hosted Agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents#agent-identity-and-endpoint).
`azure.yaml` interdit l'ajout d'un bloc `identity` au service agent.
[Règles de configuration](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/azure-yaml-reference#platform-environment-identity-and-endpoints).

`DefaultAzureCredential` inclut Azure CLI pour le développement et Managed
Identity pour Azure. Le paramètre `managed_identity_client_id` sélectionne une
identité par **client ID**, avec `AZURE_CLIENT_ID` comme valeur par défaut.
Un principal/object ID utilisé pour RBAC n'est pas un client ID.
[API Azure Identity](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential?view=azure-python).
Prévoir `NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID` comme sélecteur explicite
optionnel, sans inventer de variable d'identité injectée par Foundry.
L'objet agent expose `instance_identity.client_id` et
`instance_identity.principal_id` en lecture seule : la configuration future
doit utiliser le premier pour sélectionner le credential et le second pour
RBAC.
[Propriétés de l'agent](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-agent?tabs=rest).

Pour éviter un fallback vers une autre identité quand ce sélecteur est fourni,
utiliser directement `ManagedIdentityCredential(client_id=...)` est également
une option déterministe ; `DefaultAzureCredential` reste adapté au local.
[Recommandation Microsoft pour les apps Python hébergées](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/user-assigned-managed-identity).
Les sources Foundry consultées n'imposent pas un client ID explicite pour son
endpoint d'identité runtime et ne documentent pas d'injection automatique
`AZURE_CLIENT_ID`. La compatibilité du sélecteur avec le host réel reste donc
un critère de validation cloud ultérieure.

En production, `AZURE_TOKEN_CREDENTIALS=ManagedIdentityCredential` restreint la
chaîne à cette méthode avec `azure-identity >= 1.24`. En local,
`AZURE_TOKEN_CREDENTIALS=AzureCliCredential` peut isoler la session CLI existante.
[Chaînes et sélection d'un credential](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/credential-chains#use-a-specific-credential).

## Précautions et validation restante

- Échouer sans afficher valeur du secret, réponse SDK ni exception brute pour
  une clé absente/invalide, une authentification impossible ou un accès refusé.
- Autoriser seulement la lecture du secret et des blobs requis ; ne pas
  attribuer les droits Key Vault à l'identité du projet par confusion.
- Ne pas remplacer la clé Fernet sans migration des tokens existants : la
  rotation du secret seule rendrait les anciens blobs illisibles.
- Les tests simulés vérifient le câblage et les erreurs. Le RBAC réel,
  l'identité Foundry, l'injection ACA et l'accès réseau restent à vérifier lors
  d'une étape Azure autorisée séparément.
