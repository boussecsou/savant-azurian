# Continuous delivery of the agent

Implemented in `.github/workflows/cd.yml`. The design is in [SDD-004](design/sdd-004-continuous-integration-and-delivery.md). The workflow ships **disabled by default** in a fresh copy of the repository: it needs your own Azure identity and variables (see the [deployment guide](deployment.md#11-github-actions-optional)).

## Authorized commit and deployment identity

CD starts after a green CI that comes from a push to `main` in this repository. It takes the exact SHA of the CI run. A manual trigger stays possible on `main`, but it also checks that a push CI succeeded on the chosen SHA. The job queries the GitHub API with `actions: read` before any Azure sign-in.

The permissions are `contents: read`, `actions: read` and `id-token: write`. `azure/login` exchanges the GitHub OIDC token for temporary Azure access. The federated credential belongs to a user-assigned identity and is limited to `repo:<owner>/<repo>:ref:refs/heads/main`. No permanent Azure secret is added. `azd` uses the Azure CLI session.

## Configuration comes from GitHub variables

The workflow sets the whole `azd` environment from GitHub repository variables whose names equal the `azd` variables that `azure.yaml` reads (`AZURE_AI_PROJECT_ENDPOINT`, `AZURE_OPENAI_BASE_URL`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `TOOLBOX_ENDPOINT`, the `NOTION_*`, `SSH_*` and `SEARCH_*` values, and so on). Each is described in the [configuration reference](configuration.md#github-repository-variables), and `scripts/setup/github-variables.sh` copies them from your `azd` environment. A test (`tests/test_config_docs.py`) fails if `azure.yaml` reads a variable that `cd.yml` never sets.

The Azure OpenAI base stays in `/openai/v1/` form. The client uses the Responses API with a history managed by LangGraph; see [the model configuration](model-gpt-6-luna.md).

## Deployment and dependencies

The workflow checks that `requirements.txt` matches `uv.lock`, then runs `azd deploy sa2-agent --no-prompt` on the existing project. It adds no provisioning and creates no connection or toolbox.

The service stays on `remote_build`, Python 3.13, entry point `main.py`. `requirements.txt` holds the production versions exported from the lockfile. `.agentignore` excludes `.env` files, CLI state, user logs and the documentation from the ZIP, independently of Git's exclusions.

After deployment, the workflow reads `AGENT_SA2_AGENT_VERSION`, checks its format, then records the SHA and the version in the GitHub summary. A successful deployment without a valid version output fails the job.

## Smoke test: runtime and model

`scripts/smoke_test.py` explicitly invokes `sa2-agent` and the published version, with `--protocol responses`, a new session and a new conversation. The request times out after 180 seconds, and the process after 240 seconds.

The exact message defined in `savant.health` selects, only in a fresh conversation, a call to the **real model with no tools**. It does not discover the toolbox and asks for no personal consent. This path performs no external action and does not return a hard-coded answer.

The checker requires HTTP 200, a Responses `completed` answer, with no error and no tool call or approval, and the exact text `SA2_RUNTIME_MODEL_OK`. It accepts the JSON result and the SSE `response.completed` result. A non-empty output or a consent instruction is no longer enough.

The raw output and stderr of the invocation are captured in memory and are neither printed nor uploaded as an artifact. The summary holds only the SHA, the version, the check result and its duration. Consent links, headers and session identifiers stay out of the smoke test's logs. This does not remove the logs the SDK produces on the Foundry side.

## Personal validation of the tools

The CD identity deploys and tests the runtime. It does not carry the user's OAuth consent and does not accept it on their behalf.

After publication, the user opens a normal conversation in the playground, follows the consent instructions manually if needed, then sends their request again. They then check a real read and, separately, a write with approval or refusal. Consent gives access to the connection; approval authorizes one precise action.

A green CD proves startup, the Responses protocol and the model's inference for the pipeline's identity. It does not prove personal consent, the execution of tools, or the rights of every user.

## Known limits

The smoke test comes after publication. An error fails CD but triggers no automatic rollback. A single environment is used; no blue/green deployment, canary or notification system is added. Actions are pinned by SHA; `azd` and its extension stay installed at the versions their installers offer.

References: [deploying from source in Foundry](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-code), [invoking with azd](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/invoke-hosted-agent), [the workflow_run event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

## Selective deployment (Hosted Agent)

The planner `scripts/release_plan.py` uses the registry `.github/components.json`. After a green CI on the exact SHA, it compares the whole interval from the agent's last successful checkpoint to the tested SHA. Agent changes and shared dependencies cause a deployment; backend-only files, tests and documentation alone do not. A path nobody owns is treated as affecting every component.

The workflow deploys only if the tested SHA is still the head of `main` when planning. An automatic run that has become stale creates no checkpoint. Concurrency serializes the runs; if a waiting run is replaced, the cumulative comparison keeps the undelivered changes. A failed run does not advance the checkpoint. If no valid checkpoint remains or the history diverged, the planner schedules a deployment as a precaution. A manual trigger on the current head of `main` always asks for a deployment, with a green CI.

After a successful deployment and smoke test, or after an explicit decision to deploy nothing, a `release-agent-<SHA>` artifact keeps the comparison point for 90 days. The artifact holds the SHA, the result, the version if a deployment took place, and the run ID. A checkpoint without a deployment does not mean a new version was published. See [component delivery](component-cicd.md).

On `main`, `publish-bff.yml` builds and publishes the backend image to the registry after the CI validates the SHA. It does not update Azure Container Apps. Automatic publication needs `BFF_AUTO_PUBLISH=true`; manual publication stays possible. See the [backend publication workflow](publish-bff-workflow.md).
