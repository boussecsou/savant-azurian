# Publishing the backend image to the registry

Workflow: `.github/workflows/publish-bff.yml`. Image: `sa2-bff` in your Azure Container Registry. The build runs on the GitHub runner, without ACR Tasks. The registry name comes from the repository variable `ACR_NAME` (see the [configuration reference](configuration.md#github-repository-variables)).

## Trigger and authorized commit

The workflow starts in manual mode (`workflow_dispatch`, branch `main`). The boolean option `publish_v1` adds the `v1` tag for the first publication. It is `false` by default. The main tag is always `sha-<full SHA>`. Both tags point to the same digest and are locked against writing and deletion, as is the underlying manifest. The workflow never unlocks a tag. An administrator with the right to change ACR attributes could still lift that lock.

To enable automatic publication afterwards, set the GitHub repository variable `BFF_AUTO_PUBLISH=true`. It stays off while that variable does not exist or has another value. The automation waits for a green CI that comes from a **push to `main` in this repository**. CI runs from pull requests, forks, or that were cancelled or failed do not allow publication. The `v1` option stays manual.

Both modes check through the GitHub API that a push CI on `main` succeeded for the exact SHA. The automatic checkout uses `workflow_run.head_sha`, not the head of `main` when the job starts. No CI artifact and no pull request cache is executed with Azure rights. Actions are pinned by SHA.

## Filtering and resumption

`scripts/release_plan.py` looks for the last successful run with a `release-bff-<SHA>` artifact (or the old name `bff-checkpoint-<SHA>`), then compares the whole range up to the validated SHA. `.github/components.json` defines the backend sources, the build inputs and the shared dependencies. The Dockerfile copies into the final image only the modules listed in `source_files`; `scripts/package_bff.py` checks the static local Python imports before that copy. A change to `src/savant/agent.py`, `graph.py` or the agent's own tools therefore does not publish the backend. The shared OAuth modules and the common dependencies concern both components.

Tests, publication scripts and workflows specific to the backend trigger its CI checks, but changing them alone does not create an identical image. A manual publication stays possible to test or repair the publication operation. A SHA that is no longer the head of `main` when the plan runs is ignored, without a checkpoint; the next plan compares all changes since the last eligible checkpoint.

Deletions, renames and multi-commit pushes are covered. A failed run creates no usable checkpoint: its changes stay to be published at the next green CI. A run without changes creates a checkpoint with `published=false`, without Azure authentication. Checkpoints are kept for 90 days; if they expired, if none exists, or if the history diverges, the workflow publishes as a precaution. An API error stops the workflow, without assuming that no change exists.

Concurrency is limited to one publication run, without cancelling an active run. GitHub can replace a run that is still waiting: the comparison with the last checkpoint then also covers the changes of the intermediate runs.

## Build, publication and proof

1. Build `Dockerfile.bff`, with the OCI labels of the repository and the SHA.
2. Run `scripts/smoke_test_bff.py` with a synthetic key and SQLite.
3. Obtain a temporary Azure token through OIDC, then sign in to the registry.
4. Publish `sha-<SHA>` if it is absent. A rerun reuses the digest already present and checks its revision label; it does not replace the image after a possible change of the base images.
5. Optionally add `v1`. If it exists for another digest, fail without overwriting it. Only an explicit "repository not found" answer allows the first push; a network or RBAC error stays an error.
6. Check the remote digest against the one recorded by Docker after the push, pull the image by digest and check the OCI revision.
7. Lock the tags and the manifest, then read their attributes back.
8. Record the digest in the GitHub summary and in `bff-publication.json` (the checkpoint artifact). A partial failure leaves the run red; rerunning resumes the missing checks and locks.

The JSON holds the SHA, the digest, the `published` flag and the run ID. For a run without publication the digest is empty; find the last run with `published=true` for the image reference actually published. A successful publication proves ACR access and the synthetic smoke test. It does not prove real access to Key Vault or Blob, nor the OAuth flow in Container Apps.

## Permissions

The workflow reuses the OIDC identity of the delivery workflow (the repository variable `AZURE_CLIENT_ID`; the Bicep template creates it, see the [deployment guide](deployment.md)). The federation uses the issuer `https://token.actions.githubusercontent.com`, the audience `api://AzureADTokenExchange` and the subject `repo:<owner>/<repo>:ref:refs/heads/main`. The workflow uses `main` and adds no GitHub Environment, which would change that subject. No client secret, no ACR password and no admin account is added.

The registry runs with `roleAssignmentMode=LegacyRegistryPermissions` and the admin user disabled. The identity needs, on **the registry only**:

| Role | Minimal scope | Use |
| --- | --- | --- |
| `Reader` | The registry | Resolving `loginServer` and the ARM read used by Azure CLI |
| `AcrPush` | The registry | Push and pull, reading digests and updating tag and manifest attributes |

Neither Contributor, nor Owner, nor the right to create RBAC assignments is needed by the job. The classic mode cannot restrict `AcrPush` to the single `sa2-bff` repository. A future ABAC migration would allow `Container Registry Repository Writer` with a condition on that repository, with `Reader` for the ARM read. It needs a separate decision: the historical `AcrPush` and `AcrPull` roles are not honoured in ABAC mode.

On the GitHub side, `plan` has `contents: read` and `actions: read`. Only the `publish` job receives `id-token: write`, after the CI and change checks. The `checkpoint` job keeps only `contents: read`.

## Validation and acceptance criteria

Local checks:

```bash
uv run --locked pytest tests/test_should_publish_bff.py tests/test_publish_bff.py
bash -n bff/publish.sh
actionlint -shellcheck= .github/workflows/publish-bff.yml
```

The shell tests need `bash` and `jq`, already provided by `ubuntu-latest`. They replace Azure and Docker with simulated executables. They cover the first push, `v1`, a rerun without a push, a tag conflict, an authentication failure, wrong digests or revisions and a locking failure. The filtering tests cover pagination, expired artifacts and multi-commit ranges.

After review, merge and RBAC agreement:

- [ ] Confirm `Reader` and `AcrPush` on the registry for the OIDC identity.
- [ ] Wait for a green push CI on the SHA of `main`.
- [ ] Run `Publish BFF` manually on `main` with `publish_v1=true`.
- [ ] Check the smoke test, the SHA and `v1` tags, their identical digest, their `writeEnabled=false` / `deleteEnabled=false` attributes and the JSON.
- [ ] Rerun on the same SHA: no overwrite and no new push needed.
- [ ] Then turn on `BFF_AUTO_PUBLISH=true` by explicit decision.
- [ ] Check that a backend change followed by a green CI publishes its SHA, and that a documentation-only change skips the Azure job.
- [ ] Check that a red CI, a pull request CI and a dispatch outside `main` publish nothing.
- [ ] Check that an attempt to move `v1` to another SHA fails.

The workflow stops at the registry publication: the Container Apps rollout stays a separate manual step. No Foundry deployment is added or changed.

## References

- [SDD-004, continuous integration and delivery](design/sdd-004-continuous-integration-and-delivery.md).
- [ADR-0009, the Container Apps backend](adr/0009-bff-owns-user-facing-oauth.md).
- [The `workflow_run` event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).
- [ACR roles and RBAC/ABAC modes](https://learn.microsoft.com/azure/container-registry/container-registry-rbac-built-in-roles-directory-reference).
- [ACR image locking](https://learn.microsoft.com/azure/container-registry/container-registry-image-lock).
