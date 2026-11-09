"""Foundry Hosted Agent entry point for Savant Azurian 2."""

from __future__ import annotations

from collections.abc import Sequence

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain_azure_ai.agents.hosting import ResponsesHostServer
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from .config import Settings
from .graph import ChatModel, build_graph
from .tools import DEFAULT_TOOLS


MODEL_TOKEN_SCOPE = "https://ai.azure.com/.default"


def build_model(
    settings: Settings, tools: Sequence[BaseTool] = DEFAULT_TOOLS, *, guardrail: bool = False,
    token_provider=None, reasoning_effort: str | None = None,
) -> ChatModel:
    """Create an Entra-authenticated Responses client with LangGraph-owned history.

    Pass a shared `token_provider` when building a client per turn: a new DefaultAzureCredential
    per call would request a fresh managed identity token every time.
    """

    token_provider = token_provider or get_bearer_token_provider(
        DefaultAzureCredential(),
        MODEL_TOKEN_SCOPE,
    )
    model = ChatOpenAI(
        base_url=settings.azure_openai_base_url,
        api_key=token_provider,
        model=(settings.semantic_approval_model or settings.model_deployment_name)
              if guardrail else settings.model_deployment_name,
        use_responses_api=True,
        output_version="responses/v1",
        # Replay reasoning across tool calls/checkpoints without relying on
        # provider-side response storage or previous_response_id.
        store=False,
        include=["reasoning.encrypted_content"],
        # Judges: no reasoning. Measured with pass^k on GPT-6 Luna, more reasoning made the judge
        # doubt plain yeses (issue #50) and was slower. One retry absorbs a rate limit (429) shared
        # with the main agent; the guardrail's own timeout still bounds the whole call.
        **({"max_retries": 1, "timeout": settings.semantic_approval_timeout,
            "max_tokens": 256, "reasoning_effort": "none", "disable_streaming": True} if guardrail
           else {"timeout": settings.model_timeout, "max_retries": settings.model_max_retries,
                 **({"reasoning_effort": reasoning_effort or settings.model_reasoning_effort}
                    if (reasoning_effort or settings.model_reasoning_effort) else {})}),
    )
    return model.bind_tools(tools) if tools else model


def _document_search(settings: Settings, credential):
    """Azure AI Search for the project's documents, keyless, when SEARCH_ENDPOINT is configured."""
    if not settings.search_endpoint or credential is None:
        return None
    from .documents import SEARCH_SCOPE, AzureDocumentSearch

    return AzureDocumentSearch(settings.search_endpoint, settings.search_index,
                               get_bearer_token_provider(credential, SEARCH_SCOPE))


def build_server(
    settings: Settings,
    model: ChatModel | None = None,
):
    """Build, but do not start, the Responses-compatible Hosted Agent server."""

    tools = list(DEFAULT_TOOLS)
    if settings.notion_mcp_enabled and settings.notion_backend == "direct" and settings.notion_oauth_callback_url:
        from langchain_azure_ai.agents.hosting import FoundryCheckpointSaver
        from .oauth_runtime import build_oauth_service
        from .tools.notion_chat import build_direct_chat_graph
        from .tools.notion_foundry import toolbox_loader

        oauth = build_oauth_service(settings.notion_oauth_callback_url, settings.notion_oauth_store_url,
                                    use_key_vault=True)
        checkpointer = (
            FoundryCheckpointSaver(endpoint=settings.foundry_project_endpoint, user_isolation=True)
            if settings.foundry_project_endpoint else MemorySaver()
        )
        # One credential for the whole process: tokens are cached and refreshed by it, instead of
        # being requested again for every model client and toolbox load.
        credential = DefaultAzureCredential() if model is None else None
        token_provider = get_bearer_token_provider(credential, MODEL_TOKEN_SCOPE) if credential else None
        from .semantic_approval import SemanticApprovalGuardrail
        judge_model = model if model is not None else build_model(settings, (), guardrail=True,
                                                                  token_provider=token_provider)
        approval_guardrail = SemanticApprovalGuardrail(judge_model, timeout=settings.semantic_approval_timeout)
        ssh_runner = ssh_judge = None
        if settings.ssh_enabled:
            from .tools.ssh import CommandJudge, SshRunner

            ssh_runner = SshRunner(settings)
            # Same isolated judge model as Notion consent, with its own instructions and verdicts.
            ssh_judge = CommandJudge(judge_model, timeout=settings.semantic_approval_timeout)
        graph = build_direct_chat_graph(
            settings,
            (lambda tools: model) if model is not None
            else (lambda tools: build_model(settings, tools, token_provider=token_provider)),
            checkpointer,
            oauth,
            guardrail=approval_guardrail,
            ssh_runner=ssh_runner,
            ssh_judge=ssh_judge,
            load_toolbox=toolbox_loader(settings, credential) if settings.toolbox_endpoint else None,
            document_search=_document_search(settings, credential),
            fast_model_factory=(
                (lambda tools: build_model(settings, tools, token_provider=token_provider, reasoning_effort="none"))
                if model is None and settings.model_fast_path else None
            ),
        )
        from .semantic_approval import ConversationalResponsesHostServer

        server = ConversationalResponsesHostServer(graph)
        from contextlib import asynccontextmanager

        lifespan = server.app.router.lifespan_context

        @asynccontextmanager
        async def oauth_lifespan(app):
            try:
                async with lifespan(app) as state:
                    yield state
            finally:
                close = getattr(oauth.store, "close", None)
                if close is not None:
                    await close()

        server.app.router.lifespan_context = oauth_lifespan
        return server
    if settings.toolbox_endpoint or (settings.notion_mcp_enabled and settings.notion_backend == "foundry"):
        from langchain_azure_ai.agents.hosting import FoundryCheckpointSaver
        from .tools.notion_foundry import build_foundry_graph

        graph = build_foundry_graph(
            settings,
            (lambda tools: model) if model is not None else (lambda tools: build_model(settings, tools)),
            FoundryCheckpointSaver(endpoint=settings.foundry_project_endpoint, user_isolation=True),
        )
        return ResponsesHostServer(graph)
    if settings.notion_mcp_enabled:
        from .tools.notion import load_notion_tools

        tools.extend(load_notion_tools(settings))
    if len({tool.name for tool in tools}) != len(tools):
        raise RuntimeError("Tool names must be unique across built-in and Notion tools.")

    graph = build_graph(
        model or build_model(settings, tools),
        tools=tools,
        checkpointer=MemorySaver() if settings.notion_mcp_enabled else None,
        approval_tool_names=(
            settings.notion_write_tool_names if settings.notion_mcp_enabled else ()
        ),
    )
    return ResponsesHostServer(graph)


def main() -> None:
    """Start the server required by the Foundry Hosted Agent runtime contract."""

    settings = Settings.from_env()
    build_server(settings).run(port=settings.port)


if __name__ == "__main__":
    main()
