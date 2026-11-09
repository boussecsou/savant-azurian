# CI/CD par composant

## Périmètre

Cette évolution propose de distinguer le Hosted Agent et le BFF dans un même
dépôt. Le registre `.github/components.json` contient les chemins de runtime,
les contrôles CI et les fichiers BFF emballés. `scripts/component_changes.py`
applique ces règles ; `scripts/release_plan.py` planifie chaque livraison avec
un checkpoint propre au composant. Ajouter un service implique de déclarer ses
chemins et son workflow, puis de créer ses jobs CI/CD et son checkpoint : le
registre ne crée pas automatiquement les workflows ou les ressources Azure.

| Changement | CI Python | Build/smoke BFF en CI | CD agent | Publication BFF |
| --- | --- | --- | --- | --- |
| Agent seul, par exemple `src/savant/graph.py` | Oui | Non | Oui | Non |
| BFF seul, par exemple `oauth_callback.py` | Oui | Oui | Non | Oui |
| Code OAuth partagé ou `uv.lock` | Oui | Oui | Oui | Oui |
| Documentation seule | Oui | Non | Non | Non |
| Contrôles ou workflow BFF seuls | Oui | Oui | Non | Non |
| Chemin non attribué | Oui | Oui | Oui | Oui |

Le tableau décrit les décisions automatiques lorsque le checkpoint est
disponible, l'historique comparable et la CI verte. L'étiquette « Oui » dans la
colonne publication est conditionnée à `BFF_AUTO_PUBLISH=true`. La publication
BFF crée une image ACR immuable ; elle ne met pas à jour la révision ACA.
`workflow_dispatch` sur la tête de `main` demande explicitement la livraison du
composant sélectionné, après vérification de la CI du SHA exact.

## Détection et livraison

1. La CI tourne sur les PR et les push vers `main`. Elle utilise une comparaison
   Git complète et lance toujours la suite Python. Le build/smoke Docker BFF ne
   tourne que pour les chemins BFF pertinents ; en cas de comparaison impossible,
   il tourne par précaution. Une CI de PR n'autorise aucune livraison Azure.
2. Chaque workflow de livraison part du SHA de la CI de push réussie et vérifie
   le dépôt, la branche, l'événement et ce SHA via l'API GitHub. Il vérifie aussi
   que le SHA est encore la tête de `main` à la planification. Un run obsolète ne
   déploie pas et ne crée pas de checkpoint. La tête peut encore évoluer pendant
   un déploiement déjà commencé ; un run ultérieur rattrape alors les changements.
3. Le planificateur compare la plage complète depuis le dernier checkpoint réussi
   du composant. Les suppressions et les renommages sont traités comme chemins
   supprimés et ajoutés. Un échec ne fait pas avancer le checkpoint ; un run
   écarté par la concurrence ne masque pas ses changements.
4. Absence ou expiration du checkpoint, historique divergent ou chemin inconnu :
   livraison prudente. Une erreur d'API ou une configuration invalide fait
   échouer le plan avant toute authentification Azure. La première exécution de
   cette version peut livrer les deux composants, car le registre et le
   Dockerfile changent et l'agent n'a pas de checkpoint historique.
5. Après succès du déploiement agent et de son smoke test, ou de la publication
   BFF et de sa vérification du digest, un artefact de checkpoint est enregistré.
   Une décision « inchangé » enregistrée après une CI verte fait aussi avancer le
   point de comparaison. Les artefacts expirent après 90 jours. Pour retrouver
   la dernière version ou image réellement livrée, consulter le dernier artefact
   dont `released` ou `published` est vrai.

Les workflows qui ne livrent pas n'obtiennent pas de jeton OIDC Azure. La
publication BFF conserve les tags `sha-<commit>`, la vérification du digest et les
verrous ACR déjà en place. Les deux workflows restent sérialisés séparément.

## Frontière du BFF

Le build utilise les six modules Python explicitement listés dans
`components.bff.source_files`. `scripts/package_bff.py` analyse leurs imports
Python locaux statiques et refuse le build si un fichier existant importé n'est
pas déclaré. Le Dockerfile copie uniquement ce résultat dans l'image finale.
Une dépendance chargée dynamiquement doit être ajoutée explicitement au registre
et couverte par le smoke test ; l'analyse statique ne peut pas la déduire.
Les dépendances Python sont encore communes : tout changement de `uv.lock` ou de
`pyproject.toml` concerne donc les deux composants.

Pour ajouter un nouveau composant, définir ses fichiers de runtime et ses
contrôles CI, identifier explicitement les dépendances communes, choisir ses
permissions, son mécanisme de livraison, son checkpoint et son smoke test, puis
ajouter des scénarios de modification isolée, partagée, mixte, supprimée et de
reprise après échec. Les chemins non attribués restent conservateurs jusqu'à ce
que leur propriétaire soit défini.

## Validation et limites

Les tests locaux simulent les comparaisons Git, la pagination des checkpoints,
le contrôle de la CI et les commandes de publication. La construction et le
smoke Docker doivent également réussir dans la CI GitHub. La réussite d'une CI
ne prouve pas qu'une image a été publiée ou qu'un agent a été déployé. La fusion
de cette proposition active les workflows existants : examiner les plans et les
premières publications avant de considérer le comportement distant vérifié.
