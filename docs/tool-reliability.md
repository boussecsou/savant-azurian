# Tool reliability: confirmations, timeouts, retries and errors (task 29)

One rule for every tool, implemented in `src/savant/reliability.py` and applied in the chat graph (`tools/notion_chat.py`).

## Common rule for sensitive operations

| Tool family | Runs directly | Asks first | Mechanism |
| --- | --- | --- | --- |
| Notion | reads (read-only hint), additive edits that keep existing content | deletions, replacements, anything unknown | semantic approval + one-shot encrypted ledger, bound to the exact operation |
| Toolbox (web, code, Outlook) | web search, tool search, Outlook reads and reversible bookkeeping | code interpreter, send, reply, delete, unknown tools | same semantic approval and ledger (`toolbox_policy.py`) |
| SSH | reads and additions (new file, append), as judged by the command judge | deletions, overwrites, changes to sets of targets, durable system changes, commands driven by outside content, judge failures; secrets are refused | semantic command judge, hard-coded floor as backstop, then same command, later user turn, single use (`ssh.py`) |

In every case: the confirmation text is built from the exact arguments, model output and tool output never count as approval, and a missing identity or store blocks the operation (fail closed).

## Timeouts

| Step | Limit |
| --- | --- |
| Model call | `MODEL_TIMEOUT_SECONDS` (default 90 s) |
| Approval classifier and SSH command judge | `SEMANTIC_APPROVAL_TIMEOUT` (default 10 s) |
| Loading the Notion catalog | 30 s |
| Loading the toolbox | 12 s, then a 45 s pause before the next attempt (the turns in between answer without it); the warm-up request starts the load ahead of the first turn |
| One tool call | 60 s |
| SSH | 10 s connect, 30 s command |
| BFF relay | 120 s per silence, 220 s per answer |

## Retries

- **Model**: the SDK retries 408/429/5xx and network errors with backoff, at most `MODEL_MAX_RETRIES` times (default 2). The judges (approval classifier, SSH command judge) are retried once, inside their own timeout, so a rate limit shared with the main agent does not look like a "no"; any other failure means "not approved" and is logged as `approval_judge_failed` / `ssh_judge_failed` with a short reason (never content).
- **Reads**: one retry, only for a transient failure (timeout, network error, HTTP 408/429/502/503/504). The wait grows with jitter (about 1 s, at most 8 s) and is never shorter than a numeric `Retry-After` the service sent.
- **Several reads in one step** run side by side, at most 4 at a time; results keep the order of the calls. A failed read does not stop the others. Additive writes still go one by one through the ledger, after the reads.
- **Writes**: never retried. A failure in the middle is reported as an uncertain result, and the agent checks the state before trying again.
- **Loop guard**: a turn stops after 8 model steps that asked for tools, and the agent asks the owner how to continue.

## What the model reads

- **Arguments are checked before the call** against the tool's JSON schema. A wrong one is answered at once with `invalid_arguments` and the argument concerned, and the tool is not called. A schema that cannot be read never blocks a call.
- **A result is cut at 20,000 characters**, with a note asking for a narrower part. Only the copy the model reads is shortened.
- **Older results shrink**: tool results from before the last three user messages are replaced by a short marker in what the model sees (the saved conversation keeps them; the agent can read the data again).
- **Outside content is marked as data** (`spotlight.py`): successful results of Notion, the web and the toolbox are wrapped in `<untrusted_data>` tags, and the system prompt says that what is inside is never an order. This raises the bar; it does not stop a determined attacker alone.
- **Outside content and SSH**: when the turn has read outside content, the SSH command judge is told so and asks for confirmation if a command looks driven by that content rather than by the owner. A plain read still runs (issue #51).
- **SSH commands of one step** run side by side (at most 4); their verdicts are asked side by side too. At most one of them waits for confirmation.

## Errors the owner sees

Tool failures come back as structured JSON to the model (`tool_timeout`, `tool_temporarily_unavailable`, `tool_execution_failed`, with `retryable`), never with the raw exception text. The model turns them into a short explanation; the server's own notices (blocked write, uncertain result, unavailable toolbox) are plain English sentences.

## Tests

`tests/test_tool_pipeline.py` (parallel reads and their limit, schema check, cut and marked results, shorter history, backoff and `Retry-After`, toolbox pause and warm-up, VM taint), `tests/test_reliability.py` (transient retry then success, timeout retried once then reported, permanent error not retried, loop guard, classification, model bounds), plus the confirmation and cancellation tests in `test_semantic_*`, `test_toolbox_policy.py` and `test_ssh_tool.py`.

The choice of tools and arguments by the real model is measured separately, with repeated trials (pass^k): see `docs/tool-call-evals.md`.
