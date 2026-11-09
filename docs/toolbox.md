# Toolbox Foundry de Savant

Le runtime consomme la toolbox existante `toolbox-lab-1` via son endpoint
consommateur. `azure.yaml` configure cette URL stable dans `TOOLBOX_ENDPOINT`.
Elle suit la version publiée par défaut (`default_version`).
Le modèle Azure OpenAI existant reste utilisé ; l'exemple `model-router`
n'est pas une obligation pour connecter une toolbox.

Pour tester localement, ajouter à `.env` :

```dotenv
TOOLBOX_ENDPOINT=https://fp-savant-azurian-2-resource.services.ai.azure.com/api/projects/fp-savant-azurian-2/toolboxes/toolbox-lab-1/mcp?api-version=v1
NOTION_MCP_ENABLED=false
```

Le project endpoint est extrait de cette URL pour le checkpoint Foundry.
Le mode Toolbox expose tous les outils découverts, ainsi que `echo`, sans
nécessiter les listes Notion. Les deux modes sont exclusifs. La découverte
s'effectue dans les nœuds du graphe, sous le contexte utilisateur de la requête,
sans appel réseau au démarrage ni cache partagé entre utilisateurs.

Les outils marqués `require_approval=always` par la toolbox passent par notre
interruption LangGraph avant exécution. Les éventuels noms dans
`NOTION_WRITE_TOOL_NAMES` restent également protégés. Ce mode ne déduit pas
les écritures à partir du nom : configurer les approbations dans la toolbox.
Le consentement OAuth reste distinct et ses instructions sont affichées à
l'utilisateur lorsqu'il est nécessaire.

## Compatibilité du SDK installé

`langchain-azure-ai` installé ne possède pas de paramètre `toolbox_version`.
`EndpointToolbox` surcharge la propriété `toolbox_endpoint` pour utiliser
l'URL configurée, consommateur ou versionnée, y compris pour la découverte
des approbations.

Son transport historique utilise `langchain-mcp-adapters`, qui importe
`RequestContext` supprimé de MCP 2. Le backend direct existant utilise
`langchain[mcp]`, qui exige MCP 2 : épingler MCP 1 casserait ce backend.
Notre adaptateur utilise donc `fastmcp.Client` et `langchain.mcp.MCPAdapter`,
comme le backend direct, en conservant l'authentification, le renouvellement
du token, les headers de contexte Foundry et la gestion du consentement du SDK.
L'auth SDK est adaptée au type `httpx2.Auth` utilisé par FastMCP 4.

Références : [intégration officielle Toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox),
[incompatibilité MCP 2](https://github.com/langchain-ai/langchain-mcp-adapters/issues/589),
[nouvel adaptateur LangChain](https://github.com/langchain-ai/langchain/issues/40072).

La modification du manifeste ne met pas à jour l'agent déjà déployé.
Il faut publier une nouvelle version pour utiliser cette configuration dans
le Playground. La découverte locale ne prouve pas à elle seule le consentement
ni l'accès de l'utilisateur via le Hosted Agent.

## Déploiement et consentement personnel

La CD teste le runtime et le vrai modèle avec une requête dédiée sans tools.
Elle ne demande aucun consentement pour l'identité du pipeline. L'utilisateur
termine OAuth manuellement dans une conversation normale du Playground.
Une CD verte ne constitue pas une validation opérationnelle de Notion.
Voir `docs/cd-workflow.md` pour le contrôle exact et ses limites.

## Modifier la toolbox sans redéployer l'agent

Modifier les outils crée une nouvelle version immuable. La publier comme
version par défaut rend cette version disponible via l'endpoint consommateur.
Créer ou sauvegarder une version sans la promouvoir ne change pas les outils
servis à l'agent. Le graphe redécouvre les outils et leurs approbations dans ses
nœuds ; il ne conserve pas de liste figée entre requêtes.

Après le déploiement initial de ce changement d'endpoint, les publications
suivantes ne nécessitent aucune modification de code ni aucun redéploiement
de Savant. Éviter de publier au milieu d'une opération avec des tools : une
version différente peut être découverte entre la décision et l'exécution.
Tester les nouvelles configurations dans une nouvelle conversation. Un nouvel
outil ou une nouvelle connexion peut nécessiter un consentement personnel.

Une URL `/versions/<n>/mcp` reste acceptée pour tester une version précise,
mais ne suit pas les publications suivantes.
