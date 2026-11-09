"""Real locked SDK serialization; synthetic HTTP responses, no model inference."""
import asyncio
import json

import httpx
import pytest
from langchain_openai import ChatOpenAI

from savant.agent import build_model
from savant.config import Settings
from savant.semantic_approval import SemanticApprovalGuardrail


@pytest.mark.parametrize("response_kind,expected", [
    ("valid", "APPROVE"), ("invalid", "CLARIFY"), ("refusal", "CLARIFY"),
    ("incomplete", "CLARIFY"), ("unavailable", "CLARIFY"), ("rate_limited_once", "APPROVE"),
])
def test_guardrail_responses_wire_contract(monkeypatch, response_kind, expected):
    requests = []

    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "existing-small-deployment"
        assert body["store"] is False
        assert body["max_output_tokens"] == 256
        assert body["reasoning"]["effort"] == "none"
        assert not body.get("tools")
        assert "previous_response_id" not in body
        schema = body["text"]["format"]
        assert schema["type"] == "json_schema" and schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        if response_kind == "unavailable":
            return httpx.Response(503, json={"error": {"message": "synthetic outage"}})
        if response_kind == "rate_limited_once" and len(requests) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "10"},
                                  json={"error": {"message": "synthetic rate limit"}})
        content = ([{"type": "refusal", "refusal": "synthetic refusal"}]
                   if response_kind == "refusal" else
                   [{"type": "output_text", "text": '{"decision":"APPROVE"}'
                     if response_kind != "invalid" else '{"decision":"EXECUTE"}', "annotations": []}])
        return httpx.Response(200, json={
            "id": "resp_synthetic", "object": "response", "created_at": 0,
            "status": "incomplete" if response_kind == "incomplete" else "completed",
            "error": None, "model": "existing-small-deployment",
            "incomplete_details": {"reason": "max_output_tokens"} if response_kind == "incomplete" else None,
            "output": [{"type": "message", "id": "msg_synthetic", "role": "assistant",
                        "status": "incomplete" if response_kind == "incomplete" else "completed",
                        "content": content}],
        })

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            monkeypatch.setattr("savant.agent.DefaultAzureCredential", lambda: object())
            monkeypatch.setattr("savant.agent.get_bearer_token_provider", lambda *args: lambda: "synthetic-token")
            monkeypatch.setattr("savant.agent.ChatOpenAI", lambda **kwargs: ChatOpenAI(**kwargs, http_async_client=client))
            model = build_model(Settings("https://model.invalid/openai/v1/", "main-deployment",
                                        semantic_approval_model="existing-small-deployment"), (), guardrail=True)
            decision = await SemanticApprovalGuardrail(model).evaluate(
                operation={"name": "notion-update-page", "args": {"page_id": "sandbox", "title": "New"}},
                proposal="Change this exact title", user_message="ui, lance")
            assert decision == expected
    asyncio.run(scenario())
    # One retry at most (a rate limit shared with the main agent), always inside the judge's timeout.
    assert len(requests) == (2 if response_kind in {"unavailable", "rate_limited_once"} else 1)
