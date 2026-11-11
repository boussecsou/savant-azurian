"""Exercise the real Responses host, detached callback, and continuation IDs."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
from azure.ai.agentserver.responses import FileResponseStore, ResponsesAgentServerHost
from cryptography.fernet import Fernet
from langchain_azure_ai.agents.hosting import ResponsesHostServer
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver

from savant.config import Settings
from savant.notion_oauth import NotionOAuth, SQLiteOAuthStore
from savant.oauth_callback import create_callback_app
from savant.tools.notion_chat import build_direct_chat_graph


def test_responses_consent_callback_and_previous_response_resume(monkeypatch, tmp_path):
    async def run():
        def provider(request):
            if request.url.path.endswith("oauth-authorization-server"):
                return httpx.Response(
                    200,
                    json={
                        "authorization_endpoint": "https://mcp.notion.com/authorize",
                        "registration_endpoint": "https://mcp.notion.com/register",
                        "token_endpoint": "https://mcp.notion.com/token",
                        "code_challenge_methods_supported": ["S256"],
                    },
                )
            if request.url.path == "/register":
                return httpx.Response(201, json={"client_id": "registered"})
            return httpx.Response(
                200, json={"access_token": "private-token", "refresh_token": "private-refresh", "expires_in": 3600}
            )

        class ChainStore:
            def __init__(self):
                self.data = {}

            async def get(self, chain, key):
                return self.data.get((chain, key))

            async def set(self, chain, key, data):
                self.data[(chain, key)] = dict(data)

        model_inputs = []
        reads = []
        fetch = StructuredTool.from_function(
            lambda: reads.append(1) or "page réelle simulée",
            name="fetch",
            description="Read page",
            metadata={"annotations": {"readOnlyHint": True}},
        )

        async def discover(settings, token):
            assert token == "private-token"
            return [fetch]

        monkeypatch.setattr("savant.tools.notion_chat.discover_tools", discover)

        def factory(tools):
            class Model:
                async def ainvoke(self, messages):
                    model_inputs.append(messages)
                    if messages[-1].type == "tool" and messages[-1].name == "fetch":
                        return AIMessage(content="Résumé du projet")
                    name = "fetch" if "fetch" in {tool.name for tool in tools} else "connect_notion"
                    return AIMessage(
                        content="", tool_calls=[{"name": name, "args": {}, "id": "call-" + str(len(model_inputs))}]
                    )

            return Model()

        settings = Settings(
            "https://model/",
            "model",
            notion_read_tool_names=("fetch",),
            notion_oauth_callback_url="http://localhost:8090/oauth/notion/callback",
            notion_local_user_id="alice",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as provider_client:
            oauth = NotionOAuth(
                settings.notion_oauth_callback_url,
                SQLiteOAuthStore(str(tmp_path / "oauth.db"), Fernet.generate_key().decode()),
                provider_client,
            )
            graph = build_direct_chat_graph(settings, factory, MemorySaver(), oauth)
            app = ResponsesAgentServerHost(
                store=FileResponseStore(tmp_path / "responses"), configure_observability=None
            )
            host = ResponsesHostServer(graph, app=app, conversation_chain_store=ChainStore())
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host.app), base_url="http://agent") as chat:
                first = await chat.post("/responses", json={"input": "Lis ma page projet", "stream": False})
                assert first.status_code == 200, first.text
                response = first.json()
                text = "\n".join(
                    content.get("text", "") for item in response["output"] for content in item.get("content", [])
                )
                assert "[Connect Notion]" in text
                assert reads == []
                url = text.split("[Connect Notion](", 1)[1].split(")", 1)[0]
                state = parse_qs(urlsplit(url).query)["state"][0]
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=create_callback_app(oauth)), base_url="http://callback"
                ) as callback:
                    returned = await callback.get(
                        "/oauth/notion/callback", params={"state": state, "code": "authorized"}
                    )
                    assert returned.status_code == 200
                second = await chat.post(
                    "/responses", json={"input": "connecté", "previous_response_id": response["id"], "stream": False}
                )
                assert second.status_code == 200, second.text
                assert "Résumé du projet" in second.text
                assert "Continue their pending request: Lis ma page projet" in model_inputs[-2][0].content
                assert reads == [1]
                assert "private-token" not in first.text + second.text + returned.text
                assert "private-refresh" not in first.text + second.text + returned.text

    asyncio.run(run())
