# Contributing

Savant Azurian is a personal, single-owner project that is open for reading and reuse ([MIT](LICENSE)). Issues and pull requests are welcome, but there is no promise to merge them: the agent is shaped around one owner's Azure subscription. Be kind: see the [code of conduct](CODE_OF_CONDUCT.md).

## Set up

The quickest way is the **dev container** (`.devcontainer/`): open the repository in VS Code or Codespaces and everything is installed. Otherwise you need Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22 and, optionally, [just](https://just.systems) and [pre-commit](https://pre-commit.com).

```bash
just setup              # uv sync --locked --group dev, and npm ci in pwa/
pre-commit install      # optional: ruff, secrets scan and the docs check before each commit
just check              # lint, docs check, Python tests, web tests and build: what CI runs
```

Without `just`, the equivalent commands are in [`AGENTS.md`](AGENTS.md). No test needs Azure, Notion or a model key. To see the web client without any backend: `cd pwa && npm run dev:mock`. Running the agent for real needs your own Azure resources: see the [README](README.md), the [deployment guide](docs/deployment.md) and [`.env.example`](.env.example). Evaluations that call a model (`--run`) are paid and optional.

## Rules that matter

- **Keep the two consent layers.** OAuth authorizes a workspace; the conversational consent authorizes one operation. Do not weaken either ([ADR-0017](docs/adr/0017-two-layer-authorization-for-notion-writes.md)).
- **Fail closed.** Missing identity, unavailable credentials or an invalid judge output means no write.
- **Never log** an ID, token, OAuth code or query string.
- **Changing a judge prompt** (semantic approval, SSH) requires re-measuring pass^k on the production model; see [`docs/tool-call-evals.md`](docs/tool-call-evals.md).
- **Settings are documented.** A new environment variable needs a row in [`docs/configuration.md`](docs/configuration.md) and a line in `.env.example`; a test fails otherwise.
- **Decisions are recorded.** A decision that is hard to reverse, or that touches authorization, consent or secrets, gets an ADR in [`docs/adr/`](docs/adr/README.md) (copy `template.md`). Never edit an accepted ADR: write a new one that supersedes it.
- **Everything is in English:** documentation, comments, file names, commit messages and templates. The owner-facing French phrases of the runtime are a product feature, not documentation.
- **`requirements.txt` is generated** from `uv.lock`; CI fails if they diverge (`just export-requirements`).
- **Component ownership** lives in [`.github/components.json`](.github/components.json). Code under `src/savant/` deploys the agent when merged to `main`; see [`docs/component-cicd.md`](docs/component-cicd.md).
- **Actions are pinned by commit SHA** with a version comment. Keep that.

## Pull requests

Small, focused PRs, squash-merged, with a [Conventional Commits](https://www.conventionalcommits.org/) title (`feat`, `fix`, `docs`, `ci`, `chore`, `refactor`, `test`). CI must be green: lint, documentation check, secrets scan, Python tests, and the backend and web client checks when they are touched. The pull request template lists what to confirm.
