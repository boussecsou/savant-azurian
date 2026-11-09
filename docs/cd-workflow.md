# CD — Savant Azurian 2

Mis à jour le 2 octobre 2026. Workflow implémenté : `.github/workflows/cd.yml`.

## Commit autorisé et identité de déploiement

La CD démarre après une CI réussie issue d'un push sur `main` dans ce dépôt.
Elle récupère le SHA exact du run CI. Un déclenchement manuel reste possible
sur `main`, mais vérifie également qu'une CI de push a réussi sur le SHA choisi.
Le job consulte l'API GitHub avec `actions: read` avant toute connexion Azure.

Les permissions sont `contents: read`, `actions: read` et `id-token: write`.
`azure/login` échange le jeton OIDC GitHub contre un accès Azure temporaire.
L'app registration et son service principal existent déjà, avec une identité
fédérée limitée à `repo:<owner>/<repo>:ref:refs/heads/main`.
Aucun secret Azure permanent n'est ajouté. `azd` utilise la session Azure CLI.

Les variables GitHub existantes fournissent les identifiants Azure, la région,
le projet et la configuration modèle. Le workflow conserve les noms existants
pour éviter une migration des variables. `TOOLBOX_ENDPOINT` est directement
versionné dans `azure.yaml` ; il ne nécessite pas de nouvelle variable GitHub.

Depuis la migration du 8 octobre 2026, `FOUNDRY_MODEL_NAME` sélectionne le
déploiement existant `sa2-gpt-6-luna`. La base Azure OpenAI reste en `/openai/v1/`.
Le client utilise Responses avec un historique géré par LangGraph ; voir
[la configuration du modèle](model-gpt-6-luna.md).

## Déploiement et dépendances

Le workflow vérifie que `requirements.txt` correspond à `uv.lock`, puis lance
`azd deploy sa2-agent --no-prompt` sur le projet existant. Aucun provisioning
ni création de connexion/toolbox n'est ajouté.

Le service reste en `remote_build`, Python 3.13, entrée `main.py`.
`requirements.txt` contient les versions de production exportées du lockfile.
`.agentignore` exclut notamment les fichiers `.env`, les états CLI, les logs
utilisateur et les documents du ZIP, indépendamment des exclusions Git.

Après déploiement, le workflow lit `AGENT_SA2_AGENT_VERSION`, vérifie son format,
puis enregistre le SHA et la version dans le résumé GitHub. Un déploiement
réussi sans sortie de version valide fait échouer le job.

## Smoke test : runtime et modèle

`scripts/smoke_test.py` invoque explicitement `sa2-agent` et la version publiée,
avec `--protocol responses`, une nouvelle session et une nouvelle conversation.
La requête expire après 180 secondes, et le processus après 240 secondes.

Le message exact défini dans `savant.health` sélectionne, uniquement dans une
conversation neuve, un appel au **vrai modèle sans tools**. Il ne découvre pas
la toolbox et ne demande pas de consentement personnel. Ce chemin n'exécute
aucune action externe et ne retourne pas une réponse codée en dur.

Le vérificateur exige HTTP 200, une réponse Responses `completed`, sans erreur
ni appel/approbation de tool, et le texte exact `SA2_RUNTIME_MODEL_OK`.
Il accepte le résultat JSON et le résultat SSE `response.completed`.
Une sortie non vide ou une instruction de consentement ne suffit plus.

La sortie brute et stderr de l'invocation sont capturés en mémoire et ne sont
ni imprimés ni téléversés comme artefact. Le résumé ne contient que le SHA,
la version, le résultat du contrôle et sa durée. Les liens de consentement,
headers et identifiants de session restent hors logs du smoke test.
Cela ne supprime pas les journaux produits côté Foundry par le SDK.

## Validation personnelle des tools

L'identité GitHub CD déploie et teste le runtime. Elle ne porte pas le
consentement OAuth de l'utilisateur et ne l'accepte pas à sa place.

Après publication, l'utilisateur ouvre une conversation normale dans le
Playground, suit manuellement les instructions de consentement si nécessaire,
puis renvoie sa demande. Il vérifie ensuite une lecture réelle et, séparément,
une écriture avec approbation ou refus. Le consentement donne accès à la
connexion ; l'approbation autorise une action précise.

Une CD verte prouve le démarrage, le protocole Responses et l'inférence du
modèle pour l'identité du pipeline. Elle ne prouve ni le consentement personnel,
ni l'exécution des tools, ni les droits de tous les utilisateurs.

## Limites conservées

Le smoke test arrive après publication. Une erreur fait échouer la CD mais ne
provoque pas de rollback automatique. Un seul environnement est utilisé ;
aucun déploiement bleu/vert, canary ou système de notification n'est ajouté.
Les actions sont épinglées par SHA ; azd et son extension restent installés
selon les versions proposées par leurs outils d'installation.

Références : [déploiement source Foundry](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-code),
[invocation azd](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/invoke-hosted-agent),
[événement workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

## Déploiement sélectif (Hosted Agent)

Le planificateur `scripts/release_plan.py` utilise le registre `.github/components.json`. Après une CI réussie sur le SHA exact, il compare tout l'intervalle depuis le dernier checkpoint réussi de l'agent jusqu'au SHA testé. Les changements agent et les dépendances partagées provoquent le déploiement ; les fichiers BFF exclusifs, les tests et la documentation seuls ne le provoquent pas. Un chemin non attribué est considéré comme impactant tous les composants.

Le workflow ne déploie que si le SHA testé est encore la tête de `main` au moment de la planification. Un run automatique devenu obsolète ne crée pas de checkpoint. La concurrence sérialise les runs ; si un run en attente est remplacé, la comparaison cumulative conserve les changements non livrés. Un run en échec n'avance pas le checkpoint. Si aucun checkpoint valable ne subsiste ou si l'historique a divergé, le planificateur prévoit un déploiement par précaution. Un déclenchement manuel sur la tête actuelle de `main` demande toujours un déploiement, avec CI réussie.

Après succès du déploiement et du smoke test, ou après une décision explicite de ne rien déployer, un artefact `release-agent-<SHA>` garde le point de comparaison pour 90 jours. L'artefact contient le SHA, le résultat, la version si un déploiement a eu lieu, et le run ID. Un checkpoint sans déploiement ne signifie pas qu'une nouvelle version a été publiée. Voir `docs/component-cicd.md`.

Sur `main`, `publish-bff.yml` construit et publie l'image BFF dans ACR après
validation du SHA par la CI. Il ne met pas à jour Azure Container Apps.
La publication automatique nécessite `BFF_AUTO_PUBLISH=true` ; cette variable
est absente lors de la vérification GitHub du 20 octobre 2026. La publication
manuelle reste possible. Voir le [workflow de publication BFF](https://github.com/boussecsou/savant-azurian/blob/main/docs/publish-bff-workflow.md).
