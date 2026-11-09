# Technical Report — Repository Preparation

- **Date:** 2026-11-09
- **Status:** audit and bootstrap complete; no infrastructure, code migration, commit, or deployment performed
- **Source repository:** the existing private `sa2-agent` repository
- **Target repository:** [`boussecsou/savant-azurian`](https://github.com/boussecsou/savant-azurian) (public)
- **Audience:** maintainer and portfolio reviewers

## 1. Executive summary

This report covers the preparation work for turning Savant Azurian 2 into a reproducible,
English-only, portfolio-ready repository.

Completed in this session:

1. Audited the existing repository: configuration drift, hard-coded personal values,
   missing infrastructure and tooling, mixed documentation languages, and delivery risks.
2. Installed the official Microsoft Foundry agent skill globally for OpenCode.
3. Updated the Azure Developer CLI (`azd`) from 1.34.1 to 1.37.3.
4. Created a separate public repository and cloned it locally.

Not done in this session:

- No Azure resource was created, modified, or deleted.
- No deployment or GitHub Actions run was triggered.
- No source code or configuration was copied into the new repository.
- No commit was pushed.

The recommended next step is Phase 1: a single source of configuration, a documentation
page for every environment variable, a drift test, and a parameterized `azure.yaml`.

## 2. Context and objectives

Savant Azurian 2 is a single-owner AI assistant built with Python 3.13 and LangGraph,
hosted as a Microsoft Foundry Hosted Agent. The repository also contains:

- a FastAPI backend-for-frontend (BFF) for Notion OAuth and the owner-only PWA API;
- a React + Vite Progressive Web App (PWA) that runs locally;
- CI/CD workflows for the agent and the BFF image;
- tests that use test doubles and never touch Azure.

The preparation work has four objectives:

| Objective | Why it matters |
| --- | --- |
| One source of configuration | A new contributor can reproduce the setup without editing personal values. |
| Reproducible infrastructure | Azure resources are described in code instead of created manually. |
| English-only repository artifacts | The repository is consistent for a public portfolio and external readers. |
| Safe delivery | No accidental deployment while the repository is being restructured. |

Explicit non-goals:

- changing the runtime behavior of the agent;
- weakening either consent layer (Notion OAuth and conversational approval);
- deploying to Azure during the restructuring.

## 3. Audit of the source repository

### 3.1 Structure and tooling

The audit confirmed the following gaps:

| Item | State |
| --- | --- |
| `infra/` (Bicep or Terraform) | Absent; Azure resources were created manually. |
| `.devcontainer/` | Absent. |
| `justfile` or `Makefile` | Absent. |
| `ruff` (lint and format) | Not configured. |
| `pyright` or another type checker | Not configured. |
| `pre-commit` | Not configured. |
| `gitleaks` | Not configured. |
| `docs/configuration.md` | Absent. |

### 3.2 Configuration drift

`.env.example` already declared 41 keys, including optional and commented entries.
The code reads 12 additional runtime variables that were missing from the template:

```text
AZURE_AI_PROJECT_ENDPOINT      (alias of FOUNDRY_PROJECT_ENDPOINT)
BFF_OWNER_OBJECT_ID
DOCUMENTS_ACCOUNT_URL
DOCUMENTS_CONTAINER
FOUNDRY_HOSTING_ENVIRONMENT    (injected by the platform)
MODEL_MAX_RETRIES
MODEL_TIMEOUT_SECONDS
NOTION_IDENTITY_DIAGNOSTICS
SEARCH_INDEX
SEARCH_INDEXER
SEMANTIC_APPROVAL_MODEL
SEMANTIC_APPROVAL_TIMEOUT
```

Some of these are platform- or CI-injected and should be documented as such, not added
blindly to the local template. A drift test must distinguish three categories:

1. local developer variables;
2. BFF-only variables;
3. platform- and CI-injected variables (`FOUNDRY_HOSTING_ENVIRONMENT`, `GITHUB_*`,
   `DEPLOYED_AGENT_VERSION`).

`azure.yaml` parameterized only two values
(`AZURE_OPENAI_BASE_URL` and `AZURE_AI_MODEL_DEPLOYMENT_NAME`). The rest were hard-coded:
Foundry project and resource names, toolbox endpoint, BFF callback URL, storage account,
Key Vault URL, managed identity client ID, owner ID, SSH host, SSH host key, and AI Search
endpoint. `publish-bff.yml` also hard-coded the Azure Container Registry name.

The workflows already read Azure OIDC settings from repository variables
(`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_LOCATION`,
`FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_PROJECT_ID`, `FOUNDRY_MODEL_NAME`,
`AZURE_OPENAI_BASE_URL`, `BFF_AUTO_PUBLISH`). These are not hard-coded secrets, but they
must be documented and set per environment.

### 3.3 Documentation language

The repository mixed French and English:

- **Already English:** `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/README.md`,
  the PWA README, and about a dozen technical documents.
- **French:** approximately 38 artifacts, including `AGENTS.md`, the system guide
  (`docs/guide/`), the CI/CD documents, several feature documents, and personal setup notes.
- **French file names:** the guide chapters and the generated guide HTML/PDF.

The language policy itself was permissive: `AGENTS.md`, `CONTRIBUTING.md`, and
`docs/README.md` explicitly allowed French or English. That policy must change to
English-only for repository artifacts.

Important exception: the French strings in `confirmations.py`, `language.py`,
`semantic_approval.py`, and `pwa/src/narration.ts` are **runtime behavior**, not
documentation. They implement the owner-facing bilingual experience and are asserted by
tests. They should remain bilingual unless the product decision changes.

### 3.4 Delivery and deployment risk

The source repository had three active workflows:

| Workflow | Trigger | Effect |
| --- | --- | --- |
| CI | Pull request and push to `main` | Tests and component checks; no deployment. |
| CD | `workflow_run` after a successful CI on `main`; manual dispatch | Deploys the Hosted Agent. |
| Publish BFF | `workflow_run` after a successful CI on `main`; manual dispatch | Builds and pushes the BFF image to ACR. |

Consequences:

- A pull request alone does not deploy.
- Merging to `main` can deploy the agent and publish the BFF image.
- Changes under `src/savant/` (outside BFF files), `azure.yaml`, `.agentignore`, or
  `pyproject.toml` make the agent eligible for deployment.
- A repository-wide `ruff format` of `src/` would therefore trigger an agent deployment.

The safe default during restructuring is to disable `CD` and `Publish BFF` while keeping
`CI` for pull-request validation. Disabling all Actions is possible but removes CI too.

### 3.5 Git history and personal data

The source repository contains personal resource names, an owner ID, an SSH host, a
managed identity client ID, and related endpoints in `azure.yaml` and in older commits.
Removing them from the current files does not remove them from Git history.

For a public portfolio repository, the practical options are:

1. start from a new repository with a clean history (recommended);
2. rewrite the history of the existing repository (riskier and unnecessary here);
3. keep the history private and publish only selected artifacts.

## 4. Work completed in this session

### 4.1 Microsoft Foundry skill

Installed the official `microsoft-foundry` skill globally for OpenCode:

| Property | Value |
| --- | --- |
| Source | `microsoft/skills` |
| Path in source | `.github/plugins/azure-skills/skills/microsoft-foundry` |
| Commit | `0696600436a9669184ce47e8d8b2ceac62e4bfac` |
| Skill version | `1.2.32` |
| License | MIT |
| Local path | `~/.config/opencode/skills/microsoft-foundry` |
| Size | 222 files, approximately 1.9 MB |

The router version was chosen over the documentation-only alternative in
`MicrosoftDocs/Agent-Skills` because it covers the workflows this repository needs:
Hosted Agent lifecycle, Toolbox, RBAC, model deployment, CI/CD, evaluation, and
troubleshooting. A `SOURCE.md` file records the upstream provenance.

The skill declares a mandatory dependency check:
`scripts/check-and-setup-dependencies.sh`. The script only checks for `azd` and the
`microsoft.foundry` extension and installs the extension if it is missing. In this
environment both were already present, so the check would exit without installing
anything. It was not executed automatically, in line with the project rule that any
`azd` command with an effect requires explicit approval.

### 4.2 Azure Developer CLI update

`azd` was updated from 1.34.1 to 1.37.3 using the official install script.

Verification after the update:

- `azd version` reports 1.37.3;
- the `microsoft.foundry` extension remains installed at `1.0.0-beta.2`;
- no Azure authentication, subscription change, or resource operation was performed.

### 4.3 New public repository

Created and cloned the new public repository:

| Property | Value |
| --- | --- |
| Repository | `boussecsou/savant-azurian` |
| Visibility | Public |
| Local path | `<local clone>` |
| Branch | `main`, tracking `origin/main` |
| Initial commit | `2e86d8a Initial commit` |
| Current contents | `LICENSE`, `README.md` |

The source repository was left untouched. No code, configuration, or documentation was
copied into the new repository in this session.

## 5. Decisions

### 5.1 Repository strategy

Use the new public repository for the portfolio work and keep the existing private
repository as the known-good working environment. This avoids accidental changes to a
working setup and starts the public repository with a clean history.

### 5.2 Pull-request strategy

One pull request per logical unit, grouped by phase, with a tracking issue. Large phases
are split into smaller pull requests:

| Phase | Proposed pull requests |
| --- | --- |
| 1. Configuration | One: configuration reference, `.env.example`, drift test, parameterized `azure.yaml`. |
| 2. Infrastructure | Three or four: Bicep skeleton, service modules, RBAC/OIDC, setup scripts. |
| 3. Repository baseline | Two or three: lint/format (separate), devcontainer/justfile, release automation and ADRs. |
| 4. English migration | Four or five: engineering guide and policies, system guide, CI/CD docs, feature docs, personal notes. |
| 5. Guides | Two: PWA user guide, Azure installation guide and demo. |

The formatting pull request must be isolated because formatting `src/` makes the agent
eligible for deployment.

### 5.3 GitHub Actions policy

Recommended:

- keep `CI` enabled for pull-request validation;
- disable `CD` and `Publish BFF` until the restructuring is complete;
- in a new repository without Azure OIDC variables, deployment workflows fail closed,
  but disabling them explicitly is clearer.

### 5.4 Language policy

Repository artifacts must be English-only:

- documentation, comments, file names, commit messages, issue and pull-request templates;
- configuration examples and infrastructure code.

Runtime owner-facing strings remain bilingual (French and English) because they are part
of the product behavior. This exception must be documented explicitly.

## 6. Proposed work plan

### Phase 1 — Single source of configuration

Deliverables:

- `docs/configuration.md`: every variable, its scope, default, whether it is secret, and
  where it is set;
- complete `.env.example` with the 12 missing runtime variables, marking platform- and
  CI-injected values;
- `tests/test_config_docs.py`: drift test across `Settings`, the BFF settings, and the
  scripts;
- parameterized `azure.yaml` using environment variables only;
- `ACR_NAME` read from a repository variable in `publish-bff.yml`;
- `scripts/setup/` for secrets stored in Key Vault;
- documented GitHub repository variables.

Risk: modifying `azure.yaml` makes the agent eligible for deployment. Merge this phase
while `CD` is disabled, or accept one intentional deployment.

### Phase 2 — Infrastructure as code

Deliverables:

- `infra/` with Bicep modules per service and safe parameter defaults;
- `azure.yaml` `infra:` section and outputs written to the `azd` environment;
- user-assigned managed identity and GitHub OIDC federated credential;
- RBAC role assignments;
- scripts for tasks that Bicep does not handle well: Cosmos DB data-plane roles, AI Search
  index setup, Foundry Toolbox, Notion integration, and BFF Easy Auth;
- `azd up` and `azd down` documentation, plus a cost table.

Open question: confirm with the `microsoft-foundry` skill what Bicep can provision for a
Hosted Agent and what must remain scripted.

### Phase 3 — Repository baseline

Deliverables:

- `.devcontainer/` with Python 3.13, Node 22, `az`, `azd`, `uv`, and `gh`;
- `justfile` with test, lint, PWA, docs, and infrastructure targets;
- `ruff`, `pyright`, `pre-commit`, `gitleaks`, and coverage reporting;
- Dependabot for GitHub Actions (SHA-pinned) and Python/Node dependencies;
- `release-please` configuration and workflow;
- ADRs and a threat model for the two consent layers and the SSH judge.

### Phase 4 — English-only migration

Deliverables:

- translate `AGENTS.md` first, because it is the engineering source of truth;
- translate `docs/README.md`, the system guide, the CI/CD documents, and the feature
  documents;
- rename French guide files and regenerate the PDF;
- update every cross-link;
- archive or remove personal notes;
- change the language policy in `AGENTS.md`, `CONTRIBUTING.md`, and `docs/README.md`;
- add a lightweight check for French file names and headings (not a full language
  detector).

### Phase 5 — Guides and portfolio

Deliverables:

- PWA user guide in English, with Playwright screenshots against a mocked BFF and a
  reproducible PDF build;
- Azure installation guide in English, with portal screenshots and blurred identifiers;
- demo GIF or video;
- architecture diagram near the top of the README;
- issue templates and a code of conduct.

## 7. Open questions

1. Should the new repository start with an empty history (current state) or receive the
   existing code in one initial import commit?
2. Should `CI` be enabled in the new repository before the first pull request, or should
   tests run locally until the infrastructure is ready?
3. Should `CD` and `Publish BFF` be disabled in the source repository as an extra
   precaution, or should the source repository remain completely untouched?
4. Which Azure resources should Bicep own, and which should remain scripted because the
   Foundry or data-plane APIs do not support Bicep well?
5. Should the runtime remain bilingual, or should the product itself become English-only?
   The recommendation is to keep the runtime bilingual and make only repository artifacts
   English-only.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Accidental deployment during restructuring | Unwanted agent release or BFF image push | Disable `CD` and `Publish BFF`; do not merge to `main` until ready. |
| Personal identifiers in a public repository | Privacy and security exposure | Start from the clean new repository; never copy `azure.yaml` values; add `gitleaks`. |
| Formatting `src/` triggers deployment | Unwanted release | Isolate formatting in its own pull request while `CD` is disabled. |
| Configuration drift returns | Setup breaks for new contributors | Drift test in CI; document every variable in `docs/configuration.md`. |
| Translation drift | Repository returns to mixed languages | English-only policy; review checklist; file-name check. |
| Skill or CLI version drift | Workflows change unexpectedly | Record skill source commit and `azd` version; pin in documentation. |
| Runtime bilingual behavior mistaken for documentation | Broken French support and failing tests | Document the exception explicitly; do not translate runtime strings. |

## 9. Verification performed

| Check | Result |
| --- | --- |
| `azd version` | 1.37.3 |
| `azd extension list --installed` | `microsoft.foundry` 1.0.0-beta.2 present |
| `gh repo view boussecsou/savant-azurian` | Public, `main`, not empty |
| `gh workflow list` (source repository) | `CI`, `CD`, and `Publish BFF` active |
| `git status` (new repository) | Clean, `main` tracking `origin/main` |
| `git log` (new repository) | `2e86d8a Initial commit` |
| Azure calls | None |
| Tests | Not run |
| Deployments | None |

## 10. Sources

- Microsoft skills repository: <https://github.com/microsoft/skills>
- Alternative documentation skill: <https://github.com/MicrosoftDocs/Agent-Skills>
- OpenCode skills documentation: <https://opencode.ai/v2/docs/skills>
- GitHub Actions workflow disabling:
  <https://docs.github.com/actions/managing-workflow-runs/disabling-and-enabling-a-workflow>
- GitHub Actions repository settings:
  <https://docs.github.com/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository>
- Azure Developer CLI update command: <https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd>

## Appendix A — Commands executed

The following commands were executed. Personal identifiers are intentionally omitted.

```bash
# Skill installation
git clone --depth 1 --filter=blob:none --sparse https://github.com/microsoft/skills.git /tmp/microsoft-skills
cd /tmp/microsoft-skills
git sparse-checkout set .github/plugins/azure-skills/skills/microsoft-foundry
cp -a .github/plugins/azure-skills/skills/microsoft-foundry ~/.config/opencode/skills/microsoft-foundry

# Azure Developer CLI update
azd update --no-prompt
azd version
azd extension list --installed --output json

# Repository checks
gh repo view boussecsou/savant-azurian --json nameWithOwner,visibility,isEmpty,defaultBranchRef
gh workflow list

# New repository clone
gh repo clone boussecsou/savant-azurian <local clone>
git -C <local clone> status --short --branch
git -C <local clone> log --oneline -3
```

## Appendix B — What this report does not claim

- It does not claim that the existing repository is already reproducible.
- It does not claim that the new repository contains the agent code.
- It does not claim that the infrastructure is provisioned or validated.
- It does not claim that the English migration is complete.
- It does not claim that the deployment workflows have been changed.
