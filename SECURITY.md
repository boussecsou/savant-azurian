# Security policy

Savant Azurian 2 is a single-owner personal agent. It has no hosted service open to the public, but the code handles OAuth tokens, an SSH key and consent decisions, so security reports are welcome.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting instead: *Security* tab → *Report a vulnerability* ([`security/advisories/new`](https://github.com/boussecsou/savant-azurian/security/advisories/new)).

Please include the affected file or flow, the steps to reproduce, and the impact you expect. This is a personal project: expect an answer within a few days, not a service-level agreement.

## What counts

Reports that matter most are the ones that break one of the guarantees in [`AGENTS.md`](AGENTS.md):

- a Notion, Toolbox or SSH mutation that runs without the owner's explicit, single-use, operation-bound consent;
- a way to act as another user, or without the trusted owner identity;
- a secret, OAuth code or token written to logs, responses or Git;
- untrusted content (web page, Notion page, tool result) that is obeyed as an instruction.

## Secrets

No secret belongs in Git. Configuration comes from environment variables, Managed Identity with scoped RBAC, and Azure Key Vault ([`.env.example`](.env.example) lists the variables). If you find a real credential in the history, report it privately so it can be rotated.
