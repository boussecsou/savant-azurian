# Corrections BFF : intégration et déploiement

État vérifié le 20 octobre 2026. Cette PR fournit le durcissement du BFF,
ses tests et sa documentation. La publication ACR et le déploiement ACA restent
manuels ; ouvrir ou fusionner cette PR ne met pas à jour le BFF déployé.

## Changements préparés

- `oauth_callback.py` et `bff_logging.py` : logs à événements fixes,
  sans query strings, valeurs OAuth, en-têtes ou traces d'exception brutes.
- `scripts/should_deploy_agent.py` : exclusion explicite de `bff_logging.py`
  et du script de filtrage lui-même pour la CD Foundry.
- Tests de filtrage, tests OAuth/logs et documentation de validation.

Le code partagé (`notion_oauth.py`, `oauth_runtime.py`, `oauth_key.py`), le
runtime agent et les dépendances continuent de déclencher Foundry s'ils changent.
Un fichier inconnu ou une comparaison impossible déclenche aussi Foundry par
précaution. Une CD Foundry lancée manuellement force toujours ce déploiement.

## Ce qui se passera après intégration sur main

| Étape | Effet pour ces corrections seules |
| --- | --- |
| PR vers `main` | Tests Python, construction Docker et readiness synthétique ; aucun déploiement Azure |
| Fusion squash vers `main` | Nouvelle CI sur le SHA intégré |
| CD Foundry automatique après CI verte | Déploiement ignoré par le filtre |
| Publish BFF automatique | Ignoré tant que `BFF_AUTO_PUBLISH` reste absent ou différent de `true` |
| Publish BFF manuel | Publication du SHA validé dans ACR si les entrées BFF ont changé |
| Azure Container Apps | Reste sur `v1` jusqu'à une mise à jour explicite de l'image |

L'absence de déploiement Foundry suppose que la PR contient uniquement les
corrections BFF, les exclusions, leurs tests et la documentation. Un changement
partagé ajouté à la même PR peut légitimement déclencher Foundry.
Le filtre actuel compare `HEAD^..HEAD` : privilégier une fusion **squash**.
Il ne garantit pas l'analyse de tous les commits d'un push multiple.

## Procédure pour déployer le BFF corrigé

1. Sur la branche dédiée de cette PR issue de `main`, attendre la CI puis
   fusionner par squash après revue.
   Ne pas inclure les documents personnels déjà préparés dans l'espace local.
2. Attendre la CI **push sur main** du commit fusionné. Le workflow de
   publication exige une CI verte sur ce SHA exact.
3. Dans GitHub Actions, sélectionner **Publish BFF → Run workflow → main**,
   avec `publish_v1=false` (défaut). Ne pas relancer **CD** pour publier le BFF.
   Équivalent CLI :

   ```bash
   gh workflow run publish-bff.yml --repo boussecsou/savant-azurian --ref main
   ```

4. Attendre la réussite des jobs `plan`, `publish`, `checkpoint`. Le résumé
   du run et l'artefact `bff-publication.json` donnent le SHA et le digest.
   Le tag produit est `sa2-bff:sha-<SHA complet>`, immuable. `v1` ne doit
   pas être réécrit. Si aucun input BFF n'a changé depuis le checkpoint,
   `publish` peut être ignoré : vérifier alors l'image correspondant au code voulu.
5. Après demande explicite de déploiement, remplacer l'image utilisée par ACA
   avec le digest vérifié du run. Cette commande crée une nouvelle révision ;
   la configuration actuelle envoie le trafic vers la dernière révision.
   Remplacer la valeur fictive avant exécution :

   ```bash
   BFF_DIGEST='sha256:REMPLACER_PAR_LE_DIGEST_VERIFIE'
   az containerapp update -g rg-savant-azurian-2 -n ca-sa2-bff \
     --image "acrsavantazurian2-bkf5enaaagb4aygm.azurecr.io/sa2-bff@$BFF_DIGEST"
   ```

6. Vérifier la révision et le contrôle de santé :

   ```bash
   az containerapp show -g rg-savant-azurian-2 -n ca-sa2-bff \
     --query '{state:properties.provisioningState,latest:properties.latestRevisionName,ready:properties.latestReadyRevisionName,image:properties.template.containers[0].image}'
   curl --fail --show-error \
     https://<bff-fqdn>/readiness
   ```

   Attendu : provisioning réussi, dernière révision prête, image au bon digest,
   HTTP 200 et `{"status":"ready"}`. Refaire le test de logs avec des valeurs
   fictives ; ne pas tester en imprimant de vrais tokens ou la clé Fernet.

Le workflow de publication utilise OIDC et les autorisations ACR existantes.
La mise à jour ACA utilise la session Azure autorisée ; elle n'ajoute aucun rôle
à l'identité GitHub. Aucun provisioning Foundry n'est nécessaire.
Les identités, secrets Key Vault, variables, ingress et scaling ACA sont conservés
par cette mise à jour de l'image. Consulter [l'audit des logs](bff-logging-audit.md)
pour les preuves, les limites et les validations locales.

## Validation des exclusions

Commande exécutée :

```bash
/tmp/sa2-bff-audit-venv/bin/python -m pytest -q \
  tests/test_deploy_changes.py tests/test_bff_logging.py \
  tests/test_oauth_runtime.py tests/test_notion_oauth.py
```

**50 tests passent.** Les tests couvrent l'ensemble des fichiers de correction,
les mélanges BFF/code partagé et le comportement prudent sur les chemins inconnus.
Le filtrage appliqué à tous les fichiers actuellement modifiés ou nouveaux retourne
`false` pour le déploiement Foundry automatique. `git diff --check` passe.
Le filtre de publication BFF présent sur GitHub reconnaît tout `src/savant/` :
les deux fichiers Python du BFF seront donc bien considérés comme des entrées modifiées.

La suite complète a également été exécutée sur la branche de cette PR issue
de `main` : **142 tests passent**, avec les dépendances verrouillées et `jq`
disponible. Le build Docker et son smoke test seront exécutés par la CI GitHub.
