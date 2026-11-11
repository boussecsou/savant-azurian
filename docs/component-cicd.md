# Component-based CI/CD

## Scope

The repository holds two delivered components, the Hosted Agent and the backend (BFF), and a web client that is validated but not delivered. The registry `.github/components.json` holds the runtime paths, the CI checks and the packaged backend files. `scripts/component_changes.py` applies these rules; `scripts/release_plan.py` plans each delivery with a checkpoint specific to the component. Adding a service means declaring its paths and its workflow, then creating its CI and CD jobs and its checkpoint: the registry does not create workflows or Azure resources automatically. The design is in [SDD-004](design/sdd-004-continuous-integration-and-delivery.md).

| Change | Python CI | Backend build and smoke test in CI | Agent CD | Backend publication |
| --- | --- | --- | --- | --- |
| Agent only, for example `src/savant/graph.py` | Yes | No | Yes | No |
| Backend only, for example `oauth_callback.py` | Yes | Yes | No | Yes |
| Shared OAuth code or `uv.lock` | Yes | Yes | Yes | Yes |
| Documentation only | Yes | No | No | No |
| Backend checks or workflow only | Yes | Yes | No | No |
| A path nobody owns | Yes | Yes | Yes | Yes |

The table describes the automatic decisions when the checkpoint is available, the history comparable and the CI green. A "Yes" in the publication column is conditional on `BFF_AUTO_PUBLISH=true`. Backend publication creates an immutable registry image; it does not update the Container Apps revision. `workflow_dispatch` on the head of `main` explicitly asks for delivery of the selected component, after checking the CI of the exact SHA.

## Detection and delivery

1. CI runs on pull requests and pushes to `main`. It uses a full Git comparison and always runs the Python suite. The backend Docker build and smoke test run only for the relevant backend paths; when the comparison is impossible, they run as a precaution. A pull request CI authorizes no Azure delivery.
2. Each delivery workflow starts from the SHA of the successful push CI and checks the repository, the branch, the event and that SHA through the GitHub API. It also checks that the SHA is still the head of `main` when planning. A stale run does not deploy and creates no checkpoint. The head can still move during a deployment that has already started; a later run then catches up with the changes.
3. The planner compares the whole range since the component's last successful checkpoint. Deletions and renames are treated as removed and added paths. A failure does not advance the checkpoint; a run discarded by concurrency does not hide its changes.
4. A missing or expired checkpoint, a diverged history or an unknown path: a cautious delivery. An API error or an invalid configuration fails the plan before any Azure authentication. The first run of this version can deliver both components, because the registry and the Dockerfile change and the agent has no historical checkpoint.
5. After the agent deployment and its smoke test succeed, or the backend publication and its digest check, a checkpoint artifact is recorded. An "unchanged" decision recorded after a green CI also advances the comparison point. Artifacts expire after 90 days. To find the last version or image actually delivered, look at the latest artifact where `released` or `published` is true.

Workflows that do not deliver get no Azure OIDC token. Backend publication keeps the `sha-<commit>` tags, the digest check and the registry locks already in place. The two workflows stay serialized separately.

## The backend boundary

The build uses the Python modules explicitly listed in `components.bff.source_files`. `scripts/package_bff.py` analyzes their static local Python imports and refuses the build if an existing imported file is not declared. The Dockerfile copies only that result into the final image. A dynamically loaded dependency must be added explicitly to the registry and covered by the smoke test; the static analysis cannot infer it. Python dependencies are still shared: any change to `uv.lock` or `pyproject.toml` therefore concerns both components.

To add a new component, define its runtime files and its CI checks, identify the shared dependencies explicitly, choose its permissions, its delivery mechanism, its checkpoint and its smoke test, then add scenarios for isolated, shared, mixed and deleted changes and for recovery after a failure. Unowned paths stay conservative until their owner is defined.

## Validation and limits

The local tests simulate Git comparisons, checkpoint pagination, the CI check and the publication commands. The Docker build and smoke test must also pass in GitHub CI. A green CI does not prove that an image was published or that an agent was deployed. Merging a change to the registry activates the existing workflows: examine the plans and the first publications before considering the remote behaviour verified.
