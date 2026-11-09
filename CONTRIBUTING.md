# Contributing

This is a personal, single-owner project that is open for reading and reuse ([MIT](LICENSE)). Issues and pull requests are welcome, but there is no promise to merge them: the agent is shaped around one owner's Azure subscription.

## Set up

```bash
uv sync --locked --group dev     # Python 3.13
uv run --locked pytest           # no test touches Azure
cd pwa && npm ci && npm test && npm run build   # Node 22
```

No test needs Azure, Notion or a model key. Running the agent for real needs your own Azure resources; see the [README](README.md) and [`.env.example`](.env.example). Evaluations that call a model (`--run`) are paid and optional.

## Rules that matter

- **Keep the two consent layers.** OAuth authorizes a workspace; the conversational consent authorizes one operation. Do not weaken either (see [`AGENTS.md`](AGENTS.md)).
- **Fail closed.** Missing identity, unavailable credentials or an invalid judge output means no write.
- **Never log** an ID, token, OAuth code or query string.
- **Changing a judge prompt** (semantic approval, SSH) requires re-measuring pass^k on the production model; see [`docs/tool-call-evals.md`](docs/tool-call-evals.md).
- **`requirements.txt` is generated** from `uv.lock`; CI fails if they diverge (command in `AGENTS.md`).
- **Component ownership** lives in [`.github/components.json`](.github/components.json). Code under `src/savant/` deploys the agent when merged to `main`; see [`docs/component-cicd.md`](docs/component-cicd.md).

## Pull requests

Small, focused PRs, squash-merged, with a conventional-commit title (`feat`, `fix`, `docs`, `ci`, `chore`). Documentation and commits may be in French or English. CI (`pytest`, BFF smoke test, PWA build) must be green.
