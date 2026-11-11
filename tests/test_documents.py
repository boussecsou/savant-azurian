"""Document search: the project is imposed by the server, results are outside data. No Azure call."""

import asyncio
import hashlib
import json
import time

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from savant import documents, spotlight
from savant.config import Settings
from savant.semantic_approval import request_project
from savant.tools.notion_chat import build_direct_chat_graph


@pytest.mark.parametrize("bad", ["", "a'b", "main' or project_id ne 'x", "x" * 65, None, "projet principal"])
def test_only_plain_ids_reach_the_filter(bad):
    with pytest.raises(ValueError):
        documents.project_filter(bad)
    assert request_project({"metadata": {"project_id": bad}}) is None


def test_filter_and_request_project():
    assert documents.project_filter("main") == "project_id eq 'main'"
    assert request_project({"metadata": {"project_id": "3f2a-b9.c:1"}}) == "3f2a-b9.c:1"
    assert request_project({}) is None and request_project({"metadata": "x"}) is None


def test_azure_query_is_hybrid_semantic_filtered_and_keyless():
    seen = []

    def provider(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "document_id": "d1",
                        "title": "plan.pdf",
                        "chunk": "long text " * 500,
                        "@search.captions": [{"text": "the caption"}],
                    },
                    {"document_id": "d2", "title": "notes.md", "chunk": "x" * 5000},
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            search = documents.AzureDocumentSearch(
                "https://ais-sa2.search.windows.net/", "sa2-docs", lambda: "token", client=client
            )
            return await search.search("budget", project_id="main")

    results = asyncio.run(run())
    body = json.loads(seen[0].content)
    assert seen[0].headers["Authorization"] == "Bearer token" and "api-key" not in seen[0].headers
    assert str(seen[0].url).startswith("https://ais-sa2.search.windows.net/indexes('sa2-docs')/docs/search")
    assert body["filter"] == "project_id eq 'main'" and body["queryType"] == "semantic"
    assert body["vectorQueries"][0] == {"kind": "text", "text": "budget", "fields": "chunk_vector", "k": 20}
    assert results[0] == {"document_id": "d1", "title": "plan.pdf", "passage": "the caption"}
    assert len(results[1]["passage"]) == documents.MAX_PASSAGE_CHARS


def test_a_throttled_search_is_a_transient_error():
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(503))
        async with httpx.AsyncClient(transport=transport) as client:
            search = documents.AzureDocumentSearch("https://s.search.windows.net", "i", lambda: "t", client=client)
            await search.search("q", project_id="main")

    with pytest.raises(httpx.HTTPStatusError) as caught:
        asyncio.run(run())
    from savant import reliability

    assert reliability.is_transient(caught.value)


# -- one call, several angles --------------------------------------------------------


def doc_id(seed):
    """A document id as the BFF makes them (32 hex characters)."""
    return hashlib.md5(seed.encode()).hexdigest()


SHARED = doc_id("shared")


class AngleSearch:
    """Each query finds its own passages, plus one passage every query finds."""

    def __init__(self):
        self.calls = []

    async def search(self, query, *, project_id, top=documents.MAX_RESULTS):
        self.calls.append(query)
        await asyncio.sleep(0.05)
        return [
            {"document_id": SHARED, "title": "guide.pdf", "passage": "found by all"},
            *(
                {"document_id": doc_id(f"{query}-{i}"), "title": f"{query}.pdf", "passage": f"{query} #{i}"}
                for i in range(top)
            ),
        ]


def run_tool(search, **arguments):
    tool = documents.build_search_tool(search, "main")
    return json.loads(asyncio.run(tool.ainvoke(arguments)))


def test_one_call_searches_every_angle_side_by_side_and_merges_without_duplicates():
    search = AngleSearch()
    started = time.perf_counter()
    out = run_tool(search, query="délais", more_queries=["relances", "erreurs"])
    elapsed = time.perf_counter() - started
    assert sorted(search.calls) == ["délais", "erreurs", "relances"]
    assert elapsed < 0.12  # three searches of 50 ms ran together, not one after the other
    passages = [r["passage"] for r in out["results"]]
    assert passages.count("found by all") == 1 and len(passages) == len(set(passages))
    # Every angle is represented, not only the first one.
    assert {"délais", "relances", "erreurs"} <= {r["title"].removesuffix(".pdf") for r in out["results"]}


def test_the_merged_answer_stays_bounded():
    out = run_tool(AngleSearch(), query="a", more_queries=["b", "c"])
    assert len(out["results"]) <= documents.MAX_MERGED_RESULTS


def test_a_single_query_still_works_as_before():
    search = AngleSearch()
    out = run_tool(search, query="délais")
    assert search.calls == ["délais"] and out["results"][0]["document_id"] == SHARED


def test_the_angles_are_limited_and_blank_ones_are_ignored():
    search = AngleSearch()
    with pytest.raises(Exception):  # noqa: B017 - the tool wrapper may raise any validation error
        run_tool(search, query="a", more_queries=["b", "c", "d", "e"])
    run_tool(search, query="a", more_queries=["  ", "a", "b"])
    assert sorted(search.calls) == ["a", "b"]  # blank and repeated angles cost nothing


def test_a_document_the_owner_cannot_see_is_never_cited():
    # A file dropped by hand (non-standard id) is not in the owner's list of sources: never a source.
    class Mixed:
        async def search(self, query, *, project_id, top=documents.MAX_RESULTS):
            return [
                {"document_id": "test-doc", "title": "savant-test.md", "passage": "hidden"},
                {"document_id": "", "title": "x.md", "passage": "no id"},
                {"document_id": SHARED, "title": "guide.pdf", "passage": "visible"},
            ]

    out = run_tool(Mixed(), query="sources")
    assert [r["title"] for r in out["results"]] == ["guide.pdf"]


def test_the_prompt_asks_for_one_grouped_call():
    assert "more_queries" in documents.INSTRUCTIONS


# -- graph integration -----------------------------------------------------------


class FakeSearch:
    def __init__(self, results=None):
        self.calls, self.results = [], results

    async def search(self, query, *, project_id, top=documents.MAX_RESULTS):
        self.calls.append((query, project_id))
        await asyncio.sleep(0.01)
        return (
            self.results
            if self.results is not None
            else [{"document_id": doc_id("savant-test"), "title": "savant-test.md", "passage": f"passage for {query}"}]
        )


class OAuth:
    async def get_access_token(self, user):
        return None

    async def begin(self, user):
        return "https://mcp.notion.com/authorize?state=x"


def graph_with(search, script, offered):
    queue = list(script)

    def factory(tools):
        offered.append({tool.name for tool in tools})

        class Model:
            async def ainvoke(self, messages):
                offered.append(messages[0].content)
                return queue.pop(0)

        return Model()

    return build_direct_chat_graph(
        Settings("https://model/", "m"),
        factory,
        MemorySaver(),
        OAuth(),
        identity_provider=lambda: "owner",
        document_search=search,
    )


def calls(*queries):
    return AIMessage(
        content="",
        tool_calls=[{"name": documents.TOOL_NAME, "args": {"query": q}, "id": f"s{i}"} for i, q in enumerate(queries)],
    )


def test_searches_use_the_request_project_run_side_by_side_and_come_back_as_outside_data():
    search, offered = FakeSearch(), []
    graph = graph_with(search, [calls("budget", "planning"), AIMessage(content="D'après savant-test.md…")], offered)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": ["Que disent mes documents ?"], "project_id": "main"}, {"configurable": {"thread_id": "t"}}
        )
    )
    assert sorted(search.calls) == [("budget", "main"), ("planning", "main")]
    assert documents.TOOL_NAME in offered[0] and "Project documents" in offered[1]
    tools = [m for m in result["messages"] if m.type == "tool"]
    assert len(tools) == 2 and all(spotlight.is_untrusted(m) for m in tools)
    assert "savant-test.md" in tools[0].content


def test_the_model_cannot_choose_the_project():
    search, offered = FakeSearch(), []
    sneaky = AIMessage(
        content="",
        tool_calls=[{"name": documents.TOOL_NAME, "id": "s", "args": {"query": "budget", "project_id": "other"}}],
    )
    graph = graph_with(search, [sneaky, AIMessage(content="ok")], offered)
    asyncio.run(graph.ainvoke({"messages": ["budget ?"], "project_id": "main"}, {"configurable": {"thread_id": "t"}}))
    # The extra argument is refused by the schema or ignored: never another project.
    assert all(project == "main" for _, project in search.calls)


def test_without_a_project_there_is_no_document_search():
    search, offered = FakeSearch(), []
    graph = graph_with(search, [AIMessage(content="Je n'ai pas de projet.")], offered)
    asyncio.run(graph.ainvoke({"messages": ["mes documents ?"]}, {"configurable": {"thread_id": "t"}}))
    assert documents.TOOL_NAME not in offered[0] and search.calls == []


def test_no_result_is_said_plainly():
    search, offered = FakeSearch(results=[]), []
    graph = graph_with(search, [calls("rien"), AIMessage(content="Rien trouvé.")], offered)
    result = asyncio.run(graph.ainvoke({"messages": ["x"], "project_id": "main"}, {"configurable": {"thread_id": "t"}}))
    tool = next(m for m in result["messages"] if m.type == "tool")
    assert "No passage" in tool.content
