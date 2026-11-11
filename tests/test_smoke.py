import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from savant.config import Settings
from savant.health import RUNTIME_SMOKE_EXPECTED, RUNTIME_SMOKE_PROMPT
from savant.tools.notion_foundry import build_foundry_graph
from scripts.smoke_test import main, validate_response


def response(text=RUNTIME_SMOKE_EXPECTED, status="completed", output=None):
    return {
        "status": status,
        "output": output
        if output is not None
        else [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


@pytest.mark.parametrize("stream", [False, True])
def test_smoke_accepts_completed_model_response(stream):
    payload = response()
    body = (
        ("event: response.completed\ndata: " + json.dumps({"type": "response.completed", "response": payload}) + "\n\n")
        if stream
        else json.dumps(payload)
    )
    validate_response("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + body)


@pytest.mark.parametrize(
    "payload",
    [
        response("OAuth consent required: https://consent.example/private"),
        response(status="failed"),
        response(output=[]),
        response(output=[{"type": "mcp_approval_request"}]),
        {"error": {"message": "failure"}},
    ],
)
def test_smoke_rejects_consent_empty_and_incomplete_responses(payload):
    with pytest.raises(ValueError):
        validate_response("HTTP/1.1 200 OK\nContent-Type: application/json\n\n" + json.dumps(payload))


def test_smoke_does_not_publish_raw_response_or_stderr(monkeypatch, capsys):
    monkeypatch.setenv("DEPLOYED_AGENT_VERSION", "11")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def invoke(args, **kwargs):
        assert args[args.index("--version") + 1] == "11"
        assert "--new-session" in args
        assert "--new-conversation" in args
        return SimpleNamespace(returncode=1, stdout="https://consent.example/private", stderr="private headers")

    monkeypatch.setattr("scripts.smoke_test.subprocess.run", invoke)
    assert main() == 1
    logs = capsys.readouterr().out
    assert "private" not in logs
    assert "consent.example" not in logs


def test_runtime_probe_calls_model_without_discovering_personal_tools(monkeypatch):
    class Toolbox:
        def __init__(self, **kwargs):
            pass

        async def get_tools(self):
            pytest.fail("Runtime probe must not discover personal tools")

    class Model:
        async def ainvoke(self, messages):
            assert messages[-1].content == RUNTIME_SMOKE_PROMPT
            return AIMessage(content=RUNTIME_SMOKE_EXPECTED)

    monkeypatch.setattr("savant.tools.notion_foundry.EndpointToolbox", Toolbox)

    def factory(tools):
        assert tools == ()
        return Model()

    graph = build_foundry_graph(
        Settings(
            "https://model/", "model", toolbox_endpoint="https://project/toolboxes/lab/versions/2/mcp?api-version=v1"
        ),
        factory,
        MemorySaver(),
    )

    async def run():
        result = await graph.ainvoke({"messages": [RUNTIME_SMOKE_PROMPT]}, {"configurable": {"thread_id": "health"}})
        assert result["messages"][-1].content == RUNTIME_SMOKE_EXPECTED

    asyncio.run(run())
