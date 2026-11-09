# Observability of the Hosted Agent (task 30)

The agent already exports its logs to the project's Application Insights (`fp-savant-azurian-2-resource-appinsights`); the BFF writes fixed events to the Container App console. This task adds one **correlation id** per turn and explicit start, path and end lines.

## Correlation id

`savant/correlation.py`: the first 16 hex characters of SHA-256 of the Foundry response id of the turn. The agent receives that id as the turn id; the BFF reads it from the stream's final event. Both log the same hash, never the raw id, the user's text, a token or an owner id.

## Events

| Where | Line | Meaning |
| --- | --- | --- |
| Agent | `turn_start correlation=<id>` | a user turn enters the graph |
| Agent | `turn_step correlation=<id> path=tool round=<n> tools=<names>` | the model asked for tools (names only) |
| Agent | `turn_timing correlation=<id> round=<n> load_ms= token_ms= toolbox_ms= notion_ms= model_ms=` | durations only: catalog loading (OAuth token, toolbox and Notion side by side) and the model call |
| Agent | `turn_timing correlation=<id> round=1 path=fast\|handover fast_ms=<n>` | fast path: answered without tools, or handed over to the full agent |
| Agent | `turn_end correlation=<id> path=fast\|direct\|tool outcome=answered` | final answer, direct or after tools |
| Agent | `turn_end correlation=<id> outcome=tools_unavailable error_type=<type>` | the tool catalog could not load |
| Agent | `turn_end correlation=<id> outcome=loop_guard rounds=<n>` | the turn stopped after too many tool steps |
| Agent | `toolbox_unavailable error_type=… status=… code=… detail=…` | toolbox failed; detail has URLs and long tokens removed |
| Agent | `tool_retry tool=<name> attempt=2` | a read was retried after a transient failure |
| BFF | `INFO chat_relay_completed correlation=<id>` | the answer reached the PWA |
| BFF | `WARNING chat_stream_failed type=…` / `chat_relay_failed status=…` | relay error (status code or exception class only) |

## Follow one call

Agent side (Application Insights, Logs):

```kusto
traces
| where timestamp > ago(1d)
| where message startswith "turn_" or message startswith "toolbox_unavailable" or message startswith "tool_retry"
| extend correlation = extract("correlation=([0-9a-f]{16})", 1, message)
| project timestamp, correlation, severityLevel, message
| order by timestamp desc
```

Then filter one turn with `| where correlation == "<id>"`. Errors are the `severityLevel >= 2` rows.

BFF side (same id): `az containerapp logs show -n ca-sa2-bff -g rg-savant-azurian-2 --tail 100 | grep <id>`.

## What is never logged

User and assistant text, tool arguments and results, tokens, OAuth codes, raw response or owner ids, query strings (unchanged rules of `bff_logging.py` and the agent).

## Tests

`tests/test_observability.py`: stable hash, one correlation per turn for a direct and a tool answer with no private text in the logs, BFF completion line with a valid correlation only, and the BFF logging the agent-side id after a streamed answer.

## Turn latency

Catalog loading used to run up to three times per turn (entry gate, model, tools), each time listing the toolbox (~7 s) and the Notion catalog. Now:

- the toolbox catalog is cached for 10 minutes per process (`TOOLBOX_CACHE_SECONDS`); a consent prompt is never cached; tool calls still carry the per-request Foundry call ID;
- the Notion catalog keeps only token-free MCP definitions for 10 minutes per access token (`NOTION_CATALOG_SECONDS`), forgotten on a 401; tools carrying the token are rebuilt each time;
- one `DefaultAzureCredential` serves the model clients and the toolbox, so tokens are cached instead of requested per turn;
- the OAuth token and the toolbox load side by side.
- a still-valid Notion token is read from the encrypted Blob store in one lock-free download (no lease, no rewrite) and remembered for 30 s; only a refresh takes the leased transaction; `invalidate` forgets it;
- the system message keeps stable instructions first and per-turn parts (voice style, notices) last, so turns share a long prefix eligible for Azure OpenAI prompt caching.

Local measurement on the real graph (no Notion token): 11 s per turn before, about 2 s after the first turn. The BFF warm-up (`POST /api/warmup`) fills these caches. `turn_timing` shows what remains in production (Foundry checkpoints and hosting are not measured locally).

Measured in production (5 November 2026), the largest cost was not in the graph: **Foundry starts a new session for every new conversation** (about 13 s before the first response header; about 21 s for a plain first turn). Within a conversation, the next turns took 8 to 10 s and the catalogs came from cache (`load_ms=2`). So `POST /api/warmup` now returns the warm conversation (`conversation_id`), the PWA keeps it as a spare and continues it for the next new conversation (then prepares another spare). The agent hides that warm-up exchange from the model (`_without_warmup`). Measured: warm-up then a chained question took 8.5 s, against 21 to 25 s for a question in a new conversation.

### Fast path (tool-free turns)

Even with cached catalogs, the full model call took 5 to 6 s in production: every call carries the schemas of all tools (Notion, toolbox, SSH) and reasons about them. Each fresh turn now starts with a **fast call**: same model, no reasoning (`effort: none`), no tool schemas, one hand-over tool `use_tools` and the routing rules of `identity.FAST_PATH_INSTRUCTIONS`. A plain answer ends the turn; `use_tools`, an empty answer, an error or a 15 s timeout falls through to the full agent. The fast call is skipped whenever something waits for confirmation (SSH, Notion actions, pending OAuth request), so confirmations always reach the full agent. It cannot act: its only tool is the hand-over, which never enters the conversation.

Router evaluation on 14 representative turns (greetings, definitions, arithmetic, translation, date; weather, news, Notion read/write, VM, a confirmation): 14/14 routed correctly, median 1.5 s. Real graph, local: simple turns 0.9 to 1.5 s; a tool turn pays about 1 s more for the hand-over. `MODEL_FAST_PATH=false` turns it off.
