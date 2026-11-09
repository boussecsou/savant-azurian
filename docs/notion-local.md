# Tester Notion MCP en local

Le graphe LangGraph existant reçoit les outils du serveur officiel Notion via
`langchain.mcp.MCPAdapter`. `ToolNode` exécute ces outils sans modifier leurs
schémas, résultats structurés ou erreurs MCP. Les écritures configurées demandent
une approbation avant chaque appel. Il n’y a aucune restriction à une page donnée :
les droits de ton compte OAuth Notion déterminent les pages accessibles.

## Préparer la connexion

Installer les dépendances verrouillées :

```bash
uv sync --locked --group dev
```

Depuis un terminal local, découvrir les noms exacts des outils disponibles :

```bash
uv run --locked python -m savant.tools.notion
```

Cette commande ouvre le navigateur pour te connecter à Notion, puis affiche le
catalogue d’outils. Elle ne lit ni ne modifie de page et ne contacte pas Azure.

Si l’ouverture automatique affiche `gio: Operation not supported`, ouvrir
manuellement l’URL d’autorisation affichée dans le terminal, en gardant la commande
active. Le callback `localhost` doit être accessible depuis ce navigateur.

L’inscription OAuth demande explicitement le mode client public `none` avec PKCE,
accepté par Notion. Cela évite le défaut du SDK MCP qui duplique `client_id` dans
les requêtes utilisant HTTP Basic
([issue du SDK](https://github.com/modelcontextprotocol/python-sdk/issues/3138)).

Dans ton `.env` local, garder les variables Azure OpenAI existantes et ajouter :

```dotenv
NOTION_MCP_ENABLED=true
NOTION_MCP_URL=https://mcp.notion.com/mcp
NOTION_READ_TOOL_NAMES=NOMS_EXACTS_DES_OUTILS_DE_LECTURE_SEPARES_PAR_DES_VIRGULES
NOTION_WRITE_TOOL_NAMES=NOMS_EXACTS_DES_OUTILS_D_ECRITURE_SEPARES_PAR_DES_VIRGULES
```

Placer les outils de recherche/lecture dans la première liste, et ceux qui
modifient Notion dans la seconde. Un même nom ne peut pas apparaître dans les deux.
Laisser la seconde vide permet de tester seulement la lecture. Les outils absents
des listes ne sont pas exposés au modèle ; un nom inconnu fait échouer le démarrage
avec les noms proposés par le serveur.

## Lancer et lire une page

```bash
uv run --locked python main.py
```

Le démarrage demande la connexion OAuth Notion avant d’ouvrir le serveur. Les
tokens OAuth restent en mémoire : il faut se reconnecter après chaque redémarrage,
y compris après la commande de découverte du catalogue. Le modèle utilise
l’authentification Azure existante ; aucune commande de connexion ou de déploiement
Azure n’est lancée par cette intégration.

Dans un second terminal :

```bash
curl --fail-with-body http://localhost:8088/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Lis cette page Notion et résume-la : https://app.notion.com/p/3eceba09656f80ce9afde9a578089703","stream":false}'
```

## Tester une écriture avec approbation

Demander une petite modification sur une page de ton choix, par exemple ajouter
un paragraphe « Test local Savant Azurian 2 ». L’agent retourne une sortie
`mcp_approval_request`. Son champ `arguments` contient le nom de l’outil, ses
arguments exacts et l’identifiant de l’appel, dans l’enveloppe d’interruption
LangGraph. Vérifier ces arguments avant de répondre.

Reprendre avec l’identifiant `id` de cette sortie et le `id` de la réponse initiale :

```bash
curl --fail-with-body http://localhost:8088/responses \
  -H 'Content-Type: application/json' \
  -d '{"previous_response_id":"ID_DE_LA_REPONSE","input":[{"type":"mcp_approval_response","approval_request_id":"ID_DE_LA_DEMANDE","approve":true}],"stream":false}'
```

Avec `approve:false`, le serveur signale `interrupt_rejected` et n’exécute pas
l’écriture. Les interruptions et conversations restent en mémoire pour ce test
local et disparaissent au redémarrage du processus.

## Validation automatique

```bash
uv run --locked pytest
```

Les tests utilisent des modèles et transports simulés : ils couvrent le câblage,
les listes d’outils, les résultats et erreurs MCP, et l’approbation/refus des
écritures. La connexion OAuth et les appels réels à Notion sont à vérifier avec
le test local ci-dessus. L’intégration est désactivée par défaut dans
`.env.example`. Aucun changement de configuration Azure ou de déploiement n’est
nécessaire pour cette étape.
