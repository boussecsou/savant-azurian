# Tool-call evaluation (pass^k)

An agent can make a tool call correctly once and then fail when it is repeated. This evaluation measures `pass^k`: the probability that k independent trials **all** succeed, per case and on average.

## Commands

```bash
# Offline validation: no client, no credential, no cost.
python -m scripts.evaluate_tool_calls
# Real model calls (PAID, existing Entra authentication), 3 trials per case.
python -m scripts.evaluate_tool_calls --run --trials 3
# A subset, to iterate more cheaply.
python -m scripts.evaluate_tool_calls --run --trials 2 --limit 4
```

`--trials` is bounded to 1-8 and `--limit` to 1-12. Each case prints `{"id","trials","passes","pass_at_1","pass_hat_k"}`, then an overall summary; the exit code is 1 as soon as a case did not pass all its trials. Without `--run`, the script validates the JSONL (keys, unique ids, known tools, an `expected_tool` that is offered or null, contradictory arguments).

## Limits

- Cost: each trial is a paid inference (12 cases × 3 trials = 36 calls).
- The tool schemas are minimal and fictional, with a coroutine that never runs: selection and arguments are measured, not the real behaviour of Notion, MCP or the web.
- Single-turn evaluation: every call must target the expected tool; a clarification is judged by the absence of a call, not by the quality of the text.
