# Rolling out a new backend image

Publishing a backend image to the registry does **not** update the running Container App. This is the procedure to publish a new image and roll it out, as a deliberate step. The mechanics of publication are in [Publishing the backend image](publish-bff-workflow.md); the delivery rules are in [component delivery](component-cicd.md).

## What happens when a change reaches `main`

| Step | Effect for a backend-only change |
| --- | --- |
| Pull request to `main` | Python tests, Docker build and synthetic readiness; no Azure deployment |
| Squash merge to `main` | A new CI on the merged SHA |
| Automatic agent CD after a green CI | Deployment skipped by the filter (the agent's runtime did not change) |
| Automatic Publish BFF | Skipped while `BFF_AUTO_PUBLISH` is absent or not `true` |
| Manual Publish BFF | Publishes the validated SHA to the registry if the backend inputs changed |
| Azure Container Apps | Stays on its current image until you update it explicitly |

Shared code (`notion_oauth.py`, `oauth_runtime.py`, `oauth_key.py`), the agent runtime and the dependencies still trigger the agent deployment if they change. An unknown file or an impossible comparison also triggers it, as a precaution. A manually started CD always forces the deployment. Prefer **squash** merges: the filter compares `HEAD^..HEAD` and does not guarantee analysis of every commit of a multi-commit push.

## Procedure

1. After review, merge the pull request by squash.
2. Wait for the **push CI on `main`** of the merged commit. The publication workflow requires a green CI on that exact SHA.
3. In GitHub Actions, select **Publish BFF → Run workflow → main**, with `publish_v1=false` (the default). Do not rerun **CD** to publish the backend. CLI equivalent:

   ```bash
   gh workflow run publish-bff.yml --repo <owner>/<repo> --ref main
   ```

4. Wait for the jobs `plan`, `publish` and `checkpoint` to succeed. The run summary and the `bff-publication.json` artifact give the SHA and the digest. The tag produced is `sa2-bff:sha-<full SHA>`, immutable. `v1` must not be rewritten. If no backend input changed since the checkpoint, `publish` can be skipped: then check the image that corresponds to the code you want.
5. When you decide to roll it out, replace the image Container Apps uses with the run's verified digest. The command creates a new revision; with the usual configuration traffic goes to the latest revision. Replace the placeholder first:

   ```bash
   BFF_DIGEST='sha256:REPLACE_WITH_THE_VERIFIED_DIGEST'
   az containerapp update -g <resource-group> -n <app-name> \
     --image "<registry-login-server>/sa2-bff@$BFF_DIGEST"
   azd env set BFF_IMAGE "<registry-login-server>/sa2-bff@$BFF_DIGEST"   # so a later `azd provision` keeps it
   ```

6. Check the revision and the health probe:

   ```bash
   az containerapp show -g <resource-group> -n <app-name> \
     --query '{state:properties.provisioningState,latest:properties.latestRevisionName,ready:properties.latestReadyRevisionName,image:properties.template.containers[0].image}'
   curl --fail --show-error https://<backend-fqdn>/readiness
   ```

   Expected: provisioning succeeded, the latest revision ready, the image at the right digest, HTTP 200 and `{"status":"ready"}`. Redo the log checks with fictitious values; never test by printing real tokens or the Fernet key.

The publication workflow uses OIDC and the registry roles that the template grants. The Container Apps update uses your authorized Azure session; it adds no role to the GitHub identity. No Foundry provisioning is needed. The identities, Key Vault secrets, variables, ingress and scaling of the app are kept by an image update. See [the log audit](bff-logging-audit.md) for the evidence, the limits and the local checks.

## First rollout of a new environment

The Container App starts on a public placeholder image. The first rollout replaces it with an image you build, for example from the public repository (`az acr build … https://github.com/<owner>/<repo>.git#main`). The [deployment guide](deployment.md#8-publish-the-backend-image-and-roll-it-out) has the exact commands, including why you must not run `az acr build .` from a local checkout.
