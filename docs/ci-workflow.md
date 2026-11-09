# CI — Savant Azurian 2

Mis à jour le 2 octobre 2026. Workflow implémenté : `.github/workflows/ci.yml`.

La CI s'exécute sur les PR vers `main` et les push sur `main`. Elle utilise
Python 3.13, comme le runtime Foundry, et des actions épinglées par SHA.
Un nouveau run annule le run précédent de la même branche.

## Contrôles

1. `uv sync --locked --group dev` reconstruit l'environnement depuis `uv.lock`.
2. `uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt` régénère les dépendances de déploiement.
3. `git diff --exit-code -- requirements.txt` vérifie que l'export versionné
   correspond au lockfile.
4. `uv run --locked pytest` teste le modèle simulé, le graphe, les confirmations,
   les backends Notion/Toolbox et le contrôle du résultat du smoke test.

La permission GitHub est limitée à `contents: read`. Aucun accès Azure ni
consentement personnel n'est nécessaire. Les appels distants sont simulés.
La CI ne valide pas le consentement OAuth ni l'accès réel aux pages Notion.

Le job `changes` utilise `.github/components.json` pour classifier les fichiers modifiés par composant. Le job `test` reste un contrôle commun toujours exécuté. Le job `bff` est ignoré si les sources et contrôles qui le concernent sont inchangés. Si la comparaison Git est impossible, il est exécuté par précaution. Quand il est nécessaire, le job `bff` construit `Dockerfile.bff`, puis lance
`scripts/smoke_test_bff.py` avec une clé synthétique et SQLite. Il vérifie
`/readiness` via le port publié et l'absence du SDK Key Vault dans l'image.
Il n'utilise aucune identité Azure ni aucun secret du dépôt et ne publie pas
l'image. Un job `bff` ignoré est attendu lorsque le BFF n'est pas concerné ;
les jobs exécutés doivent réussir pour que le workflow CI soit vert.

## Modifier une dépendance

Mettre à jour `pyproject.toml` et `uv.lock`, puis exécuter la commande d'export
ci-dessus et commiter aussi `requirements.txt`. Celui-ci contient les versions
exactes des dépendances de production ; le package Savant est chargé depuis
`src/` grâce au `PYTHONPATH` du manifeste. Les dépendances `dev` ne sont pas
exportées.

Une CI réussie sur un **push de ce SHA sur main** autorise la CD. Une réussite
sur PR seule ne suffit pas. Cette règle s'applique aussi au déclenchement manuel
CD ; voir `docs/cd-workflow.md`.
