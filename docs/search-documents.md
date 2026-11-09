# Documents par projet dans Azure AI Search (tâche 37, PR 1)

Cette PR crée le **pipeline d'ingestion** : on dépose un fichier dans Blob Storage, et Azure AI Search le
découpe, le vectorise et l'indexe tout seul. Elle ne contient que des scripts : rien n'est déployé et le
runtime ne change pas. La recherche (outil de l'agent), l'upload (BFF) et l'interface viennent dans les
PR suivantes. Contexte : SDD-005 §5.3 (D5), §6, et `docs/azure-ai-search-project-scoping.md`.

## Le principe : la vectorisation intégrée

Analogie : une imprimerie. Tu déposes un manuscrit (le PDF) à l'accueil (le conteneur Blob). Le chef
d'atelier (l'**indexeur**) le prend, le découpe en feuillets (**Text Split**), fait traduire chaque feuillet
en « coordonnées GPS du sens » (**embedding**, `text-embedding-3-small`) et range chaque feuillet dans le
grand classeur (**l'index**), avec l'étiquette de son projet.

| Objet | Nom | Rôle |
| --- | --- | --- |
| Source de données | `sa2-docs-blob` | Le conteneur `documents`, lu avec l'**identité managée** du service Search (aucune clé). |
| Skillset | `sa2-docs-skillset` | Découpe (2 000 caractères, chevauchement de 300) puis embedding de chaque morceau. Les *index projections* écrivent un document de recherche par morceau. |
| Index | `sa2-docs` | Un document = un morceau : `chunk`, `chunk_vector`, `title`, `project_id`, `document_id`, `parent_id`. Recherche hybride, ranker sémantique, et un **vectorizer** qui vectorise aussi la question. |
| Indexeur | `sa2-docs-indexer` | Lance le tout, une fois à la création puis toutes les 30 minutes. Le BFF le relancera après chaque upload. |

**Isolation par projet.** Chaque blob portera, depuis le BFF, les métadonnées `project_id` et `document_id`.
Elles sont recopiées sur chaque morceau. `project_id` est *filterable* dès la première version : un champ
existant ne peut pas le devenir plus tard. L'agent ajoutera toujours `project_id eq '<projet>'` lui-même,
jamais le modèle (SDD-005 D6).

**Suppression.** La détection de suppression Blob ne s'applique pas à l'indexation « un vers plusieurs »
(doc Microsoft). Le BFF supprimera donc d'abord les morceaux (`document_id eq '<id>'`), puis le blob (D8).

**Types de fichiers (v1).** PDF texte, DOCX, PPTX, TXT, MD. Les images et les PDF scannés demandent l'OCR
(un skill facturé) : ce sera plus tard. Limites en Basic : 16 Mo par fichier, 512 000 caractères extraits.

## Pourquoi pas l'outil « AI Search » de Foundry ?

| Option | Écartée parce que |
| --- | --- |
| Outil Azure AI Search de la Toolbox | Son filtre est fixe pour toutes les requêtes : impossible d'imposer le projet du tour. |
| Foundry IQ (knowledge base, `knowledge_base_retrieve`) | En preview ; les arguments viennent du modèle ; un appel LLM de plus. |
| Foundry IQ, source « fichiers » | En preview, sans isolation par projet. |

On garde donc l'ingestion **native Azure**. La recherche est un petit outil à nous, avec le filtre imposé
par le serveur (PR 2).

## Étapes manuelles (Portail, par le propriétaire)

1. **Déploiement d'embeddings** : déjà présent. `text-embedding-3-small` (GlobalStandard, 120 000 TPM) est
   déployé sur la ressource Foundry `fp-savant-azurian-2-resource`. Son point d'accès
   `https://fp-savant-azurian-2-resource.services.ai.azure.com` est accepté par le skill et le vectorizer
   (domaines pris en charge : `openai.azure.com`, `services.ai.azure.com`, `cognitiveservices.azure.com`).
2. **Conteneur** : sur `stsavantazurian2`, créer `documents` (accès privé).
3. **Service `ais-sa2`** :
   - *Identity* : activer l'identité managée **système** ;
   - *Keys* : contrôle d'accès « **Role-based access control** » (ou « Both »).
4. **Rôles** (*Access control (IAM)*) :

| Qui | Rôle | Sur | Pourquoi |
| --- | --- | --- | --- |
| Identité de `ais-sa2` | Storage Blob Data Reader | `stsavantazurian2` | L'indexeur lit les fichiers. |
| Identité de `ais-sa2` | Cognitive Services OpenAI User | `fp-savant-azurian-2-resource` | Embeddings à l'indexation et à la requête. |
| Ton compte | Search Service Contributor + Search Index Data Contributor | `ais-sa2` | Lancer ce script et explorer l'index. |
| `id-sa2-bff` (PR 3) | Storage Blob Data Contributor, Search Index Data Contributor, Search Service Contributor | stockage, `ais-sa2` | Upload, suppression des morceaux, lancement de l'indexeur. |
| Identité de l'agent (PR 2) | Search Index Data Reader | `ais-sa2` | Rechercher. |

## Créer le pipeline

Dans `.env` (jamais committé) :

```env
SEARCH_ENDPOINT=https://ais-sa2.search.windows.net
SEARCH_STORAGE_RESOURCE_ID=/subscriptions/<id>/resourceGroups/rg-savant-azurian-2/providers/Microsoft.Storage/storageAccounts/stsavantazurian2
SEARCH_EMBEDDING_ENDPOINT=https://fp-savant-azurian-2-resource.services.ai.azure.com
SEARCH_EMBEDDING_DEPLOYMENT=text-embedding-3-small
```

```bash
uv run --locked python -m scripts.search_setup            # affiche les 4 définitions, n'envoie rien
uv run --locked python -m scripts.search_setup --apply    # crée ou met à jour (PUT, ton identité Entra)
```

Le script est **idempotent** : le relancer met à jour les mêmes objets. Il n'utilise aucune clé et n'affiche
que le code HTTP, ou le message d'erreur du service.

## Vérifier (preuve de la PR 1)

1. Déposer à la main un petit PDF dans `documents/main/test-doc/` et lui ajouter deux **métadonnées** (dans
   le portail : le blob, puis *Metadata*) : `project_id = main` et `document_id = test-doc`.
2. `ais-sa2`, *Indexers*, `sa2-docs-indexer`, **Run**. Attendre « Success ».
3. *Search explorer* sur `sa2-docs`, avec une requête qui contient un mot du PDF et le filtre
   `project_id eq 'main'`. Des morceaux reviennent, avec `title` égal au nom du fichier et
   `document_id = test-doc`.
4. Le même filtre avec `project_id eq 'autre'` ne renvoie **rien** : l'isolation est prête pour la PR 2.

## Recherche par l'agent (PR 2)

L'agent a un outil de lecture `search_documents(query, more_queries?)` (`src/savant/documents.py`). Il n'apparaît que si
`SEARCH_ENDPOINT` est configuré **et** que la requête porte un projet.

- **Le projet vient du serveur.** Le BFF met `metadata.project_id` d'après la session enregistrée
  (Cosmos). `ConversationalResponsesHostServer.build_input` le lit (`request_project`, identifiant simple
  seulement) et l'outil est construit pour ce tour, lié à ce projet. Le modèle ne fournit que `query` (et au plus 3 `more_queries`, d'autres angles de la même question, cherchés **ensemble** dans le même appel et fusionnés : 8 passages au plus, sans doublon, chaque angle représenté — un résumé ou une liste de limites tient en une étape au lieu de cinq, chacune coûtant un appel modèle de 5 à 16 s) ;
  un argument `project_id` ajouté par le modèle est refusé par le schéma. Sans projet, pas d'outil (*fail closed*).
- **La requête** est hybride (mots-clés et vecteur, la question étant vectorisée par le vectorizer de
  l'index) et reclassée par le ranker sémantique (légende extractive). Elle renvoie au plus 5 passages de
  1 200 caractères maximum, avec `document_id` et le nom du fichier.
- **C'est une lecture** : pas d'approbation. Plusieurs recherches dans une même étape partent en
  parallèle (4 au plus), avec les délais et la relance unique de `reliability.py`. Un 429 ou un 5xx
  compte comme une erreur transitoire.
- **Résultats = données extérieures** : ils sont enveloppés dans `<untrusted_data>` (`spotlight.py`),
  comme le web et Notion.
- **Journal** : `documents_search results=<n> ms=<durée>`, jamais la question, un titre ou un passage.
- **Authentification** : `DefaultAzureCredential` de l'agent, portée `https://search.azure.com/.default`,
  aucune clé. Rôle requis pour l'identité de l'agent
  (`fp-savant-azurian-2-resource-fp-savant-azurian-2-sa2-agent-AgentIdentity`, objet
  `<agent-identity-client-id>`) : **Search Index Data Reader** sur `ais-sa2`.
- **Configuration** : `SEARCH_ENDPOINT` et `SEARCH_INDEX` (par défaut `sa2-docs`) dans `azure.yaml`.

## Envoi, liste et suppression par le BFF (PR 3)

Routes réservées au propriétaire (Easy Auth), montées seulement avec l'espace de travail (Cosmos) et
`DOCUMENTS_ACCOUNT_URL` (`bff_documents.py`, règles dans `document_library.py`) :

| Route | Effet |
| --- | --- |
| `GET /api/projects/{id}/documents` | Liste avec l'**état réel** : `ready` (l'index a des morceaux du document), `failed` (erreur de l'indexeur sur ce fichier), sinon `indexing`. |
| `POST /api/projects/{id}/documents?name=<fichier>` | Corps = le fichier brut (pas de formulaire). Types : PDF, DOCX, PPTX, TXT, MD ; 16 Mo au plus. Écrit `documents/{projet}/{document}/{nom}` avec les métadonnées `project_id` et `document_id`, puis lance l'indexeur (un 409 « déjà en cours » suffit : il verra le fichier). |
| `DELETE /api/projects/{id}/documents/{doc}` | Supprime d'abord les morceaux de l'index (filtre `project_id` + `document_id`), puis le fichier. |
| `GET /api/projects/{id}/documents/{doc}/file` | Renvoie le fichier en ligne (un PDF s'ouvre dans le navigateur), `nosniff`. |

- **Le blob est l'enregistrement** : aucune table de plus. Le projet doit exister dans Cosmos ; un document
  d'un autre projet répond 404.
- **Supprimer un projet** supprime aussi ses documents, index d'abord (D8).
- **Ce qui n'est pas montré n'est pas cherché** (règle D8, corrigée le 2026-11-08) :
  - *Suppression immédiate* : la corbeille supprime tout de suite les morceaux, puis le fichier. La PWA
    garde d'abord une copie du fichier en mémoire ; **Undo** la renvoie comme un nouveau document (nouvel
    identifiant, réindexé). Avant, la suppression attendait la fin du toast (6,5 s) : le document masqué
    restait cherchable, et jamais supprimé si l'onglet se fermait.
  - *Indexeur en cours* : un passage qui lisait déjà le fichier écrit ses morceaux *après* la suppression.
    Le BFF attend donc la fin de ce passage en arrière-plan (`settle`, statut lu toutes les 5 s, 200 s au
    plus), puis supprime ce qui n'a plus de fichier visible.
  - *Réconciliation* : chaque `GET …/documents` lit l'index, puis les fichiers (dans cet ordre, pour qu'un
    envoi en cours ne passe jamais pour un orphelin), et supprime les morceaux de tout document absent de la
    liste. Un fichier déposé à la main (identifiant non standard, comme `test-doc`) n'est jamais listé : ses
    morceaux partent, le fichier reste. Au mieux : un échec n'empêche pas la liste.
  - *Garde côté agent* : `search_documents` ignore tout passage dont le document n'a pas un identifiant de
    la liste (32 caractères hexadécimaux).
  - La lecture et la suppression des morceaux couvrent plus de 1000 morceaux par document.
- **Sources dans le chat** : quand l'agent appelle `search_documents`, le relais SSE émet
  `{"type": "sources", "id": <appel>, "sources": [{"documentId", "title"}]}`. Seuls l'identifiant et le nom
  du fichier passent, jamais le texte des passages.
- **Journaux** : `document_added size_kb=…`, `documents_failed error_type=…` ; jamais un nom ni un id.
- **Voix** : pendant `search_documents`, la PWA dit « Je regarde ça dans les sources du projet. » (puis
  d'autres variantes pour les appels suivants), sans le modèle (`pwa/src/narration.ts`).

Configuration du Container App (en plus de `COSMOS_ENDPOINT`) : `DOCUMENTS_ACCOUNT_URL=https://stsavantazurian2.blob.core.windows.net`,
`SEARCH_ENDPOINT=https://ais-sa2.search.windows.net` ; optionnels `DOCUMENTS_CONTAINER` (`documents`),
`SEARCH_INDEX` (`sa2-docs`), `SEARCH_INDEXER` (`sa2-docs-indexer`). `SEARCH_ENDPOINT` seul n'active rien
côté BFF.

Rôles de `id-sa2-bff` (`<bff-identity-principal-id>`) : *Storage Blob Data Contributor* sur le
conteneur `documents`, *Search Index Data Contributor* et *Search Service Contributor* sur `ais-sa2`.

## Interface (PR 4)

`DOCUMENTS_ENABLED` et `ATTACHMENTS_ENABLED` sont activés (`pwa/src/flags.ts`).

- **Sources du projet** : le projet est la portée de tout ce qui suit. Il se choisit en haut du rail
  (sélecteur : un popover qui part du bouton, plus d'onglets Sessions/Projects), puis viennent ses sessions
  et, en bas, la section **Sources · {projet}** (repliable). On ajoute par le bouton + ou par
  glisser-déposer. Chaque ligne montre un badge (PDF, DOC, PPT, MD, TXT), le nom (en entier au survol),
  la taille et l'**état réel** (Uploading… pendant l'envoi, puis Indexing… / Ready / Failed lus par le BFF,
  rafraîchis toutes les 5 s tant qu'un document est en cours). Un clic sur le nom ouvre le fichier. La
  corbeille le retire avec un toast **Undo** de 6,5 s, puis la suppression réelle a lieu (index puis
  fichier).
- **Destination toujours visible** : un fichier déposé n'importe où sur le fil de discussion va aux sources
  du projet actif, et un voile dit « Add to {projet}'s sources » pendant le glisser. Le trombone du composer
  fait la même chose (son infobulle nomme le projet). Plus de puce persistante dans le composer : un toast dit
  « Added … · indexing… », puis « … is ready: Savant can search it » (ou l'échec), même si le rail est replié.
- **Sous la réponse** : « Sources · N », avec une puce par document cité (événement SSE `sources`). Un
  document connu du projet s'ouvre au clic ; un document inconnu (par exemple déposé à la main) est
  seulement nommé.
- **Voix** : « Je regarde ça dans les sources du projet. » pendant la recherche (PR 3).
- Les fichiers refusés (type, taille, vide) sont annoncés par un toast avec la raison donnée par le BFF.
- Les sources sont gardées pour la page en cours seulement, comme les étapes d'outils : elles ne sont pas
  enregistrées dans Cosmos.

Vérifié en local contre le BFF déployé : `GET /api/projects/main/documents` répond 200 par le proxy de
développement. L'envoi, l'indexation, l'ouverture et la suppression restent à vérifier dans l'interface.
