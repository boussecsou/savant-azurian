# Projets et sessions dans Cosmos DB (SDD-005, phase 2)

Le BFF garde les projets, sessions et messages du propriétaire dans Cosmos DB for NoSQL.
Sans `COSMOS_ENDPOINT`, rien ne change : pas de routes `/api/projects` ni `/api/sessions`,
et le chat fonctionne comme avant.

## Ressources (créées à la main dans le Portail)

- Compte `cosmos-db-sa2` (Italy North, Serverless, clés de compte désactivées : Entra seulement).
- Base `sa2` ; conteneurs `projects` (`/id`), `sessions` (`/id`), `messages` (`/sessionId`).
  La clé de partition ne change plus après la création.
- Rôle de données **Cosmos DB Built-in Data Contributor** (`00000000-0000-0000-0000-000000000002`) pour
  l'identité managée du BFF. Les rôles de données Cosmos ne se donnent pas dans « Access control (IAM) » :
  `az cosmosdb sql role assignment create`.
- L'agent n'accède pas à Cosmos pour l'instant (la lecture de sessions par l'agent viendra avec la mémoire).

## Configuration du BFF

| Variable | Rôle |
| --- | --- |
| `COSMOS_ENDPOINT` | Origine HTTPS `*.documents.azure.com` du compte. Active la fonctionnalité. |
| `COSMOS_DATABASE` | Nom de la base (défaut `sa2`). |

## Règles (`workspace.py`)

Tout appartient à un projet ; `Main` existe toujours, ne se renomme ni ne se supprime ; les noms de projet
sont uniques (sans tenir compte de la casse) ; une session appartient à un projet et peut en changer ;
supprimer un projet ou une session supprime ce qu'il contient. On ne garde que le texte, jamais les
arguments ni les résultats des outils.

## Chat avec une session

`POST /api/chat` et `/api/chat/stream` acceptent `session_id`. Le BFF lit alors la session, envoie
`metadata.project_id` à l'agent (jamais choisi par le modèle), continue le fil depuis le dernier
`conversationId` de la session si le navigateur n'en donne pas, puis enregistre le tour (question et réponse)
une fois la réponse terminée. Un échec de stockage est journalisé (`session_persist_failed`, sans contenu)
et n'interrompt jamais la réponse.

## Routes (propriétaire seulement, Easy Auth)

`GET/POST /api/projects`, `PATCH/DELETE /api/projects/{id}`, `GET/POST /api/sessions?project=`,
`PATCH/DELETE /api/sessions/{id}`, `GET /api/sessions/{id}/messages`. Erreurs : 404 inconnu, 409 conflit
ou projet `Main`, 422 donnée invalide, 502 stockage indisponible.

## Déploiement

Nouvelle dépendance `azure-cosmos` : la fusion redéploie l'agent (une fois) et publie l'image du BFF.
Mettre à jour le Container App reste manuel : nouvelle image, variables `COSMOS_ENDPOINT`
(et `COSMOS_DATABASE` si différent), puis `/readiness`.
