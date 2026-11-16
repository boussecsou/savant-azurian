# Component-based CI

## Scope

The repository holds two deployable components, the Hosted Agent and the backend (BFF), and a web client that is validated but not deployed. The registry `.github/components.json` holds the runtime paths, the CI checks and the packaged backend files. `scripts/component_changes.py` applies these rules to decide which CI jobs a change needs. **There is no automated deployment**: merging to `main` deploys nothing, and the agent and the backend are rolled out by hand ([deployment guide](deployment.md)). The design is in [SDD-004](design/sdd-004-continuous-integration-and-delivery.md).

| Change | Python CI | Backend build and smoke test in CI |
| --- | --- | --- |
| Agent only, for example `src/savant/graph.py` | Yes | No |
| Backend only, for example `oauth_callback.py` | Yes | Yes |
| Shared OAuth code or `uv.lock` | Yes | Yes |
| Documentation only | Yes | No |
| Backend checks or workflow only | Yes | Yes |
| A path nobody owns | Yes | Yes |

CI runs on pull requests and pushes to `main`. It uses a full Git comparison and always runs the Python suite. The backend Docker build and smoke test run only for the relevant backend paths; when the comparison is impossible, they run as a precaution. An unknown path counts as a change to every component, on purpose: it is the conservative failure mode.

## The backend boundary

The build uses the Python modules explicitly listed in `components.bff.source_files`. `scripts/package_bff.py` analyzes their static local Python imports and refuses the build if an existing imported file is not declared. The Dockerfile copies only that result into the final image. A dynamically loaded dependency must be added explicitly to the registry and covered by the smoke test; the static analysis cannot infer it. Python dependencies are still shared: any change to `uv.lock` or `pyproject.toml` therefore concerns both components.

To add a component, define its runtime files and its CI checks, identify the shared dependencies explicitly, then add scenarios for isolated, shared, mixed and deleted changes. Unowned paths stay conservative until their owner is defined.

## Validation and limits

The local tests simulate Git comparisons and the packaging rules. The Docker build and smoke test must also pass in GitHub CI. A green CI does not prove that an image was published or that an agent was deployed: neither happens from this repository.
