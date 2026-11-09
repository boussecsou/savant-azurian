"""Tool-free model probe used by deployment checks, never a canned response."""

RUNTIME_SMOKE_EXPECTED = "SA2_RUNTIME_MODEL_OK"
RUNTIME_SMOKE_PROMPT = (
    "Savant runtime model probe. Reply with exactly SA2_RUNTIME_MODEL_OK. "
    "Do not call any tools."
)


def is_runtime_probe(messages):
    """Only a fresh, exact probe takes the tool-free path."""
    return (
        len(messages) == 1
        and messages[0].type == "human"
        and messages[0].content == RUNTIME_SMOKE_PROMPT
    )
