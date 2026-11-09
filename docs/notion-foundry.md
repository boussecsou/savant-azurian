# Notion dans Foundry : validation préalable

La voie directe avec lien OAuth dans le chat est maintenant implémentée dans
[notion-chat-oauth.md](notion-chat-oauth.md). Elle contourne la connexion Custom
MCP Foundry ; le consentement et la lecture cloud restent à valider. Les sections
ci-dessous décrivent l’intégration Foundry antérieure.

État au 2 octobre 2026 : **backend cloud écrit ; compatibilité OAuth réelle non validée**.
Le test local direct reste disponible dans [notion-local.md](notion-local.md).
La présence de fonctionnalités OAuth dans les deux produits ne constitue pas
une preuve de compatibilité. Aucune connexion ni toolbox Azure n’a été créée
pendant cette investigation. Le runtime dispose maintenant d'un backend Foundry,
désactivé dans `azure.yaml`. La CD et son smoke test restent indépendants de Notion.

## Paramètres vérifiés

Les [métadonnées publiques Notion](https://mcp.notion.com/.well-known/oauth-authorization-server)
annoncent :

| Paramètre | Valeur |
| --- | --- |
| Serveur MCP | `https://mcp.notion.com/mcp` |
| Autorisation | `https://mcp.notion.com/authorize` |
| Token et renouvellement | `https://mcp.notion.com/token` |
| Enregistrement dynamique | `https://mcp.notion.com/register` |
| Scope annoncé | `default` |
| PKCE | `S256` disponible |
| Grants | `authorization_code`, `refresh_token` disponibles |
| Authentification client | `none`, `client_secret_basic`, `client_secret_post` |

Ne pas ajouter `offline_access` : il n’est pas annoncé par Notion.
Le [guide client Notion](https://developers.notion.com/guides/mcp/build-mcp-client)
décrit l’enregistrement dynamique. Il reste à vérifier comment enregistrer le
callback HTTPS réel de Foundry et le client correspondant ; ne pas utiliser
automatiquement les identifiants d’une intégration REST Notion.

[Foundry OAuth](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/mcp-authentication)
documente un OAuth géré ou personnalisé, un callback fourni après configuration
et un lien de consentement par utilisateur. La documentation consultée ne
confirme pas une entrée Notion dans le catalogue du projet ni la compatibilité
de l’enregistrement dynamique avec ce flux personnalisé.

[Toolbox Hosted Agent](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent)
confirme `AzureAIProjectToolbox` pour LangGraph. Les outils doivent être chargés
avec le contexte de la requête. Le consentement et sa reprise dans le host
LangGraph actuel restent à prouver dans le Playground.

## Étape Azure à autoriser

Mise à jour du 2 octobre : une session Azure habituelle déjà authentifiée a été
vérifiée hors sandbox, sans nouvelle connexion. L'inspection réelle du projet
montre uniquement une connexion Application Insights et `FoundryMCPServerpreview`,
ainsi qu'une toolbox `toolbox-lab-1`. Aucune connexion Notion ni toolbox
`sa2-notion-tools` n'existe dans le projet lors de cette vérification.
Les observations suivantes décrivent la tentative historique dans le répertoire
temporaire, pas l'état de la session Azure habituelle.

La dernière tentative Azure CLI avec `AZURE_CONFIG_DIR=/tmp/sa2-azure-config`
n’a pas été finalisée, puis a été annulée par l’utilisateur. Ne pas reprendre
cette ancienne autorisation. `az login` ouvrirait une authentification interactive
et enregistrerait une session dans ce répertoire. Cette commande attend une
demande explicite, conformément au cadre d’apprentissage du dépôt.

Après cette autorisation, inspecter le catalogue du projet existant
`fp-savant-azurian-2` sans créer de ressources. Si Notion propose l’OAuth géré,
préparer cette connexion ; sinon préparer les paramètres d’OAuth personnalisé
et vérifier l’enregistrement du callback et PKCE. Présenter la configuration
concrète avant toute création de connexion ou de toolbox.

La création autorisée devra porter uniquement sur la connexion Notion et la
toolbox `sa2-notion-tools`, dans le projet existant. Elle stockera la configuration
OAuth côté Foundry. Le consentement personnel devra être effectué par
l’utilisateur. Aucun token Notion ne doit être copié dans le conteneur ou Git.

## Critère de passage au runtime

Enregistrer les preuves suivantes sans conserver les tokens ni les liens de
consentement sensibles :

1. Connexion utilisant le serveur officiel et l’identité personnelle.
2. Lien de consentement réel, consentement réussi et reprise de la demande.
3. Découverte des noms exacts des outils et lecture réussie d’une page choisie.
4. Renouvellement compatible avec le scope `default` et absence de callback local.

En cas d’échec, documenter l’erreur et arrêter ; ne pas ajouter de service OAuth
de substitution. Tant que ces preuves manquent, conserver Notion désactivé dans
le déploiement.

Le code peut être préparé et testé avec des transports simulés avant cette
validation ; seule son activation cloud dépend des preuves ci-dessus.
Les backends `direct|foundry`, le chargement par requête, le filtrage des noms
préfixés, les approbations d’écriture et `FoundryCheckpointSaver` sont maintenant
implémentés. Vérifier également la persistance des réponses et
l’isolation utilisateur ; un checkpoint seul ne garantit ni la reprise via
`previous_response_id`, ni l’exécution unique d’une écriture. Tester lecture,
approbation, refus et reprise après redémarrage dans le Playground. Le smoke test
CD doit rester indépendant du consentement OAuth.

## Backend implémenté et configuration

`src/savant/tools/notion_foundry.py` utilise `AzureAIProjectToolbox` et charge
les outils dans les nœuds asynchrones, sous le contexte courant du host.
Aucun appel toolbox au démarrage, aucun cache de tools entre utilisateurs et
aucun identifiant d'appel utilisateur construit ou mémorisé par l'application.
Les listes doivent contenir les noms complets renvoyés par la toolbox, par
exemple `notion___<nom-exact>` : aucun retrait automatique de préfixe.
Les outils hors listes ne sont pas exposés. Les écritures listées et les outils
sélectionnés marqués `require_approval=always` passent par la même interruption.

Pour une toolbox existante et autorisée, configurer :

```dotenv
NOTION_MCP_ENABLED=true
NOTION_BACKEND=foundry
NOTION_TOOLBOX_NAME=sa2-notion-tools
FOUNDRY_PROJECT_ENDPOINT=https://<compte>.services.ai.azure.com/api/projects/<projet>
NOTION_READ_TOOL_NAMES=<noms-complets-validés>
NOTION_WRITE_TOOL_NAMES=<noms-complets-validés>
```

Foundry fournit le project endpoint dans le cloud. Le checkpointer utilise
`user_isolation=True`. Le host officiel gère le stockage des réponses et des
chaînes de conversation ; ne pas le remplacer par un stockage en mémoire.

Lors du consentement requis pendant la découverte, le SDK renvoie un outil
synthétique `oauth_consent_required`. Le graphe affiche ses instructions sans
appel au modèle et retente la découverte à la prochaine requête. Ce parcours
n'émet pas lui-même un item natif `oauth_consent_request` : le comportement du
Playground et la reprise via `previous_response_id` restent à vérifier.
Le SDK peut journaliser le lien de consentement : traiter ces logs comme sensibles.
Un consentement qui expire pendant un appel d'outil peut être renvoyé comme une
erreur d'outil ; réauthentifier puis réessayer explicitement, sans relancer
automatiquement une écriture. Pas de garantie d'exécution unique.

Créer la connexion et la toolbox dans le portail Foundry ou Foundry Toolkit,
avec OAuth personnel et uniquement le serveur officiel, après accord explicite.
Découvrir et vérifier les outils de lecture avant d'autoriser les écritures.
Les valeurs du manifeste sont préparées, mais `NOTION_MCP_ENABLED` y reste
explicitement `false` jusqu'à la validation. Les listes du manifeste restent
vides : les renseigner avec les noms validés au moment de l'activation.
La publication du code via CI/CD ne valide pas OAuth et n'active pas Notion.

## Compatibilité : recherche complémentaire du 2 octobre

Notion impose Authorization Code avec PKCE, stockage sécurisé et renouvellement
des tokens. Son enregistrement de client et le callback HTTPS de Foundry doivent
encore être associés. La [liste Microsoft des connecteurs OAuth gérés](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol)
ne contient pas Notion : suivre le parcours OAuth personnalisé.

Une [discussion du dépôt Microsoft](https://github.com/microsoft-foundry/new-foundry-portal/issues/109)
signale des difficultés de clients publics ; une réponse de l'équipe indique
croire que PKCE est supporté, sans fournir de confirmation opérationnelle pour
Notion. Cette discussion ne démontre donc ni compatibilité ni incompatibilité.
Ne pas basculer vers une PWA uniquement sur cette base. La prochaine preuve
nécessaire reste une connexion OAuth personnalisée, le consentement de
l'utilisateur et une lecture réelle, avant l'activation du backend.


## Raccordement de toolbox-lab-1 version 2

L'utilisateur a créé cette toolbox et fourni son endpoint. Le mode général
`TOOLBOX_ENDPOINT`, configuré dans `azure.yaml`, expose tous ses outils ;
il fonctionne avec `NOTION_MCP_ENABLED=false`, qui désactive uniquement
le backend Notion spécifique décrit plus haut. Voir `docs/toolbox.md`.

La découverte réelle de la version 2 a atteint Foundry et obtenu une demande
de consentement pour la connexion Notion. Le consentement reste manuel et
aucune lecture/écriture Notion n'est encore validée par ce raccordement.
La CD teste séparément le runtime et le modèle ; voir `docs/cd-workflow.md`.
