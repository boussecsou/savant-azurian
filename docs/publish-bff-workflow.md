# Publication BFF dans ACR

Workflow : `.github/workflows/publish-bff.yml`. Image : `sa2-bff` dans
`acrsavantazurian2`. Le build tourne sur le runner GitHub, sans ACR Tasks.

## Déclenchement et commit autorisé

Le workflow commence en mode manuel (`workflow_dispatch`, branche `main`).
L'option booléenne `publish_v1` ajoute le tag `v1` pour la première publication.
Elle vaut `false` par défaut. Le tag principal est toujours `sha-<SHA complet>`.
Les deux tags désignent le même digest et sont verrouillés contre l'écriture
et la suppression, ainsi que le manifest sous-jacent. Le workflow ne déverrouille
jamais un tag. Un administrateur ayant les droits de modifier les attributs
ACR pourrait toutefois lever ce verrou.

Pour activer ensuite la publication automatique, définir la variable de dépôt
GitHub `BFF_AUTO_PUBLISH=true`. Elle reste désactivée tant que cette variable
n'existe pas ou possède une autre valeur. L'automatisation attend une CI
réussie, issue d'un **push sur main dans ce dépôt**. Les CI de PR, de forks,
annulées ou échouées ne permettent pas de publier. L'option `v1` reste manuelle.

Les deux modes vérifient via l'API GitHub qu'une CI de push sur `main` a réussi
pour le SHA exact. Le checkout automatique utilise `workflow_run.head_sha`,
pas la tête de `main` au démarrage du job. Aucun artefact CI ni cache de PR
n'est exécuté avec les droits Azure. Les actions sont épinglées par SHA.

## Filtrage et reprise

`scripts/release_plan.py` cherche le dernier run réussi avec un artefact `release-bff-<SHA>` (ou l'ancien nom `bff-checkpoint-<SHA>`), puis compare toute la plage jusqu'au SHA validé. `.github/components.json` définit les sources BFF, les entrées de build et les dépendances communes. Le Dockerfile ne copie dans l'image finale que les modules listés dans `source_files` ; `scripts/package_bff.py` vérifie les imports Python locaux statiques avant cette copie. Une modification de `src/savant/agent.py`, `graph.py` ou des outils propres à l'agent ne publie donc pas le BFF. Les modules OAuth partagés et les dépendances communes concernent les deux composants.

Les tests, les scripts de publication et les workflows propres au BFF déclenchent ses contrôles CI, mais leur changement seul ne crée pas une image identique. Une publication manuelle reste possible pour tester ou réparer l'opération de publication. Un SHA qui n'est plus la tête de `main` au moment du plan est ignoré, sans checkpoint ; le prochain plan compare tous les changements depuis le dernier checkpoint éligible.

Les suppressions, renommages et push à plusieurs commits sont couverts.
Un run échoué ne crée aucun checkpoint utilisable : ses changements restent
à publier lors de la prochaine CI réussie. Un run sans changements crée un
checkpoint avec `published=false`, sans authentification Azure.
Les checkpoints sont conservés 90 jours ; s'ils ont expiré, s'il n'en existe
pas ou si l'historique diverge, le workflow publie par précaution. Une erreur
API interrompt le workflow, sans supposer qu'aucun changement n'existe.

La concurrence est limitée à un run de publication, sans annuler un run actif.
GitHub peut remplacer un run encore en attente : la comparaison avec le dernier
checkpoint couvre alors aussi les modifications des runs intermédiaires.

## Construction, publication et preuve

1. Construire `Dockerfile.bff`, avec les labels OCI du dépôt et du SHA.
2. Exécuter `scripts/smoke_test_bff.py` avec clé synthétique et SQLite.
3. Obtenir un jeton Azure temporaire par OIDC, puis se connecter au registre.
4. Publier `sha-<SHA>` s'il est absent. Une relance réutilise le digest déjà
   présent et vérifie son label de révision ; elle ne remplace pas l'image
   après une éventuelle évolution des images de base.
5. Ajouter éventuellement `v1`. S'il existe pour un autre digest, échouer
   sans l'écraser. Seule une réponse explicite « repository not found »
   autorise le premier push ; une erreur réseau ou RBAC reste une erreur.
6. Vérifier le digest distant contre celui enregistré par Docker après push,
   tirer l'image par digest et vérifier la révision OCI.
7. Verrouiller les tags et le manifest, puis relire leurs attributs.
8. Enregistrer le digest dans le résumé GitHub et `bff-publication.json`
   (artefact de checkpoint). Un échec partiel laisse le run rouge ; relancer
   permet de reprendre les vérifications et verrous manquants.

Le JSON contient le SHA, le digest, l'indicateur `published` et le run ID.
Pour un run sans publication, le digest est vide ; retrouver le dernier run
avec `published=true` pour la référence d'image réellement publiée.
Une publication réussie prouve l'accès ACR et le smoke test synthétique.
Elle ne prouve pas l'accès réel à Key Vault/Blob, ni le parcours OAuth en ACA.

## Permissions et audit Azure du 15 octobre 2026

Identité réutilisée : variable existante `AZURE_CLIENT_ID`, application
`<github-oidc-client-id>`, principal
`<github-oidc-principal-id>`. Les variables `AZURE_TENANT_ID`
et `AZURE_SUBSCRIPTION_ID` restent celles de la CD existante.

La fédération existante utilise l'émetteur
`https://token.actions.githubusercontent.com`, l'audience
`api://AzureADTokenExchange` et le sujet :
`repo:<owner>/<repo>:ref:refs/heads/main`.
Le workflow utilise `main` et n'ajoute pas de GitHub Environment, qui modifierait
ce sujet. Aucun client secret, mot de passe ACR ou compte admin n'est ajouté.

Registre vérifié :

- scope : `/subscriptions/<subscription-id>/resourceGroups/rg-savant-azurian-2/providers/Microsoft.ContainerRegistry/registries/acrsavantazurian2` ;
- login server : `acrsavantazurian2-bkf5enaaagb4aygm.azurecr.io`
  (résolu dynamiquement, sans supposer `<nom>.azurecr.io`) ;
- `roleAssignmentMode=LegacyRegistryPermissions` ; admin désactivé ;
- le repository `sa2-bff` n'existait pas lors de l'audit.

L'audit des attributions directes et héritées retourne uniquement **Foundry
User** au niveau du groupe de ressources pour cette identité. Ce rôle ne donne
pas les droits ACR requis. Les droits suivants sont donc **manquants**, à faire
approuver avant toute attribution :

| Rôle | Scope minimal | Usage |
| --- | --- | --- |
| `Reader` | Registre ci-dessus uniquement | Résolution `loginServer` et lecture ARM utilisée par Azure CLI |
| `AcrPush` | Registre ci-dessus uniquement | Push/pull, lecture des digests et mise à jour des attributs de tags/manifests |

Ni Contributor, ni Owner, ni droit de création d'attribution RBAC ne sont
nécessaires au job. Le mode classique ne permet pas de restreindre `AcrPush`
au seul repository `sa2-bff`. Une future migration ABAC permettrait
`Container Registry Repository Writer` avec condition sur ce repository,
avec `Reader` pour la lecture ARM. Elle nécessite une décision séparée :
les rôles historiques `AcrPush`/`AcrPull` ne sont pas honorés en mode ABAC.
L'identité OIDC conserve ses droits Foundry existants parce qu'elle est partagée
avec la CD ; ce workflow ne les étend pas et n'appelle aucun service Foundry.

Côté GitHub, `plan` a `contents: read` et `actions: read`. Seul le job
`publish` reçoit `id-token: write`, après les contrôles CI et changements.
Le job `checkpoint` conserve uniquement `contents: read`.

Lors de la PR initiale de publication BFF, aucune attribution RBAC, activation
automatique, publication d'image ou modification de ressource Azure n'a été
effectuée. La présente évolution modifie les workflows CI et CD pour utiliser
le registre de composants décrit plus haut.

## Validation et critères d'acceptation

Contrôles locaux :

```bash
uv run --locked pytest tests/test_should_publish_bff.py tests/test_publish_bff.py
bash -n bff/publish.sh
actionlint -shellcheck= .github/workflows/publish-bff.yml
```

Les tests du shell requièrent `bash` et `jq`, déjà fournis par `ubuntu-latest`.
Ils remplacent Azure et Docker par des exécutables simulés. Ils couvrent le
premier push, `v1`, la relance sans push, le conflit de tag, l'échec d'auth,
les digests/révisions incorrects et l'échec du verrouillage. Les tests de filtrage
couvrent la pagination, les artefacts expirés et les plages multi-commits.

Après revue et fusion, puis accord RBAC :

- [ ] Confirmer `Reader` et `AcrPush` sur le registre pour l'identité OIDC.
- [ ] Attendre la CI de push réussie sur le SHA de `main`.
- [ ] Lancer manuellement `Publish BFF` sur `main` avec `publish_v1=true`.
- [ ] Vérifier le smoke test, les tags SHA et `v1`, leur digest identique,
      leurs attributs `writeEnabled=false`/`deleteEnabled=false` et le JSON.
- [ ] Relancer sur le même SHA : aucun écrasement ni nouveau push requis.
- [ ] Activer ensuite `BFF_AUTO_PUBLISH=true` par décision explicite.
- [ ] Vérifier qu'une modification BFF suivie d'une CI verte publie son SHA,
      et qu'une modification documentaire seule saute le job Azure.
- [ ] Vérifier qu'une CI rouge, une CI de PR et un dispatch hors `main`
      ne publient rien.
- [ ] Vérifier qu'une tentative de déplacer `v1` vers un autre SHA échoue.

Le workflow s'arrête à la publication ACR : le déploiement ACA reste une étape
manuelle distincte. Aucun déploiement Foundry n'est ajouté ou modifié.

## Références

- [Task 26.1](https://app.notion.com/p/3f1eba09656f81d58cdceea603a4841f).
- [SDD-004 — Continuous Integration Workflow](https://app.notion.com/p/3e5eba09656f81b9b2cec0863551d273).
- [ADR-009 — Container Apps BFF](https://app.notion.com/p/3f1eba09656f8131ad63eea86d33b7ce).
- [Événement workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).
- [Rôles ACR et modes RBAC/ABAC](https://learn.microsoft.com/azure/container-registry/container-registry-rbac-built-in-roles-directory-reference).
- [Verrouillage des images ACR](https://learn.microsoft.com/azure/container-registry/container-registry-image-lock).
