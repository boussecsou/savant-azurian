"""Project documents in the BFF: rules, routes and the cited sources, with in-memory fakes. No Azure."""
import asyncio
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from savant import bff_api
from savant.bff_api import ApiSettings, add_api
from savant.document_library import DocumentError, DocumentLibrary, MAX_BYTES, clean_name
from savant.oauth_callback import create_callback_app
from savant.workspace import WorkspaceService
from test_bff_api import AGENT_URL, OBJECT_ID, OWNER, OWNER_HEADERS, Credential, easy_auth, service  # noqa: F401
from workspace_fakes import InMemoryStore


class FakeFiles:
    def __init__(self):
        self.blobs, self.log, self.clock = {}, [], 0

    async def list(self, prefix):
        return [{"name": n, "size": len(b["data"]), "last_modified": b["at"]}
                for n, b in self.blobs.items() if n.startswith(prefix)]

    async def upload(self, name, data, content_type, metadata):
        self.clock += 1
        self.blobs[name] = {"data": data, "type": content_type, "metadata": metadata, "at": self.clock}
        self.log.append(("upload", name))

    async def download(self, name):
        return self.blobs[name]["data"]

    async def delete(self, name):
        self.blobs.pop(name, None)
        self.log.append(("delete_file", name))

    async def close(self):
        pass


class FakeIndex:
    def __init__(self, files):
        self.files, self.chunks, self.runs, self.failures = files, {}, 0, set()
        # Indexer runs still in progress, as seen by successive status reads; `on_poll` lets a test act
        # like a run that writes chunks after a removal.
        self.busy_reads, self.on_poll = [], None

    def index_all(self):
        """What the indexer would do: chunks for every blob, tagged from its metadata."""
        for blob in self.files.blobs.values():
            meta = blob["metadata"]
            self.chunks[meta["document_id"]] = meta["project_id"]

    async def ready(self, project_id):
        return {doc for doc, project in self.chunks.items() if project == project_id}

    async def failed(self):
        return set(self.failures)

    async def delete_document(self, project_id, document_id):
        if self.chunks.get(document_id) == project_id:
            del self.chunks[document_id]
        self.files.log.append(("delete_chunks", document_id))

    async def run(self):
        self.runs += 1

    async def busy(self):
        if self.on_poll:
            self.on_poll()
        return self.busy_reads.pop(0) if self.busy_reads else False

    async def close(self):
        pass


def library():
    files = FakeFiles()
    return DocumentLibrary(files, FakeIndex(files)), files


def make(service, store=None):
    lib, files = library()
    workspace = WorkspaceService(store or InMemoryStore())
    app = create_callback_app(service)
    add_api(app, ApiSettings(OWNER, AGENT_URL, owner_object_id=OBJECT_ID), service, Credential(),
            httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
            workspace=workspace, documents=lib)
    return TestClient(app), lib, files


@pytest.mark.parametrize("raw,expected", [
    ("Plan.PDF", "Plan.pdf"), ("../../etc/notes.md", "notes.md"), ("C:\\Users\\a\\SDD-003.docx", "SDD-003.docx"),
    ("ré\u0000sumé.txt", "résumé.txt"),
])
def test_names_are_cleaned(raw, expected):
    assert clean_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "image.png", "script.exe", "noextension", ".pdf"])
def test_unsupported_or_empty_names_are_refused(raw):
    with pytest.raises(DocumentError):
        clean_name(raw)


def test_upload_lists_with_the_real_state_and_stays_in_its_project(service):
    client, lib, files = make(service)
    h = OWNER_HEADERS
    client.post("/api/projects", headers=h, json={"id": "p2", "name": "Cloud"})
    added = client.post("/api/projects/main/documents?name=SDD-003.pdf", headers=h, content=b"%PDF-1.7 voice")
    assert added.status_code == 201 and added.json()["state"] == "indexing" and lib.index.runs == 1
    doc = added.json()["id"]
    (name, blob), = files.blobs.items()
    assert name == f"main/{doc}/SDD-003.pdf" and blob["metadata"] == {"project_id": "main", "document_id": doc}
    assert blob["type"] == "application/pdf"
    assert client.get("/api/projects/main/documents", headers=h).json()[0]["state"] == "indexing"
    lib.index.index_all()
    listed = client.get("/api/projects/main/documents", headers=h).json()
    assert [(d["id"], d["name"], d["state"]) for d in listed] == [(doc, "SDD-003.pdf", "ready")]
    # Another project sees nothing of it, and cannot reach it by id.
    assert client.get("/api/projects/p2/documents", headers=h).json() == []
    assert client.get(f"/api/projects/p2/documents/{doc}/file", headers=h).status_code == 404
    assert client.delete(f"/api/projects/p2/documents/{doc}", headers=h).status_code == 404


def test_a_failed_file_is_shown_as_failed(service):
    client, lib, files = make(service)
    doc = client.post("/api/projects/main/documents?name=scan.pdf", headers=OWNER_HEADERS, content=b"%PDF").json()["id"]
    lib.index.failures = {f"main/{doc}/scan.pdf"}
    assert client.get("/api/projects/main/documents", headers=OWNER_HEADERS).json()[0]["state"] == "failed"


def test_file_is_served_inline_with_its_type(service):
    client, _, _ = make(service)
    doc = client.post("/api/projects/main/documents?name=notes été.md", headers=OWNER_HEADERS, content=b"# hi").json()["id"]
    response = client.get(f"/api/projects/main/documents/{doc}/file", headers=OWNER_HEADERS)
    assert response.status_code == 200 and response.content == b"# hi"
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "inline; filename*=UTF-8''notes%20%C3%A9t%C3%A9.md"


def test_removing_forgets_the_chunks_before_the_file(service):
    client, lib, files = make(service)
    doc = client.post("/api/projects/main/documents?name=a.txt", headers=OWNER_HEADERS, content=b"x").json()["id"]
    lib.index.index_all()
    assert client.delete(f"/api/projects/main/documents/{doc}", headers=OWNER_HEADERS).status_code == 200
    assert [entry[0] for entry in files.log] == ["upload", "delete_chunks", "delete_file"]
    assert files.blobs == {} and lib.index.chunks == {}


def test_listing_forgets_chunks_whose_file_is_gone(service):
    # An indexer run that was already reading the file writes its chunks after the delete: orphans.
    client, lib, files = make(service)
    doc = client.post("/api/projects/main/documents?name=a.txt", headers=OWNER_HEADERS, content=b"x").json()["id"]
    lib.index.index_all()
    files.blobs.clear()  # the file is gone, its chunks are not
    assert client.get("/api/projects/main/documents", headers=OWNER_HEADERS).json() == []
    assert lib.index.chunks == {}, doc


def test_forgetting_orphans_leaves_everything_else_alone(service):
    client, lib, files = make(service)
    h = OWNER_HEADERS
    client.post("/api/projects", headers=h, json={"id": "p2", "name": "Cloud"})
    kept = client.post("/api/projects/main/documents?name=b.txt", headers=h, content=b"y").json()["id"]
    other = client.post("/api/projects/p2/documents?name=c.txt", headers=h, content=b"z").json()["id"]
    lib.index.index_all()
    # An orphan, and a file never indexed: only the orphan goes; other projects are untouched.
    lib.index.chunks["0" * 32] = "main"
    files.blobs["main/" + "1" * 32 + "/new.txt"] = {"data": b"o", "type": "text/plain", "metadata": {}, "at": 9}
    client.get("/api/projects/main/documents", headers=h)
    assert set(lib.index.chunks) == {kept, other}


def test_a_file_the_list_cannot_show_is_never_searchable(service):
    # A file dropped by hand (non-standard id) is not in the owner's list: what Savant does not show, it
    # does not remember. Its chunks go; the file itself is left alone.
    client, lib, files = make(service)
    files.blobs["main/test-doc/savant-test.md"] = {"data": b"n", "type": "text/markdown", "metadata": {}, "at": 9}
    lib.index.chunks["test-doc"] = "main"
    assert client.get("/api/projects/main/documents", headers=OWNER_HEADERS).json() == []
    assert lib.index.chunks == {} and "main/test-doc/savant-test.md" in files.blobs


def test_after_a_removal_the_chunks_written_by_a_running_indexer_are_forgotten_too():
    lib, files = library()

    async def run():
        doc = (await lib.add("main", "a.txt", b"x"))["id"]
        lib.index.index_all()
        lib.index.busy_reads = [True, True, False]  # the run in progress ends after two status reads
        # That run had read the file before the removal and writes its chunks afterwards.
        lib.index.on_poll = lambda: lib.index.chunks.__setitem__(doc, "main")
        await lib.remove("main", doc)
        await lib.settle("main")
        lib.index.on_poll = None
        return doc

    lib.settle_interval = 0
    doc = asyncio.run(run())
    assert doc not in lib.index.chunks and files.blobs == {}


def test_a_failing_cleanup_does_not_break_the_list(service):
    client, lib, files = make(service)
    doc = client.post("/api/projects/main/documents?name=a.txt", headers=OWNER_HEADERS, content=b"x").json()["id"]
    lib.index.index_all()
    lib.index.chunks["f" * 32] = "main"  # an orphan whose deletion fails

    async def broken(project_id, document_id):
        raise RuntimeError("search is down")
    lib.index.delete_document = broken
    listed = client.get("/api/projects/main/documents", headers=OWNER_HEADERS)
    assert listed.status_code == 200 and [d["id"] for d in listed.json()] == [doc]


def test_deleting_a_project_deletes_its_documents(service):
    client, lib, files = make(service)
    h = OWNER_HEADERS
    client.post("/api/projects", headers=h, json={"id": "p2", "name": "Cloud"})
    client.post("/api/projects/p2/documents?name=a.txt", headers=h, content=b"x")
    kept = client.post("/api/projects/main/documents?name=b.txt", headers=h, content=b"y").json()["id"]
    lib.index.index_all()
    assert client.delete("/api/projects/p2", headers=h).status_code == 200
    assert list(lib.index.chunks) == [kept] and all(name.startswith("main/") for name in files.blobs)


def test_limits_and_unknown_projects(service):
    client, _, files = make(service)
    h = OWNER_HEADERS
    assert client.post("/api/projects/main/documents?name=big.pdf", headers=h,
                       content=b"x" * (MAX_BYTES + 1)).status_code == 413
    assert client.post("/api/projects/main/documents?name=photo.png", headers=h, content=b"x").status_code == 415
    assert client.post("/api/projects/main/documents?name=empty.txt", headers=h, content=b"").status_code == 422
    assert client.post("/api/projects/nope/documents?name=a.txt", headers=h, content=b"x").status_code == 404
    assert client.delete("/api/projects/main/documents/not-a-real-id", headers=h).status_code == 404
    assert files.blobs == {}


@pytest.mark.parametrize("method,path", [
    ("get", "/api/projects/main/documents"), ("post", "/api/projects/main/documents?name=a.txt"),
    ("delete", "/api/projects/main/documents/" + "0" * 32), ("get", "/api/projects/main/documents/" + "0" * 32 + "/file"),
])
def test_document_routes_fail_closed(service, method, path):
    client, _, files = make(service)
    kwargs = {"content": b"x"} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert getattr(client, method)(path, headers=easy_auth("11111111-2222-4333-8444-555555555555"),
                                   **kwargs).status_code == 403
    assert files.blobs == {}


def test_without_documents_configuration_the_routes_do_not_exist(service):
    app = create_callback_app(service)
    add_api(app, ApiSettings(OWNER, AGENT_URL, owner_object_id=OBJECT_ID), service, Credential(),
            workspace=WorkspaceService(InMemoryStore()))
    assert TestClient(app).get("/api/projects/main/documents", headers=OWNER_HEADERS).status_code == 404


def test_documents_settings(monkeypatch):
    monkeypatch.delenv("DOCUMENTS_ACCOUNT_URL", raising=False)
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://ais-sa2.search.windows.net")
    # The agent's variable alone never turns the BFF feature on, nor breaks its start.
    assert bff_api._documents_settings(True) == {}
    monkeypatch.setenv("DOCUMENTS_ACCOUNT_URL", "https://stsavantazurian2.blob.core.windows.net")
    assert bff_api._documents_settings(True)["search_indexer"] == "sa2-docs-indexer"
    with pytest.raises(RuntimeError, match="COSMOS"):
        bff_api._documents_settings(False)
    monkeypatch.setenv("DOCUMENTS_ACCOUNT_URL", "https://evil.example.com")
    with pytest.raises(RuntimeError, match="DOCUMENTS_ACCOUNT_URL"):
        bff_api._documents_settings(True)


# -- cited sources in the chat stream ---------------------------------------------


def lines(*events):
    async def gen():
        for event in events:
            yield "data: " + json.dumps(event)
    return gen()


def test_a_document_search_relays_only_the_cited_documents():
    passage = "SECRET passage text"
    output = ('<untrusted_data source="search_documents">\n' + json.dumps({"results": [
        {"document_id": "0" * 32, "title": "SDD-003.pdf", "passage": passage},
        {"document_id": "0" * 32, "title": "SDD-003.pdf", "passage": "again"},
        {"document_id": "bad id'", "title": "x", "passage": "y"},
        {"document_id": "test-doc", "title": "savant-test.md", "passage": passage}]}) + "\n</untrusted_data>")
    events = [
        {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "c1", "name": "search_documents"}},
        {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "c2", "name": "notion-fetch"}},
        {"type": "response.output_item.done", "item": {"type": "function_call_output", "call_id": "c2", "output": output}},
        {"type": "response.output_item.added", "item": {"type": "function_call_output", "call_id": "c1", "output": output}},
        {"type": "response.output_item.done", "item": {"type": "function_call_output", "call_id": "c1", "output": output}},
        {"type": "response.completed", "response": {"id": "resp_1"}},
    ]

    async def run():
        return [chunk async for chunk in bff_api._relay_events(lines(*events))]

    chunks = asyncio.run(run())
    sources = [json.loads(c[len("data: "):]) for c in chunks if '"sources"' in c]
    assert sources == [{"type": "sources", "id": "c1", "sources": [
        {"documentId": "0" * 32, "title": "SDD-003.pdf"}, {"documentId": "test-doc", "title": "savant-test.md"}]}]
    assert all(passage not in c for c in chunks)


def test_azure_index_deletes_by_filter_tolerates_a_running_indexer_and_reads_failures():
    from savant.document_library import AzureSearchIndex
    seen, doc, chunks = [], "a" * 32, ["k1", "k2"]

    def provider(request):
        seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.url.path.endswith("/docs/search"):
            return httpx.Response(200, json={"value": [{"chunk_id": k} for k in chunks]})
        if request.url.path.endswith("/docs/index"):
            chunks.clear()
        if request.url.path.endswith("/run"):
            return httpx.Response(409)
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"lastResult": {"errors": [{
                "key": f"localId=https://st.blob.core.windows.net/documents/main/{doc}/mon%20scan.pdf&documentKey=x",
                "errorMessage": "Could not extract"}]}})
        return httpx.Response(200, json={})

    class Token:
        async def get_token(self, scope):
            assert scope == "https://search.azure.com/.default"
            return type("T", (), {"token": "t"})()

    async def run():
        index = AzureSearchIndex("https://ais-sa2.search.windows.net", "sa2-docs", "sa2-docs-indexer", Token(),
                                 client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
        await index.delete_document("main", doc)
        await index.run()
        return await index.failed()

    failed = asyncio.run(run())
    search, delete = seen[0][2], seen[1][2]
    assert search["filter"] == f"project_id eq 'main' and document_id eq '{doc}'"
    assert delete == {"value": [{"@search.action": "delete", "chunk_id": "k1"},
                                {"@search.action": "delete", "chunk_id": "k2"}]}
    assert failed == {f"main/{doc}/mon scan.pdf"}


def test_azure_index_reads_whether_a_run_is_in_progress_and_forgets_hand_made_ids_safely():
    from savant.document_library import AzureSearchIndex
    seen, status = [], {"lastResult": {"status": "inProgress"}}

    def provider(request):
        seen.append((request.url.path, json.loads(request.content) if request.content else None))
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json=status)
        if request.url.path.endswith("/docs/search"):
            return httpx.Response(200, json={"value": []})
        return httpx.Response(200, json={})

    class Token:
        async def get_token(self, scope):
            return type("T", (), {"token": "t"})()

    async def run():
        index = AzureSearchIndex("https://ais-sa2.search.windows.net", "sa2-docs", "sa2-docs-indexer", Token(),
                                 client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
        first = await index.busy()
        status["lastResult"]["status"] = "success"
        second = await index.busy()
        await index.delete_document("main", "test-doc")
        with pytest.raises(DocumentError):
            await index.delete_document("main", "x' or project_id ne 'main")
        return first, second

    assert asyncio.run(run()) == (True, False)
    assert seen[-1][1]["filter"] == "project_id eq 'main' and document_id eq 'test-doc'"


def test_azure_index_reads_and_deletes_past_one_page_of_chunks():
    from savant.document_library import AzureSearchIndex
    doc, remaining = "a" * 32, [f"k{i}" for i in range(1003)]
    searches, deleted = [], []

    def provider(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/docs/search"):
            searches.append(body.get("skip", 0))
            page = remaining[body.get("skip", 0):body.get("skip", 0) + body["top"]]
            return httpx.Response(200, json={"value": [{"chunk_id": k, "document_id": doc} for k in page]})
        assert len(body["value"]) <= 1000
        for action in body["value"]:
            remaining.remove(action["chunk_id"])
            deleted.append(action["chunk_id"])
        return httpx.Response(200, json={})

    class Token:
        async def get_token(self, scope):
            return type("T", (), {"token": "t"})()

    async def run():
        index = AzureSearchIndex("https://ais-sa2.search.windows.net", "sa2-docs", "sa2-docs-indexer", Token(),
                                 client=httpx.AsyncClient(transport=httpx.MockTransport(provider)))
        assert await index.ready("main") == {doc}
        assert searches == [0, 1000]  # a second page was read
        await index.delete_document("main", doc)

    asyncio.run(run())
    assert remaining == [] and len(deleted) == 1003
