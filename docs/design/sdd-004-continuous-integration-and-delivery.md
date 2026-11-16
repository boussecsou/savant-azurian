# SDD-004: Continuous integration (and why there is no CD)

- **Status:** Accepted and in service. The continuous-delivery part was removed on 2026-11-16; see [section 3](#3-component-aware-ci)
- **Version:** 2.0 (first written 2026-09-24)
- **Owner:** Ali Boussecsou
- **Related:** [SDD-002](sdd-002-architecture-and-azure-infrastructure.md), [ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md), [CI details](../ci-workflow.md), [component CI](../component-cicd.md)

## 1. Purpose

Answer one question on every commit: can it rebuild the project's environment and pass its tests, and which components does it touch?

CI never connects to Azure. Nothing is deployed from GitHub: an earlier design had a CD workflow and a backend publication workflow that signed in to Azure with OpenID Connect after a green CI on `main`. They were removed on 2026-11-16, because this repository is a public prototype whose Azure resources belong to one owner, and a deployment is a deliberate, manual step (`azd deploy`).

## 2. The first CI (2026-09-24)

```text
push to main, or pull request to main
  → start the CI workflow, cancel the previous run for the same branch
  → check out, install Python 3.13, install uv with its cache
  → sync dependencies from the lockfile (--locked)
  → run pytest (--locked)
  → pass: the change is sound   fail: fix required
```

**Triggers.** A pull request targeting `main` validates a change before integration; a push to `main` confirms the real state of the reference branch. A concurrency group per workflow and branch cancels an outdated run when a new commit lands.

**Commands the CI reproduces**

```bash
uv sync --locked --group dev
uv run --locked pytest
```

`--locked` fails when `uv.lock` and `pyproject.toml` diverge, so a dependency change must update the lockfile in the same change. An earlier proposal used `--frozen`, which does not check consistency; it was corrected on 2026-09-24.

**Permissions.** The job has `contents: read` only. No Azure secret, no model key, no permanent token. Tests use a fake model and make no network call.

**What it proves.** The project installs with Python 3.13 and the lockfile; the non-secret configuration validates; the model client builds with `DefaultAzureCredential`; the graph forwards the message to the model; the hosting server wraps the graph; the root entry point imports.

**What it does not prove.** That Azure resources exist or that the remote agent responds. The smoke test (`scripts/smoke_test.py`) checks a deployed agent when you run it by hand, and a green CI proves neither OAuth nor tools under real conditions.

**Pinned actions.** Third-party actions are pinned to an immutable commit SHA with the version as a comment, not to a floating tag.

**Deliberately deferred.** A linter, formatter, type checker or coverage report is added only once the project chooses and configures the tool, because adding a tool without explicit rules creates noise without strengthening validation. A multi-version Python matrix is unnecessary: the project targets Python 3.13 locally and in Foundry.

## 3. Component-aware CI

The repository holds more than one component. A **registry**, `.github/components.json`, is the single source of ownership: for each component it lists the runtime paths, the excluded paths, the source files and the CI checks. `scripts/component_changes.py` classifies a diff against it and tells CI which jobs to run.

| Changed input | Python CI | BFF build and smoke test |
| --- | --- | --- |
| Agent-only code | Yes | No |
| BFF-only code | Yes | Yes |
| Shared OAuth modules or Python dependencies | Yes | Yes |
| Documentation or tests only | Yes | No |
| A path no component owns | Yes | Yes |

An unknown path concerns both components on purpose: it is the conservative failure mode.

**The BFF image.** It contains only the Python modules the registry lists. Static local imports are checked while packaging, so a module the BFF imports but the registry omits fails the build. Dynamically loaded dependencies must be declared and covered by a smoke test. A synthetic readiness smoke test runs the packaged image in CI. Building and publishing the image, and updating the Container App, are manual operations.

**The agent.** It is deployed by hand with `azd deploy`, then checked with a smoke test that invokes the deployed version.

## 4. Operating notes

- **The BFF module list** grew as routes were added (owner routes, projects and sessions, documents). A change limited to a BFF-only file builds the image in CI and does not concern the agent.
- **A shell trap, kept from the removed pipeline.** An `azd` extension check written as `azd ext list | grep -q "microsoft.foundry"` failed with exit status 141 under `set -o pipefail`: `grep -q` exits at the first match, the writer receives SIGPIPE, and pipefail reports it. The fix redirects to `/dev/null` instead. **Rule: never end a pipeline with `grep -q`, `head` or any early-exit reader under `pipefail`.**
- **The web client** is a **CI-only** component. `pwa/**` is declared non-runtime, a `pwa` check runs Node 22 (install, production audit, tests, build) with pinned actions and never receives an Azure token. Nothing in the web client is deployed ([ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md)).
- **Not covered by CI:** the owner's Entra authentication, role assignments and Container App configuration, which are manual or scripted steps ([deployment guide](../deployment.md)).

## 5. Non-goals

Azure sign-in from CI, deploying from CI or from GitHub at all, a remote smoke test from CI, linting, type checking and coverage (for now), and a Python version matrix.

## Revision history

| Date | Change |
| --- | --- |
| 2026-09-24 | First version: a single-job CI |
| 2026-10-27 | Component-aware CI/CD proposed |
| 2026-10-30 | In service; operating notes, the `pipefail` fix, the BFF module list |
| 2026-10-31 | The web client as a CI-only component |
| 2026-11-09 | Rewritten as a single document |
| 2026-11-16 | Continuous delivery removed: no deployment or image publication workflow remains |
