# Application Insights : correction du 2 octobre 2026

## Diagnostic

Le Hosted Agent v10 répondait correctement (`/readiness` et `/responses` en
HTTP 200), mais les exports OpenTelemetry et QuickPulse étaient refusés avec
`Forbidden`. Le rôle `Monitoring Metrics Publisher` était présent pour
l'identité du projet, absent pour l'identité du Hosted Agent. La propriété
`DisableLocalAuth` n'était pas configurée sur Application Insights.

## Correction Azure réalisée sur demande

- Attribution de `Monitoring Metrics Publisher` à l'identité du Hosted Agent,
  uniquement sur `fp-savant-azurian-2-resource-appinsights`.
- Configuration de cette ressource avec `DisableLocalAuth=true`, conformément
  au parcours Entra recommandé pour les traces Foundry.
- Aucun changement de code, de modèle ni redéploiement nécessaire.

## Vérification réelle

Deux invocations explicites de la v10 ont répondu `OK`. Après la correction
complète, Log Analytics contient, pour l'identifiant d'opération exact du
second test, 1 `AppRequests`, 4 `AppDependencies` et 15 `AppTraces`.
Les logs récents de cette session ne contiennent plus `Forbidden` ni
`Exception occurred while publishing live metrics`. Cela valide l'ingestion
et l'absence des erreurs observées sur cette session ; le panneau graphique
Live Metrics n'a pas été inspecté directement.

## Accès et piège de version

La session Azure habituelle est authentifiée et utilisable hors sandbox.
Le répertoire `/tmp/sa2-azure-config` n'est pas authentifié. Dans la sandbox,
le répertoire Azure habituel est en lecture seule, et azd ne peut pas ouvrir
son serveur interne : utiliser l'exécution approuvée hors sandbox sans copier
les credentials.

L'environnement azd local référence encore la v3. Les tests de la v10 ont
utilisé `--version 10 --protocol responses` et les lectures de logs ont ciblé
explicitement l'identifiant de session renvoyé par cette invocation.
Ne pas interpréter `azd ai agent show` sans vérifier ce contexte.

## Référence

[Authentification Entra pour les traces Foundry](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-ingestion-entra-authentication)
