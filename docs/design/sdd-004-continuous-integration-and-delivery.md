# SDD-004: Continuous integration and delivery

- **Status:** Accepted and in service
- **Version:** 2.0 (first written 2026-09-24)
- **Owner:** Ali Boussecsou
- **Related:** [SDD-002](sdd-002-architecture-and-azure-infrastructure.md), [ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md), [CI details](../ci-workflow.md), [CD details](../cd-workflow.md), [component delivery](../component-cicd.md)

## 1. Purpose

Answer two questions on every commit, in this order:

1. **CI:** can the commit rebuild the project's environment and pass its tests?
2. **CD:** which deliverable did the commit change, and does it need delivering?

CI never connects to Azure. CD is a separate workflow that signs in to Azure with OpenID Connect and runs only after a green CI on `main`. This separation keeps a simple code check from holding Azure permissions.

## 2. The first CI (2026-09-24)

```text
push to main, or pull request to main
  → start the CI workflow, cancel the previous run for the same branch
  → check out, install Python 3.13, install uv with its cache
  → sync dependencies from the lockfile (--locked)
  → run pytest (--locked)
  → pass: the commit is eligible for the next stage   fail: fix required
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

**What it does not prove.** That Azure resources exist or that the remote agent responds. That is the job of the delivery smoke test, and a green CI proves neither OAuth nor tools under real conditions.

**Pinned actions.** Third-party actions are pinned to an immutable commit SHA with the version as a comment, not to a floating tag.

**Deliberately deferred.** A linter, formatter, type checker or coverage report is added only once the project chooses and configures the tool, because adding a tool without explicit rules creates noise without strengthening validation. A multi-version Python matrix is unnecessary: the project targets Python 3.13 locally and in Foundry.

## 3. Component-aware delivery (2026-10-27)

The repository holds more than one deliverable. A **registry**, `.github/components.json`, is the single source of ownership: for each component it lists the runtime paths, the excluded paths, the source files and the CI checks. `scripts/component_changes.py` classifies a diff against it, and `scripts/release_plan.py` plans each delivery.

| Changed input | Agent delivery | BFF image publication |
| --- | --- | --- |
| Agent-only code | Yes | No |
| BFF-only code | No | Yes, when automatic publication is on |
| Shared OAuth modules or Python dependencies | Yes | Yes, when automatic publication is on |
| Documentation or tests only | No | No |
| A path no component owns | Yes | Yes, when automatic publication is on |

An unknown path delivers both components on purpose: it is the conservative failure mode.

**Release planning.** Each release workflow checks that a push CI succeeded for the exact SHA on `main`, verifies the SHA is still the head, then compares the whole range since the component's last successful **checkpoint** (a workflow artifact kept for 90 days). Failed deliveries do not advance a checkpoint. A missing checkpoint or a divergent history forces a conservative release. API or configuration errors fail before any Azure sign-in. A manual dispatch is an explicit release of the chosen component on the current `main`.

**The BFF image.** It contains only the Python modules the registry lists. Static local imports are checked while packaging, so a module the BFF imports but the registry omits fails the build. Dynamically loaded dependencies must be declared and covered by a smoke test. A synthetic readiness smoke test runs the packaged image. Publishing is an immutable registry push with digest verification; **updating the Container App is a separate, manual operation.**

**The agent.** Delivery is a Foundry code deployment with `azd deploy`, followed by a smoke test that invokes the deployed version.

**Adding a service** needs a registry entry, its CI and release jobs, a checkpoint, and tests for isolated, shared and failed changes. The registry does not create workflows or Azure resources.

## 4. Operating notes

- **The BFF module list** grew as routes were added (owner routes, projects and sessions, documents). A change limited to a BFF-only file publishes an image and does not redeploy the agent.
- **A pipeline trap.** An `azd` extension check written as `azd ext list | grep -q "microsoft.foundry"` failed with exit status 141 under `set -o pipefail`: `grep -q` exits at the first match, the writer receives SIGPIPE, and pipefail reports it. The fix redirects to `/dev/null` instead. **Rule: never end a pipeline with `grep -q`, `head` or any early-exit reader under `pipefail`.**
- **Trigger rule to remember.** Editing `.github/components.json`, `.agentignore`, `azure.yaml` or `pyproject.toml`, or the agent's runtime code, is a runtime change: merging it to `main` deploys the agent.
- **The web client** is a **CI-only** component. `pwa/**` is declared non-runtime, a `pwa` check runs Node 22 (install, production audit, tests, build) with pinned actions and never receives an Azure token. A web-client-only change delivers nothing ([ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md)).
- **Not covered by CI or CD:** the owner's Entra authentication, role assignments and Container App configuration, which are manual or scripted steps ([deployment guide](../deployment.md)).
- **Rollout caveat.** The first run after introducing component checkpoints may deploy the agent and publish the BFF, because no checkpoint exists yet. Merging and Azure rollout need explicit owner authorization.

## 5. Non-goals

Azure sign-in from CI, deploying from CI, a remote smoke test from CI, linting, type checking and coverage (for now), and a Python version matrix.

## Revision history

| Date | Change |
| --- | --- |
| 2026-09-24 | First version: a single-job CI |
| 2026-10-27 | Component-aware CI/CD proposed |
| 2026-10-30 | In service; operating notes, the `pipefail` fix, the BFF module list |
| 2026-10-31 | The web client as a CI-only component |
| 2026-11-09 | Rewritten as a single document |
