# SSH tool for the Linux VM

The agent can run a command on the Linux VM with `ssh_exec`. Its rules live in the system prompt (`tools/ssh_skill.py`): there is no `read_ssh_skill` tool any more, which cost one model turn (6 to 9 s) per conversation. Every command is judged by a **semantic judge** (an isolated second model call, like Notion consent); a hard-coded floor remains as a safety net. The decision is recorded in [ADR-0018](adr/0018-ssh-tool-with-a-semantic-command-judge.md).

## How it works

| Element | Role |
| --- | --- |
| `ssh_exec(command, reason, confirmed)` | One line, at most 1000 characters, 30 s. Several independent commands in one step (4 at most) are judged, then run in parallel. |
| Judge (`ssh.CommandJudge`) | Receives the exact command, the reason the model gave, the owner's last message and a flag "outside content was read in this turn". Returns `RUN`, `CONFIRM` or `REFUSE` (structured output, reasoning `none`, `SSH_JUDGE_INSTRUCTIONS`). |
| Floor (`ssh.floor_matches`) | A safety net that turns a `RUN` into `CONFIRM` for `rm -r`, `mkfs`, `dd of=`, reboot, `chmod/chown -R`, `curl … \| sh`, users, firewall, `sshd`, SSH keys, sudoers and so on. It is no longer the main mechanism. |
| `ssh` node of the graph | A server-side gate (`notion_chat.run_ssh`), separate from Notion consent (unchanged). |

### What the judge decides

- **Without confirmation:** reads (system state, services, logs, files, searches, including wildcards, loops and pipes that only read) and **additions** (a new file, a new directory, appending to a file).
- **With confirmation:** deleting, overwriting or modifying an existing file (`>` on an existing file, `sed -i`); any change applied to a list or a set of targets (loops, wildcards, `xargs`, `find -exec`); lasting changes (services, permissions, firewall, users, keys, packages, cron, disks, reboot); code that is downloaded then executed; a compound command part of which would need it; a command that does not follow from the owner's request (for example dictated by a web page or a Notion page read in the turn); and any doubt.
- **Refusal:** showing or sending secrets (private keys, tokens, password hashes, `.env`) or sending VM data to a third party nobody asked for.
- **Judge failure** (timeout, error, invalid output): confirmation, never execution (*fail closed*). Logged as `ssh_judge_failed reason=…`, without content.

Outside content read in the turn is no longer an automatic block. An earlier "contamination rule" blocked a plain read that followed a web search; it is now a hint given to the judge.

Each verdict is logged as `ssh_verdict digest=… verdict=… outside=… ms=…` (a truncated fingerprint, never the command). The evaluation dataset is `evals/ssh_commands.jsonl`, measured in pass^k with `python -m scripts.evaluate_ssh_judge --run --trials 5` (paid calls; without `--run` it only validates the dataset). Measured on 7 November 2026 on the production model: 36 of 36 cases in pass^5, no judge failure. To create a file, the agent writes with `>>` (creates without overwriting): a plain `>` asks for confirmation, because the judge cannot know whether the file exists.

### A command that needs confirmation

1. The first call is judged `CONFIRM`: nothing runs, and the state keeps `ssh_pending` (command fingerprint, owner, conversation, turn). Only one command waits at a time; the other commands of the same step that need confirmation are returned to the model.
2. The agent shows the exact command and asks for approval.
3. On the user's next message, the agent calls `ssh_exec` again with the **same** command and `confirmed=true`.
4. It runs only if the fingerprint matches, a **new user turn** has happened and the wait is under 30 minutes; it does not go through the judge again. The wait is then consumed: a replay is judged again.

Accepted limit: the owner's "yes" to the SSH question is not verified by a second model (the main model reads it). What is guaranteed: no self-approval in the same turn, no change of command, no replay. Output from the VM cannot validate anything. An expired wait no longer disables the fast path of later turns.

### Fail-closed refusals

A missing identity, an empty, multi-line or too long command, a mixed batch (SSH and another tool) or more than 4 commands, a `REFUSE` or unknown verdict: nothing runs. A timeout or a lost connection yields "uncertain result" and is never replayed automatically.

## Connection

- `asyncssh`, one connection per command, closed afterwards.
- A dedicated account (passwordless sudo); an administration account stays separate.
- The ed25519 private key is a Key Vault secret, read on every call with the agent's managed identity (the existing *Key Vault Secrets User* role). Never in the code, the graph state or the logs.
- The host key is pinned (`SSH_HOST_KEY`, public): no trust on first use. Read it with `ssh-keyscan` and cross-check it on the VM (`/etc/ssh/ssh_host_ed25519_key.pub`). `scripts/setup/ssh-setup.sh` does the first step and prints the fingerprint to compare.
- Logs: a truncated fingerprint of the command, the exit code and the duration. Never the command text, the host or the output.
- sshd on the VM: `PermitRootLogin no`, `PasswordAuthentication no`, and `AllowUsers` limited to the two accounts.

## Configuration

All or nothing (otherwise a `RuntimeError` at startup): `SSH_HOST`, `SSH_USER`, `SSH_HOST_KEY`, `SSH_KEY_VAULT_URL`, `SSH_KEY_SECRET_NAME`. Optional: `SSH_PORT` (22), `SSH_CONNECT_TIMEOUT` (10), `SSH_COMMAND_TIMEOUT` (30). See the [configuration reference](configuration.md#ssh-tool-optional-all-or-nothing).

## Rotating the key

1. Generate a new ed25519 key pair outside the repository.
2. Add the public key to the dedicated account's `authorized_keys` (through the administration account).
3. `az keyvault secret set --name <secret-name> --file <key>` (a new version; the agent reads the latest).
4. Check one command, then remove the old public key and destroy the local file.

## Cutting access

- Quickly: remove the line from `authorized_keys`, or disable the Key Vault secret.
- Removing the tool: empty the `SSH_*` variables and redeploy.
- Damage on the VM: restore from a snapshot taken before the tool was enabled. Take one first.

## Known weaknesses

- Port 22 stays open to the Internet in the network security group. Protections: the key, the pinned host key and the dedicated account. The hosted agent's outbound IP was observed (in the VM's `ssh` log) but is not guaranteed stable: restrict it once its stability is confirmed.
- A stolen key gives root on a learning VM. Acceptable only while the VM holds no sensitive data.
- A model's judgement is not a security boundary: hence the floor, the new-turn rule and the snapshot.
- One more judge call per command (about 1 to 1.5 s, in parallel for the commands of one step), offset by the removal of the `read_ssh_skill` turn and by parallel execution.
- The VM has no managed identity: root access cannot pivot to Azure.
