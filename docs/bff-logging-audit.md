# Audit des logs BFF — 20 octobre 2026

Périmètre : `ca-sa2-bff`, `cae-savant-azurian-2`, code Python/Docker,
logs récents ACA, deux workspaces Log Analytics accessibles et quatre fichiers
locaux de diagnostic. Aucun secret réel n'a été récupéré pour les comparer.
Aucune donnée historique n'a été supprimée et aucune attribution RBAC ajoutée.

## Résultats Azure

- Révision active : `ca-sa2-bff--0000001`, image `sa2-bff:v1`, entrée Docker
  `python -m savant.oauth_callback`, sans surcharge de commande.
- Inspection dans le conteneur : `UVICORN_ACCESS_LOG_DISABLED=True`.
- Aucun diagnostic setting sur l'app ou l'environnement ; destination de logs
  de l'environnement et configuration Log Analytics nulles.
- Dapr désactivé, aucun export OpenTelemetry configuré dans l'environnement,
  aucune variable App Insights/OTEL dans le conteneur. Le point d'entrée BFF
  n'initialise aucun SDK de télémétrie. Les dépendances OTEL installées dans
  l'image ne constituent pas, seules, une activation de l'instrumentation.
- HTTPS imposé ; les variables secrètes n'ont été inspectées que par leur nom.
- Les métriques plateforme restent disponibles : `Requests`, unité `Count`,
  une série retournée sur les dernières 24 h. Aucun réglage de métrique changé.

Les logs HTTP d'ingress peuvent contenir le chemin **avec la query string** :
ne pas activer `ContainerAppHTTPLogs` pour cet environnement OAuth sans dispositif
validé de suppression avant stockage. La configuration actuelle ne les exporte pas.
Référence : [schéma des logs ACA](https://learn.microsoft.com/en-us/azure/container-apps/log-monitoring).

## Risques et corrections du code

L'accès HTTP était déjà désactivé. Les réponses HTML et erreurs OAuth étaient
également génériques. En revanche, le processus n'imposait aucune protection globale
contre les messages de dépendances, avertissements Python ou exceptions Uvicorn.
Les erreurs inattendues du callback étaient absorbées sans événement exploitable.

`src/savant/bff_logging.py` impose désormais une sortie à événements fixes :
aucun formatage des arguments, messages tiers, extras, chemins, exceptions ou
stack traces. Le logger d'accès est filtré même s'il est activé accidentellement.
Les avertissements Python passent par cette configuration. Les logs tiers
existants sont désactivés et les nouveaux logs propagés passent par le filtre.
Les avertissements/erreurs propagés restent représentés par des événements génériques.

`oauth_callback.py` configure cette protection avant de construire le service,
transmet la même configuration à Uvicorn et produit des événements fixes de
succès, refus, panne et échec de démarrage. Les métriques Azure ne dépendent pas
de cette configuration Python. Ce durcissement concerne uniquement le BFF.

## Recherche historique

- Logs récents : 6 lignes console et 24 lignes système retournées, aucun motif
  de code/query OAuth, cookie, Authorization, token, secret nommé ou JWT détecté.
  La requête demande les 300 dernières lignes ; ce n'est pas un export exhaustif.
- Les deux workspaces (rétention configurée : 30 jours) ne retournent aucune
  ligne faisant référence à l'app ou à son environnement sur les 30 derniers jours.
  La recherche utilise les noms BFF/CAE et agrège les résultats côté service.
- Quatre fichiers locaux : 1 985 lignes. Les 30 occurrences du mot Authorization
  sont 20 en-têtes déjà masqués, 6 références RBAC et 4 noms de SDK dans User-Agent.
  Aucun candidat de secret non masqué confirmé dans cette recherche.
- Les résultats conservés dans `/tmp/sa2-bff-log-audit/` sont des configurations
  filtrées et des compteurs ; les messages historiques bruts n'y sont pas copiés.

## Validation

Commande :

```bash
/tmp/sa2-bff-audit-venv/bin/python -m pytest -q \
  tests/test_bff_logging.py tests/test_oauth_runtime.py tests/test_notion_oauth.py
```

**44 tests passent.** Tests Uvicorn réels sur localhost avec uniquement des
valeurs fictives : succès, refus OAuth, panne du callback, exception non interceptée,
logs de dépendances, avertissement Python et échec de démarrage. Les faux codes,
states, tokens, cookies, Authorization et contenus d'exception sont absents de
la sortie ; les événements de succès/erreur restent présents. `git diff --check` passe.

Test public sur `/readiness` avec query string, Authorization et cookie fictifs :
HTTP **200**, `{"status":"ready"}`, aucun marqueur synthétique dans les logs console
retournés. Ce contrôle ne constitue pas un test OAuth réel ni une preuve sur tous
les journaux internes Microsoft.

## État d'application et limites

**Le durcissement Python est corrigé et testé localement, mais pas encore déployé.**
L'inspection du conteneur confirme `HARDENED_LOGGING_MODULE_PRESENT=False`.
Aucune configuration Azure dangereuse active n'a été trouvée à modifier.
Le déploiement d'une nouvelle image nécessite une demande explicite selon le
cadre d'apprentissage d'`AGENTS.md`.

Après fusion et CI verte sur `main`, utiliser **Publish BFF** manuellement
pour construire et publier l'image corrigée dans ACR. Mettre ensuite à jour
`ca-sa2-bff` explicitement avec le digest vérifié ; vérifier la nouvelle révision,
`/readiness` et les logs synthétiques. Voir [la procédure complète](bff-release-procedure.md).
Aucun workflow actuel ne met à jour ACA automatiquement.

La recherche historique dépend des données accessibles et retenues ; elle ne prouve
pas l'absence absolue de fuite passée. Les futures impressions directes sur stdout,
handlers personnalisés ou instrumentations/exporteurs indépendants devront être
revus séparément. Les événements d'erreur génériques limitent volontairement le
diagnostic détaillé. Aucun nouveau stockage durable de logs n'a été activé.
