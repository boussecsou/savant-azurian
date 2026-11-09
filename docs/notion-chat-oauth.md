# Notion MCP direct : OAuth dans le chat

Implémentation initiale du 6 octobre 2026, complétée par la Task 26.2.
La [politique de découverte et de confirmation conversationnelle](notion-semantic-approval.md)
décrit le comportement actuel, les preuves locales et les limites Playground.

Implémentation du flux OAuth : Le runtime appelle le **serveur MCP officiel
Notion**, indépendamment de l’OAuth Custom MCP de Foundry. Le modèle Azure
OpenAI et l’hébergement LangGraph/Responses existants restent utilisés.

## Parcours

1. Une demande nécessite Notion : le modèle appelle `connect_notion` si aucun
   grant valide n’existe pour l’identité utilisateur fournie par Foundry.
2. Le graphe renvoie un lien **Connecter Notion**, mémorise la demande dans
   son checkpoint et termine la réponse. Il n’attend pas le navigateur.
3. Notion affiche son consentement et redirige vers le callback HTTPS.
4. Le callback valide l’état OAuth à usage unique, échange le code avec PKCE
   et conserve les tokens chiffrés. Sa page demande de revenir au chat.
5. Dans **la même conversation**, écrire **« connecté »** : le graphe charge
   les outils Notion autorisés et reprend la demande initiale. Un message de
   confirmation ne suffit pas si le callback n’a pas effectivement réussi.
6. Les outils listés comme écritures passent par l’approbation LangGraph
   existante. Consentement OAuth et approbation d’une modification sont distincts.

Une salutation ne déclenche pas le consentement. Le smoke test exact reste un
appel réel au modèle sans découverte MCP ni lecture du stockage OAuth.
L’agent ne reçoit aucun mot de passe Notion. Les tokens ne sont jamais placés
dans les messages ou arguments des tools ; le lien de consentement est personnel.

## Configuration locale

Installer avec `uv sync --locked --group dev`. Dans un `.env` non commité :

```dotenv
TOOLBOX_ENDPOINT=
FOUNDRY_PROJECT_ENDPOINT=
AZURE_AI_PROJECT_ENDPOINT=
NOTION_MCP_ENABLED=true
NOTION_BACKEND=direct
NOTION_MCP_URL=https://mcp.notion.com/mcp
NOTION_OAUTH_CALLBACK_URL=http://127.0.0.1:8090/oauth/notion/callback
NOTION_OAUTH_STORE_URL=sqlite:///tmp/sa2-notion-oauth/credentials.db
NOTION_LOCAL_USER_ID=local-dev
NOTION_TOOL_POLICY=dynamic
NOTION_READ_TOOL_NAMES=
NOTION_WRITE_TOOL_NAMES=
OAUTH_CALLBACK_PORT=8090
```

Ajouter `NOTION_OAUTH_ENCRYPTION_KEY`, une clé Fernet générée une seule fois
(`uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`).
La garder dans la configuration secrète des **deux processus**. Ne pas la
commiter ni la remplacer à chaque redémarrage : elle déchiffre les grants existants.

Dans deux terminaux, depuis ce dépôt :

```bash
uv run --locked python -m savant.oauth_callback
uv run --locked python main.py
```

Le navigateur doit pouvoir atteindre le callback sur cette machine. Le endpoint
local agent reste `/responses` sur le port 8088. Conserver `previous_response_id`
entre la demande initiale et le message « connecté ». Un test local peut enlever
`FOUNDRY_PROJECT_ENDPOINT` pour utiliser le checkpointer en mémoire ; en cloud
les conversations utilisent le checkpointer Foundry avec isolation utilisateur.

La découverte dynamique expose tous les outils réellement annoncés par le serveur.
Seules les annotations explicites de lecture autorisent une exécution automatique ;
toute opération inconnue ou mutative demande confirmation. Les restrictions du
compte restent appliquées par Notion. Le mode optionnel `NOTION_TOOL_POLICY=allowlist`
restreint les outils aux noms configurés ; la liste de lecture ne peut pas retirer
une protection d'écriture. Une liste d'écriture vide n'impose donc pas un mode
lecture seule en découverte dynamique.

## Préparation cloud, à exécuter séparément

Le code **ne provisionne et ne déploie rien**. `azure.yaml` prépare désormais
Notion direct pour le prochain déploiement autorisé ; modifier le manifeste ne
change pas la version actuellement hébergée.

Le callback est une petite application ASGI indépendante, lançable avec
`python -m savant.oauth_callback`. Il expose `GET /oauth/notion/callback`
et `/readiness`. Il ne faut pas supposer que Foundry publie cette route en
ajoutant simplement le callback au conteneur de l’agent.

Réutiliser le BFF HTTPS et le conteneur Blob privé existants. Les deux processus utiliseront :

```dotenv
NOTION_MCP_ENABLED=true
NOTION_BACKEND=direct
NOTION_OWNER_ID=<cle fixe du proprietaire, identique pour le BFF et l'agent>
NOTION_OAUTH_CALLBACK_URL=https://CALLBACK-HOST/oauth/notion/callback
NOTION_OAUTH_STORE_URL=https://STORAGE.blob.core.windows.net/PRIVATE-CONTAINER/notion-oauth.enc
NOTION_LOCAL_USER_ID=
```

### Clé partagée et identités — étape 0

Le BFF reçoit `NOTION_OAUTH_ENCRYPTION_KEY` via un `secretRef` Container Apps
adossé au secret Key Vault `notion-oauth-encryption-key` et à l'UAMI `id-sa2-bff`.
Il ne lit pas Key Vault via SDK. Son image exclut `azure-keyvault-secrets`.
La configuration native ACA utilise le **resource ID ARM** de cette UAMI.
Pour l'accès Blob du BFF, définir aussi
`NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID` avec son **client ID**.

Le Hosted Agent accepte ces paramètres **non secrets**, à configurer lors de
l'étape 26.2 ; aucune activation Notion n'est faite par cette PR :

```dotenv
NOTION_OAUTH_KEY_VAULT_URL=https://kv-savant-azurian-2.vault.azure.net
NOTION_OAUTH_KEY_VAULT_SECRET_NAME=notion-oauth-encryption-key
NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID=<instance_identity.client_id de l'agent>
```

Ces paramètres remplacent la copie de la clé dans l'environnement de l'agent.
Quand le vault est configuré, le SDK lit le secret au démarrage du backend
Notion direct, le valide comme clé Fernet, puis ferme le client et son credential.
Une erreur refuse le démarrage ; elle ne retourne jamais à une clé d'environnement.
L'URL et le nom du secret doivent être renseignés ensemble. Sans ces paramètres,
la clé d'environnement reste disponible pour le développement local.
Le BFF ignore ces paramètres de vault et exige toujours sa clé injectée.

Avec un client ID explicite, Key Vault et Blob utilisent
`ManagedIdentityCredential(client_id=...)`, sans chaîne de secours.
Dans Foundry, récupérer `instance_identity.client_id` de **l'agent**, pas
l'identité du projet ni le `principal_id` utilisé pour RBAC.
Sans sélecteur, le développement local utilise `DefaultAzureCredential`
(session Azure CLI existante notamment). En production, renseigner le sélecteur
de chaque composant ; valider son fonctionnement réel à l'étape Azure suivante.

Les deux composants doivent pointer vers la même clé et le même blob.
Ne pas faire tourner la clé en créant une nouvelle version du secret sans
migration : Fernet ne pourra plus déchiffrer les tokens existants.
La clé est chargée une fois au démarrage de l'agent. La synchronisation native
ACA peut redémarrer le BFF après une rotation ; coordonner les deux composants.
Les erreurs applicatives sont neutres ; ne pas activer les traces HTTP du SDK.

Les capacités et leurs limites documentées sont détaillées dans
[la recherche Key Vault](research-bff-key-vault.md), avec les sources Microsoft.

### Image BFF et contrôle local

```bash
docker build --file Dockerfile.bff --tag sa2-bff:ci .
python3 scripts/smoke_test_bff.py sa2-bff:ci
```

`Dockerfile.bff` réutilise Python 3.13 et `uv.lock`, démarre
`python -m savant.oauth_callback` sur `0.0.0.0:8090` comme utilisateur non root.
Le contexte Docker est limité au code et aux manifests de dépendances ; aucun
`.env`, état CLI ou fichier de données n'est copié. Les secrets sont fournis
au runtime uniquement. Configurer dans ACA une sonde HTTP `/readiness` sur 8090
à l'étape 26.1 ; le Docker HEALTHCHECK ne remplace pas la configuration ACA.

Le script et la CI testent la vraie image via un port publié sur loopback,
une clé synthétique et un fichier SQLite temporaire. Ils vérifient HTTP 200 et
l'absence du SDK Key Vault. Ils ne prouvent ni RBAC, ni injection Key Vault,
ni accès Blob dans Azure. `/readiness` prouve que le service est démarré ; il
ne réalise pas de requête Notion ou Blob.

Les deux identités Azure doivent pouvoir accéder au conteneur via Managed
Identity (`Storage Blob Data Contributor`, au périmètre du conteneur).
Le chiffrement Fernet protège aussi le contenu avant upload. Les leases Blob
sérialisent les modifications et le refresh entre instances. Aucun SAS ni
secret Azure permanent n’est attendu dans l’URL. Un seul document convient à
ce prototype ; ce choix sérialise toutes les connexions et n’est pas une
architecture de forte concurrence.

Modifier les variables du manifeste de l’agent **avant son futur déploiement**.
Commencer avec `TOOLBOX_ENDPOINT` vide pour isoler Notion. Les autres outils
Toolbox peuvent ensuite coexister avec ce backend direct ; une ancienne source
Notion OAuth dans Toolbox pourrait encore provoquer son propre consentement.
Le graphe ne mélange pas les tokens ni les approbations des deux intégrations.

Le callback désactive les access logs Uvicorn car leur URL contient le code
OAuth. Configurer aussi le proxy et la télémétrie du futur hébergement pour
ne pas conserver ces query strings. Le HTML n’inclut ni code, ni état, ni tokens.

La clé utilisateur vient du contexte **fiable** du Hosted Agent, jamais du
prompt, du thread ID ou des arguments fournis par le modèle. Si elle manque,
l’accès Notion est refusé. L’identité locale n’est pas acceptée en hébergement
Foundry. Le callback rattache les tokens à l’utilisateur de la transaction
initiale et refuse un état expiré, inconnu ou réutilisé.

## Validation et limites

Les tests simulent le fournisseur OAuth et MCP : lien/PKCE, retour callback,
reprise, chiffrement, isolation, expiration, refus, replay, rotation et
approbation/refus d’écriture. Ils ne prouvent pas un consentement réel ni
une lecture cloud. Le consentement personnel, une lecture choisie, le refresh
et une écriture sandbox approuvée puis refusée devront être validés après
la configuration et le déploiement autorisés.

Le serveur renouvelle les tokens près de leur expiration. `invalid_grant`
efface le grant et redemande le consentement. Une découverte MCP renvoyant
401 invalide également le grant. Aucun retry automatique d’une écriture après
un timeout n’est introduit ; relire/réconcilier un résultat incertain.
Un checkpoint ne constitue pas une garantie « exactly once ».

La future PWA pourra reprendre ce même callback et déclencher le tour suivant
après connexion. La version Playground demande volontairement « connecté ».

Sources : [client OAuth Notion](https://developers.notion.com/guides/mcp/build-mcp-client),
[outils officiels](https://developers.notion.com/guides/mcp/mcp-supported-tools),
[contrat Hosted Agent](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract).
