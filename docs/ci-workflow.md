# Continuous integration

Implemented in `.github/workflows/ci.yml`. The design is in [SDD-004](design/sdd-004-continuous-integration-and-delivery.md).

CI runs on pull requests to `main` and on pushes to `main`. It uses Python 3.13, like the Foundry runtime, and actions pinned by SHA. A new run cancels the previous run of the same branch.

## Checks

1. `uv sync --locked --group dev` rebuilds the environment from `uv.lock`.
2. `uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt` regenerates the deployment dependencies.
3. `git diff --exit-code -- requirements.txt` checks that the versioned export matches the lockfile.
4. `uv run --locked pytest` tests the simulated model, the graph, the confirmations, the Notion and Toolbox backends and the check of the smoke test result.
5. `ruff check` and `ruff format --check` (the `lint` job).
6. `python3 -m scripts.check_docs` (the `docs` job) checks relative links and anchors, the format and index of the ADRs, that every document is reachable from an index, and that headings and file names are in English.
7. A secrets scan of the full history with gitleaks (the `secrets` job).

The GitHub permission is limited to `contents: read`. No Azure access and no personal consent are needed. Remote calls are simulated. CI does not validate OAuth consent or real access to Notion pages.

The `changes` job uses `.github/components.json` to classify the changed files by component. The `test` job is a shared check that always runs. The `bff` job is skipped when the sources and checks that concern it are unchanged. If the Git comparison is impossible, it runs as a precaution. When it is needed, the `bff` job builds `Dockerfile.bff`, then runs `scripts/smoke_test_bff.py` with a synthetic key and SQLite. It checks `/readiness` through the published port and the absence of the Key Vault SDK in the image. It uses no Azure identity and no secret of the repository, and does not publish the image. A skipped `bff` job is expected when the backend is not concerned; the jobs that run must pass for the CI workflow to be green.

## Changing a dependency

Update `pyproject.toml` and `uv.lock`, then run the export command above and commit `requirements.txt` too. It holds the exact versions of the production dependencies; the Savant package is loaded from `src/` thanks to the manifest's `PYTHONPATH`. The `dev` dependencies are not exported.

A green CI on a **push of that SHA to `main`** authorizes CD. A green run on a pull request alone is not enough. The rule also applies to manual CD dispatch; see [the CD workflow](cd-workflow.md).
