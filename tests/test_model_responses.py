"""Exercise the real OpenAI transport and replay checkpointed tool history."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from savant.agent import build_model
from savant.config import Settings
from savant.graph import build_graph
from savant.identity import BASE_IDENTITY


@pytest.mark.parametrize("asynchronous", [False, True])
def test_responses_tool_loop_and_checkpoint_replay(monkeypatch, asynchronous):
    requests = []

    def provider(request):
        assert request.url == "https://model.example/openai/v1/responses"
        assert request.headers["authorization"] == "Bearer transport-test-token"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "sa2-gpt-6-luna"
        assert body["store"] is False
        assert body["include"] == ["reasoning.encrypted_content"]
        assert "previous_response_id" not in body
        assert body["tools"][0]["name"] == "echo"
        if len(requests) == 1:
            output = [
                {"type": "reasoning", "id": "rs_first", "summary": [], "encrypted_content": "encrypted-reasoning"},
                {
                    "type": "function_call",
                    "id": "fc_first",
                    "call_id": "call_echo",
                    "name": "echo",
                    "arguments": '{"text":"hello"}',
                    "status": "completed",
                },
            ]
        else:
            output = [
                {
                    "type": "message",
                    "id": f"msg_{len(requests)}",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "hello", "annotations": []}],
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": f"resp_{len(requests)}",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "model": "gpt-6-luna-2026-09-22",
                "output": output,
                "parallel_tool_calls": True,
                "tools": body["tools"],
                "tool_choice": "auto",
            },
        )

    transport = httpx.MockTransport(provider)
    with httpx.Client(transport=transport) as client:
        async_client = httpx.AsyncClient(transport=transport)
        monkeypatch.setattr("savant.agent.DefaultAzureCredential", lambda: object())
        monkeypatch.setattr("savant.agent.get_bearer_token_provider", lambda *args: lambda: "transport-test-token")
        monkeypatch.setattr(
            "savant.agent.ChatOpenAI",
            lambda **kwargs: ChatOpenAI(
                **kwargs,
                http_client=client,
                http_async_client=async_client,
            ),
        )
        settings = Settings("https://model.example/openai/v1/", "sa2-gpt-6-luna")
        graph = build_graph(build_model(settings))

        async def run():
            try:
                result = (
                    (await graph.ainvoke({"messages": [HumanMessage("Echo hello")]}))
                    if asynchronous
                    else graph.invoke({"messages": [HumanMessage("Echo hello")]})
                )
                assert result["messages"][-1].text == "hello"
                assert result["messages"][-2].type == "tool"
                assert result["messages"][-2].content == "hello"
                # The production checkpointer uses this serializer. Rebuild the
                # client as request-scoped graphs do, then replay restored state.
                serde = JsonPlusSerializer()
                restored = serde.loads_typed(serde.dumps_typed(result["messages"]))
                model = build_model(settings)
                messages = [SystemMessage(BASE_IDENTITY), *restored, HumanMessage("Repeat it")]
                response = await model.ainvoke(messages) if asynchronous else model.invoke(messages)
                assert response.text == "hello"
            finally:
                await async_client.aclose()

        asyncio.run(run())

    assert len(requests) == 3
    for body in requests[1:]:
        history = body["input"]
        assert any(item.get("encrypted_content") == "encrypted-reasoning" for item in history)
        assert any(item.get("type") == "function_call" and item["call_id"] == "call_echo" for item in history)
        assert any(
            item.get("type") == "function_call_output" and item["call_id"] == "call_echo" and item["output"] == "hello"
            for item in history
        )
        assert all("id" not in item for item in history if item.get("type") == "message")
