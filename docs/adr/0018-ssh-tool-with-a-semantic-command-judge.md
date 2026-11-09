# ADR-0018: Gate the SSH tool with a semantic command judge

- **Status:** Accepted
- **Date:** 2026-11-09 (recorded retrospectively; the decision was taken while the SSH tool was built, in late October and early November 2026)
- **Tags:** security, agent, infra

## Context

The agent can run shell commands on a dedicated Linux VM. This is a useful lab and monitoring surface and also the most dangerous tool the agent has. A hard-coded list of dangerous commands is easy to bypass (pipes, loops, wildcards, encodings) and blocks harmless commands. An approval prompt for every command makes the tool unusable.

An earlier version also added a rule that blocked any command after the turn had read outside content. That blocked a plain read after a web search, which was not the intent.

## Decision

Judge **every command** with a **semantic judge** before it runs: a second, isolated model call that returns a structured verdict.

| Verdict | Meaning |
| --- | --- |
| `RUN` | Reads (state, services, logs, files, searches, including pipes and loops that only read) and additions (a new file, a new directory, an append) |
| `CONFIRM` | Deletion, overwriting or modifying an existing file, anything applied to a set of targets, durable system changes, code downloaded then executed, a command driven by outside content, and any doubt |
| `REFUSE` | Showing or sending secrets, or sending VM data to a third party nobody asked for |

The judge receives the exact command, the reason the model gave, the owner's last message and a flag saying whether the turn read outside content. That flag is a **hint for the judge, not a block.**

- **A judge failure means `CONFIRM`**, never execution (fail closed).
- **A hard-coded floor** (`rm -r`, `mkfs`, `dd of=`, reboot, recursive `chmod` or `chown`, piped downloads, users, firewall, `sshd`, SSH keys, sudoers…) turns a `RUN` into `CONFIRM`. It is a safety net, not the main mechanism.
- **A confirmed command runs only on a later user turn**, with the same fingerprint, once, and without going back through the judge. A replay is judged again.
- **Hard limits.** One line, at most 1000 characters, 30 seconds, at most 4 independent commands per step, judged and run in parallel. A mixed batch with other tools is refused.
- **The SSH node is independent of Notion consent** ([ADR-0017](0017-two-layer-authorization-for-notion-writes.md)).

**Connection hygiene.** A dedicated account (it can use sudo, which is why the judge exists), an ed25519 private key kept in Key Vault and read at use time, a **pinned host key** (no trust on first use), password login and root login disabled on the VM, and configuration that is all-or-nothing. Logs hold a truncated fingerprint, never the command, the host or the output.

## Consequences

**Positive**

- The common cases (reads and additions) run without friction, and the risky ones always ask.
- The judge is measured like the consent judge: 36 of 36 cases passed with pass^5 on the production model on 2026-11-07, with no judge failure. The dataset lives in `evals/`.

**Negative / risks**

- **Known limit:** the owner's "yes" to an SSH confirmation is read by the main model, not by a second model. What is guaranteed: no self-approval in the same turn, no change of command, no replay. Output from the VM can never validate anything.
- A timeout or lost connection reports an uncertain result and is never replayed automatically.

## Related

[ADR-0017](0017-two-layer-authorization-for-notion-writes.md), [ADR-0019](0019-external-content-is-data.md), [ADR-0020](0020-keyless-access-with-entra-and-key-vault.md), [SSH tool design](../ssh-tool.md), [live validation](../ssh-live-validation-2026-11-02.md)
