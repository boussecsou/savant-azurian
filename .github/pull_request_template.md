## What and why

<!-- One or two sentences. Link the issue or task if there is one. -->

## Checks

- [ ] `uv run --locked pytest` passes (and `npm test && npm run build` in `pwa/` if the PWA changed)
- [ ] `requirements.txt` regenerated if `uv.lock` changed
- [ ] No secret, ID, token or query string added to code, logs or docs
- [ ] Consent layers unchanged, or the change is justified and measured (pass^k)
- [ ] If `src/savant/` (outside BFF files) changed: I know merging deploys the agent
