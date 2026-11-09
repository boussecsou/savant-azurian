# Branch ruleset for `main`

`protect-main.json` is the ruleset for `main`: no deletion, no force push, linear history (squash merges), pull request and green CI (`test`, `bff`, `pwa`) required. The repository admin can bypass it, because this is a single-owner project that sometimes pushes documentation straight to `main`.

GitHub only enforces rulesets on a **private** repository with a paid plan (the API answers 403 on the free plan). It works on a **public** repository at no cost. To apply it:

```bash
gh api -X POST repos/boussecsou/savant-azurian/rulesets --input .github/rulesets/protect-main.json
```

The file is a template, not a live setting: GitHub does not read it by itself.
