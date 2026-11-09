# Notion MCP dans Savant : choix d’architecture

Recherche documentaire du **6 octobre 2026**, sources primaires consultées sur le web. Aucun appel Azure, enregistrement OAuth, consentement ou appel Notion authentifié effectué. Les observations cloud ci-dessous datent du **2 octobre**, selon la passation locale ; elles ne décrivent pas un état Azure relu aujourd’hui.

## Décision proposée

**Qualifier d’abord le chemin Hosted Agent LangGraph → Toolbox Foundry → serveur MCP officiel Notion.** Il est déjà raccordé dans Savant. Faire une qualification bornée du client OAuth et de la reprise utilisateur, plutôt qu’ajouter immédiatement un backend qui gère les tokens. Si un obstacle reproductible subsiste, passer à un client Notion MCP côté backend avec OAuth propre et stockage durable. Cette décision est une recommandation d’architecture, pas une compatibilité opérationnelle déjà prouvée.

Une interface confortable et un BFF ne changent pas nécessairement ce choix : un BFF peut porter les sessions de l’application, le streaming, les boutons de consentement et les confirmations, tout en laissant Foundry gérer OAuth Notion. « Ajouter un backend » et « déplacer OAuth Notion vers ce backend » sont deux décisions distinctes.

## Ce que le dépôt prouve

[toolbox.md](toolbox.md), [notion-foundry.md](notion-foundry.md), [notion-local.md](notion-local.md) et la passation `/tmp/sa2-handoff-2026-10-06.md` décrivent :

- Agent v12 et smoke test modèle réussis le 2 octobre ; 45 tests locaux réussis. Le smoke test contourne volontairement la découverte des outils.
- Endpoint consommateur configuré. À la dernière inspection, v3 existait mais `default_version` restait `1`. Une version créée ne constitue pas une promotion ; ne pas diagnostiquer l’ancienne erreur à partir de v3 seule.
- Consentement Notion atteint ; contexte transmis par le parent de recherche : erreur `Unknown OAuth client`. Aucune lecture ni écriture réelle démontrée. Cette erreur suggère de vérifier l’enregistrement du client ; elle ne prouve pas la cause exacte.
- [notion_foundry.py](../src/savant/tools/notion_foundry.py) charge les outils dans le contexte de la requête, reprend les politiques d’approbation et conserve un adaptateur de compatibilité MCP. [approval.py](../src/savant/tools/approval.py) interrompt l’appel avec nom, arguments et identifiant avant exécution.
- Le backend direct local utilise un callback navigateur local et des tokens en mémoire. C’est une base de validation, pas une solution multi-utilisateur durable.

Les sections anciennes de `notion-foundry.md` évoquant l’absence de connexion ne doivent pas être lues comme un inventaire cloud actuel.

## Ce que les sources officielles établissent

Toolbox centralise les outils et expose un endpoint MCP réutilisable entre runtimes. C’est une raison de conserver cette abstraction dans Savant tant qu’elle fonctionne. [Présentation Microsoft](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/toolbox-overview).

Microsoft documente `AzureAIProjectToolbox` pour LangGraph. L’endpoint consommateur suit `default_version` ; la promotion change les outils servis sans redéployer l’agent. Le runtime doit appliquer `require_approval` : l’endpoint MCP Toolbox ne bloque pas lui-même les appels exigeant une approbation. [Hosted Agent et Toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent).

Foundry distingue l’identité de l’agent vers Toolbox et celle de l’utilisateur vers le service. OAuth sur la connexion gère acquisition, injection et renouvellement. Le contexte de l’appel Hosted doit être transmis ; la seule Managed Identity du BFF ne représente pas son utilisateur. Les consommateurs OAuth ont besoin du rôle **Foundry Agent Consumer** et du même tenant Entra que le projet ; l’échange inter-tenant n’est pas pris en charge dans ce parcours. [Authentification Toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/tool-authentication).

OAuth personnalisé demande un client ID ; le secret est facultatif selon le client. Le callback est fourni après configuration. La documentation explique `oauth_consent_request`, puis la continuation avec `previous_response_id`. Elle ne fournit pas ici de preuve que DCR automatique ou PKCE Notion fonctionne dans cette configuration. [Authentification MCP Foundry](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/mcp-authentication).

Les [métadonnées publiques Notion](https://mcp.notion.com/.well-known/oauth-authorization-server) annoncent `/authorize`, `/token`, `/register`, `authorization_code`, `refresh_token`, PKCE `S256`, les méthodes client `none`, `client_secret_basic`, `client_secret_post`, le scope `default` et le support de Client ID Metadata Documents (`client_id_metadata_document_supported`). Microsoft recommande génériquement `offline_access`, mais il n’est pas annoncé ici : ne pas l’ajouter sans validation fournisseur.

Notion exige un client OAuth avec PKCE, refresh et stockage sécurisé. Son guide décrit DCR et confirme CIMD comme alternative. Les identifiants d’une intégration REST ne doivent donc pas être présumés valables pour le serveur MCP. Les tokens web restent côté serveur ; la rotation exige persistance atomique et refresh sérialisé. `invalid_grant` conduit à reconnecter. [Guide client Notion](https://developers.notion.com/guides/mcp/build-mcp-client).

**CIMD supporté par Notion ne signifie pas CIMD supporté par Foundry.** De même, OAuth disponible des deux côtés ne prouve pas leur interopérabilité.

## Comparaison appliquée à Savant

| Option | Gain pour Savant | Travail et limite |
| --- | --- | --- |
| Hosted Agent + Toolbox | Réutilise le chemin existant ; gestion OAuth déléguée ; outils modifiables par promotion | Prouver Notion/PKCE/refresh et reprise ; population Entra compatible |
| Interface + BFF devant Foundry | Parcours connexion, progression et confirmations adaptés à l’utilisateur ; futur canal vocal | Préserver l’identité et les IDs ; ne résout pas seul un client OAuth incompatible |
| Backend client direct Notion MCP | Contrôle du callback, PKCE, identité applicative et expérience de reconnexion | Construire stockage tokens, rotation, isolation, révocation, erreurs et exploitation |

Ce tableau exprime les conséquences de conception déduites des contraintes officielles et du code, pas des mesures de coût ou de latence. Ajouter une couche réseau n’offre aucune garantie de performance ; mesurer le parcours réel avant d’optimiser.

## Qualification bornée à effectuer ensuite

La recherche autorise ce rapport uniquement. Les modifications cloud suivantes restent soumises au cadre d’apprentissage d’`AGENTS.md`.

1. Relire la version par défaut et la connexion effectivement servies ; comparer à la configuration Notion attendue. Écarter d’abord une mauvaise version.
2. Vérifier le client ID de la connexion, le callback HTTPS réel et son enregistrement Notion. Un préenregistrement DCR peut suffire en principe, sous réserve que Foundry produise PKCE et un échange token compatibles. Résoudre le callback avant d’enregistrer ; ne pas inventer une URL ni réutiliser des credentials REST.
3. Observer sans journaliser de secrets les paramètres utiles : callback, présence de `code_challenge_method=S256`, méthode client, scope. Contrôler l’erreur exacte si le client reste inconnu.
4. Faire consentir personnellement l’utilisateur, reprendre la demande et lire une page choisie. Vérifier le résultat réel, puis l’accès d’un autre utilisateur isolé si le produit vise plusieurs personnes.
5. Vérifier renouvellement et reconnexion, puis une écriture limitée avec approbation, un refus et une reprise après redémarrage. Conserver IDs non secrets et résultats attendus comme preuves.

Arrêter la qualification si le callback/client ne peut être configuré, si PKCE est absent ou incompatible, ou si refresh/reprise échoue durablement avec une configuration vérifiée. Documenter la reproduction avant de choisir le backend direct ; ne pas multiplier les changements Azure sans preuve.

## Critères de bascule et expérience confortable

**Garder Toolbox** si lecture, refresh, isolation et approbations passent, et si les utilisateurs prévus peuvent utiliser le tenant Foundry. Un BFF fin peut ensuite afficher « Connecter Notion », conserver `previous_response_id` et l’identifiant de demande d’approbation, et présenter cible et arguments avant confirmation. Le code actuel retourne aussi des instructions de consentement via un outil synthétique ; vérifier le format réellement reçu, sans supposer un item natif identique à celui des Prompt Agents.

**Choisir le backend direct** si incompatibilité OAuth reproductible, limites de reprise persistantes, ou produit visant des utilisateurs externes dont l’identité ne convient pas au parcours Entra documenté. Ces besoins peuvent justifier cette option avant même une panne technique. Réutiliser le transport existant, mais remplacer callback local et mémoire volatile par callback HTTPS, grants isolés et stockage durable chiffré. Choisir une bibliothèque après validation avec le lockfile existant ; ne pas recopier aveuglément un exemple SDK.

Pour la voix, conserver une interface web accessible pour le consentement navigateur et un affichage de la modification proposée. Prévoir une confirmation liée à la demande exacte, des états attente/refus/expiration et une reprise après coupure. C’est une proposition UX ; le MCP seul ne fournit pas ces interactions.

Le consentement OAuth autorise l’accès à Notion ; il n’approuve pas une écriture donnée. Une reprise ou un timeout ne garantit pas l’exécution unique : après résultat d’écriture incertain, relire et réconcilier avant de relancer. Ni un checkpoint ni le BFF ne prouvent une garantie « exactly once ». Ces contrôles sont à qualifier sur le runtime Savant, indépendamment du choix du gestionnaire OAuth.
