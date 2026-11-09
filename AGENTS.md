# Savant Azurian 2 — guide de développement

Agent personnel mono-propriétaire (Python 3.13, LangGraph) hébergé comme Foundry Hosted Agent, plus un BFF FastAPI pour l'OAuth Notion. Monorepo : agent, BFF et PWA (`pwa/`, React + Vite, importée de l'ancien dépôt `sa2-pwa`). La PWA tourne en local ; le BFF et l'agent restent dans Azure. Le prototype historique n'est qu'une référence fonctionnelle : ne pas le migrer tel quel.

Ce projet utilise le skill `microsoft-foundry`. Avant toute modification d'un Hosted Agent, Toolbox, connexion Foundry, commande `azd` ou CI/CD, le lire.

## Cadre d'apprentissage (à respecter)

L'utilisateur construit ce projet pour apprendre et garde la main sur chaque étape Azure. Avant toute authentification, commande `azd`/`az`/`gh` à effet, initialisation, provisionnement ou déploiement : expliquer la commande et son effet, puis attendre une demande explicite. Ne jamais créer ou modifier une ressource Foundry/Azure sans cette demande. Entra/RBAC se font à la main via le Portail, pas via `azd pipeline config`.

Outils : `gh` (`gh auth status`), `az` (`az account show`), `azd` (`azd version`). Sous sandbox, préfixer `az` par `AZURE_CONFIG_DIR=/tmp/sa2-azure-config` si son répertoire de configuration est en lecture seule.

## Commandes

```bash
uv sync --locked --group dev            # installer (identique à la CI)
uv run --locked pytest                  # toute la suite (aucun test ne touche Azure)
uv run pytest tests/test_graph.py::test_nom   # un seul test
uv run --locked python main.py          # agent local sur :8088 (.env + session Azure autorisée)
azd ai agent run                        # Hosted Agent en local contre Foundry

# requirements.txt est généré depuis uv.lock ; la CI échoue s'il diverge
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt

# BFF (port 8090, /readiness)
docker build -f Dockerfile.bff -t sa2-bff:ci . && python3 scripts/smoke_test_bff.py sa2-bff:ci

# Évaluations : sans --run, valident seulement le jeu de données ; --run = appels payants
python scripts/evaluate_semantic_approval.py [--run --trials 5]  # juge de consentement, pass^k
python -m scripts.evaluate_ssh_judge [--run --trials 5]         # juge des commandes SSH, pass^k (docs/ssh-tool.md)
python -m scripts.evaluate_tool_calls [--run --trials 3]        # sélection d'outils, pass^k (docs/tool-call-evals.md)
```

PWA : `cd pwa && npm ci && npm test && npm run build` (Vitest + `tsc`, Node 22, identique à la CI).

Pas de linter ni de formatter configurés — seulement `pytest` et Vitest. Les scripts de CI s'exécutent en modules depuis la racine (`python3 -m scripts.release_plan --component agent`) car ils utilisent des imports relatifs.

Boucle de développement : développer et tester localement → valider avec `azd ai agent run` → `azd provision` seulement pour les ressources nécessaires → `azd deploy` puis smoke test distant. La CI impose tests et qualité ; le CD ne déploie qu'après la CI.

## Architecture

**Deux livrables Azure, un seul package `src/savant/`** (la PWA `pwa/` n'est pas livrée : CI seulement).
- *Hosted Agent* : `main.py` (entrée du déploiement ZIP, exigée à la racine par `azd`) → `savant.agent.main()` → `ResponsesHostServer` (protocole `/responses`). Déployé via `azure.yaml` en code deploy (`remote_build`, `PYTHONPATH=/app/src`) ; `.agentignore` exclut `tests/`, `scripts/`, `docs/` du paquet, donc le runtime ne doit pas en dépendre.
- *BFF* : `savant.oauth_callback` (FastAPI, callback OAuth Notion + routes PWA `bff_api.py` réservées au propriétaire + projets/sessions Cosmos DB, voir plus bas), image `Dockerfile.bff`. N'embarque que les modules listés dans `components.bff.source_files` de `.github/components.json` ; `scripts/package_bff.py` fait échouer le build si un module importé n'y figure pas. Tout nouvel import côté BFF doit être ajouté à ce registre.

**`agent.build_server()` choisit entre trois graphes** selon `Settings` : (1) chat Notion direct avec OAuth + approbation sémantique (`tools/notion_chat.build_direct_chat_graph`, la configuration de `azure.yaml` en production) ; (2) graphe Foundry Toolbox (`tools/notion_foundry`) ; (3) graphe minimal `graph.build_graph` avec outils locaux et Notion MCP optionnel (`tools/notion`). Le modèle est un `ChatOpenAI` en API Responses, authentifié par `DefaultAzureCredential` (aucune clé API), `store=False` avec reasoning chiffré rejoué par LangGraph. `graph.ChatModel` est un `Protocol` pour brancher de faux modèles dans les tests.

LangGraph porte l'orchestration applicative (state, nodes, routing, tools, interruptions) ; Foundry fournit la plateforme (modèles, Managed Identity, endpoint, sessions, hébergement) ; `langchain-azure-ai[hosting]` expose le graphe via `/responses`.

**`config.Settings.from_env()`** valide tout au démarrage et échoue vite (`RuntimeError`) : seules `AZURE_OPENAI_BASE_URL` et `AZURE_AI_MODEL_DEPLOYMENT_NAME` sont toujours requises, mais de nombreuses combinaisons Notion/OAuth/Toolbox sont croisées (callback HTTPS, `NOTION_OWNER_ID` obligatoire en cloud, etc.). Modèle de config : `.env.example`.

**Autorisation des mutations Notion (deux couches indépendantes — ne pas en affaiblir une) :**
- OAuth Notion autorise l'accès à un workspace ; le consentement conversationnel autorise *une opération précise*. L'un ne remplace pas l'autre.
- `tools/notion_policy.py` : catalogue dynamique ; seul un outil portant un indice read-only s'exécute sans approbation, tout le reste est protégé.
- `semantic_approval.py` : un second appel modèle (sortie structurée APPROVE/REJECT/clarification, raisonnement `none`, une relance dans son délai) juge le message de l'utilisateur ; toute modification de ses instructions se mesure en pass^k sur le modèle de production (`--trials 5`) ; `semantic_ledger.py` : autorisation chiffrée, à usage unique, liée au digest de l'opération, au propriétaire, à la conversation et à l'expiration ; réclamée *avant* l'I/O réseau et jamais récupérable automatiquement.
- Tout est *fail closed* : identité manquante (`current_user_id` → `None`), credentials indisponibles, sortie d'approbation invalide ⇒ pas d'écriture. `NOTION_OWNER_ID` sert de clé fixe du propriétaire unique (identité Foundry + `x-agent-foundry-call-id` requis en cloud). Ne jamais journaliser d'ID, token, code OAuth ou query string (`bff_logging.py`, `_safe_operation`).

**Outil SSH** (`tools/ssh.py`, agent seulement) : `ssh_exec` vers la VM Linux. Chaque commande passe par un **juge sémantique** (`ssh.CommandJudge`, second appel modèle isolé) : `RUN` pour la lecture et l'ajout, `CONFIRM` pour la suppression, l'écrasement, une modification d'un ensemble de cibles, un changement durable du système, une commande dictée par un contenu extérieur ou tout doute, `REFUSE` pour une fuite de secrets ; un échec du juge vaut `CONFIRM`. Le plancher codé en dur (`floor_matches`) n'est qu'un filet de sécurité. Une commande confirmée ne s'exécute qu'à un tour utilisateur ultérieur, avec la même empreinte, une seule fois, sans repasser par le juge. Le contenu extérieur lu dans le tour (`spotlight.tainted_turn`) est un indice pour le juge, pas un blocage. Les règles sont dans le prompt système (`tools/ssh_skill.py`, pas d'outil `read_ssh_skill`) ; jusqu'à 4 `ssh_exec` d'une même étape sont jugés et exécutés en parallèle. Le nœud `ssh` est indépendant du consentement Notion. Clé privée dans Key Vault, clé d'hôte épinglée, configuration tout ou rien (`SSH_*`). Détails : `docs/ssh-tool.md`.

**Documents par projet** (`documents.py`, agent ; pipeline `scripts/search_setup.py`) : Azure AI Search `ais-sa2`, index `sa2-docs`, ingestion native (indexeur Blob, découpage et embeddings dans le skillset, `project_id` sur chaque morceau). L'outil de lecture `search_documents(query)` n'existe que si `SEARCH_ENDPOINT` est défini et que la requête porte `metadata.project_id` (mis par le BFF, lu par `request_project`) ; le filtre `project_id eq '<projet>'` est imposé par le serveur, jamais par le modèle. Résultats enveloppés comme données non fiables. Le BFF gère l'envoi, la liste (état réel lu dans l'index et l'indexeur) et la suppression (index d'abord, puis fichier) dans `bff_documents.py` / `document_library.py`, actifs seulement avec `DOCUMENTS_ACCOUNT_URL`, et relaie un événement SSE `sources` (id et nom du fichier, jamais les passages). Détails : `docs/search-documents.md`.

**Toolbox Foundry** : `azure.yaml` pointe `TOOLBOX_ENDPOINT` vers `sa2-web` (recherche web, code interpreter). `sa2-toolbox` (avec Outlook) est mise de côté : sa source Outlook fait échouer `tools/list` pour l'appelant BFF. `tools/toolbox_policy.py` juge chaque appel par nom (y compris l'outil visé par `call_tool` quand « Tool search » est actif) : recherche web et lectures directes, code interpreter, envoi/suppression et tout outil inconnu passent par le consentement sémantique. Détails : `docs/outlook-tool.md`. La PWA et les notices techniques du serveur sont en anglais ; les phrases que le serveur adresse au propriétaire (question de confirmation d'une opération Notion, résultat) suivent sa langue, français ou anglais (`language.py`, `confirmations.py`) : elles sont écrites par le serveur à partir des arguments validés, jamais par le modèle, et le consentement reste jugé par la validation sémantique.

**Fiabilité et observabilité** : `reliability.py` borne tout appel d'outil (timeouts, une seule relance avec backoff pour une lecture en échec transitoire, jamais pour une écriture, arrêt après 8 étapes d'outils), valide les arguments contre le schéma JSON avant l'appel, lit les outils en lecture en parallèle (4 max), coupe un résultat à 20 000 caractères et réduit à un marqueur les résultats antérieurs aux 3 derniers messages de l'utilisateur (seule la copie vue par le modèle change). La Toolbox a un timeout court (12 s) puis une pause de 45 s après échec ; la requête de warm-up du BFF la précharge. Un second modèle rapide (`fast_model_factory`) répond aux tours sans outil et passe la main via `use_tools`. `correlation.py` donne à chaque tour un identifiant de corrélation (empreinte de l'id de réponse Foundry) partagé par les logs de l'agent (`turn_start`/`turn_step`/`turn_end`) et du BFF (`chat_relay_completed`). Détails : `docs/tool-reliability.md`, `docs/observability.md`.

**Contenu extérieur = donnée** (`spotlight.py`) : les résultats réussis de Notion, du web et de la Toolbox sont enveloppés dans `<untrusted_data>` et le system prompt dit que ce contenu n'est jamais un ordre. Cela relève la barre sans suffire : les juges sémantiques (consentement, SSH) et la règle du tour ultérieur restent les vrais verrous.

**Projets et sessions** (BFF seulement, `workspace.py` règles, `workspace_store.py` Cosmos DB for NoSQL en Entra sans clé, `bff_workspace.py` routes) : actif seulement si `COSMOS_ENDPOINT` est défini, sinon aucune route `/api/projects` ni `/api/sessions` et le chat est inchangé. `POST /api/chat` accepte `session_id` ; le BFF relaie `metadata.project_id` (jamais choisi par le modèle) et enregistre le texte du tour, sans arguments ni résultats d'outils. L'agent n'accède pas à Cosmos. La PWA garde un store local et le synchronise vers le BFF (`pwa/src/state/remoteSync.ts`). Ces trois modules sont dans `components.bff.source_files` et dans `exclude` de l'agent. Les rôles de données Cosmos se donnent en CLI, pas dans IAM. Détails : `docs/workspace-cosmos.md`.

**Voix** : le navigateur parle directement à Azure Speech avec un jeton de 10 minutes émis par le BFF (`POST /api/speech/token`, identité managée, rôle Cognitive Services Speech **Contributor** — Speech User n'a pas `issuetoken/action`, `SPEECH_ENDPOINT`/`SPEECH_REGION`) ; seul le texte final passe par le chat existant, avec `mode=voice` relayé en `metadata.channel` pour un style de réponse oral (`identity.VOICE_STYLE`). Pendant les outils, la PWA lit des annonces fixes (`pwa/src/narration.ts`), sans le modèle. Détails : `docs/voice-contract.md`.

**Identité** : `identity.BASE_IDENTITY` est le system message **en anglais** (contenu envoyé au modèle, pas une doc), injecté de façon transitoire à chaque appel modèle, jamais écrit dans `state["messages"]`. Une consigne de langue est ajoutée à chaque tour (`language.language_note`, d'après les messages du propriétaire, le dernier qui porte un signal) : « répondre entièrement dans cette langue, sans en mélanger une autre » (une demande d'un seul mot avait dérivé en espagnol). Une identité personnelle future devra rester dans un fichier/constante séparé pour que la base reste réutilisable.

## CI/CD par composant

`.github/components.json` est la source unique de propriété : pour `agent` et `bff`, ses chemins `runtime` / `exclude` / `source_files` / `ci` pilotent la CI, la planification de release et l'empaquetage ; `non_runtime` (`pwa/**`, docs, tests, scripts, `.github`, `*.md`, `.gitignore`…) ne déploie rien. La section `checks` déclare des contrôles CI sans livraison : `pwa` produit `pwa_ci` pour le job Node. Tout chemin absent du registre déclenche par prudence le déploiement de l'agent **et** la publication du BFF ; toute modification de `components.json` ou de `.agentignore` aussi.
- CI (PR et push `main`) : `uv sync --locked`, contrôle de `requirements.txt` vs `uv.lock`, `pytest`, et build+smoke Docker du BFF seulement si le BFF est touché.
- CD (`cd.yml`) et Publish BFF (`publish-bff.yml`) se déclenchent par `workflow_run` après une CI verte sur un push `main` (jamais sur un commit non validé). `scripts/release_plan.py` compare au dernier checkpoint (artefact `release-<composant>-<sha>`) et ne déploie que si le runtime du composant a changé. Auth Azure par OIDC, jamais de secret Azure permanent.
- **Fusionner du code sous `src/savant/` (hors fichiers BFF) sur `main` déclenche `azd deploy` de l'agent.** Publier une image BFF dans ACR ne met *pas* à jour l'Azure Container App (étape manuelle distincte). Publication automatique du BFF conditionnée par la variable de dépôt `BFF_AUTO_PUBLISH=true`.
- Actions épinglées par SHA de commit avec commentaire de version : garder cette convention. Lire `docs/component-cicd.md`, `docs/cd-workflow.md`, `docs/ci-workflow.md` avant de modifier un workflow ou le registre.

## Tests

`pytest` avec `pythonpath = [".", "src"]` (donc `scripts.*` et `savant.*` importables), pas de `conftest.py`. Faux modèles/serveurs injectés (`FakeModel`, `FakeResponsesHostServer`, `tests/semantic_fakes.py::SimulatedApprovalModel`, `tests/workspace_fakes.py` pour le store Cosmos) ; une réussite de CI ne prouve ni OAuth ni outils en conditions réelles (voir `docs/notion-live-validation-2026-10-25.md`).

## Conventions

Documentation et commits en français ou anglais (conventional commits : `feat`, `fix`, `docs`, `ci`…, PR numérotées en squash) ; petits commits. Aucun secret dans Git : variables d'environnement, Managed Identity/RBAC, Key Vault.
