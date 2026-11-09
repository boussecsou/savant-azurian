"""CosmosStore against a fake Cosmos client: partition keys, system fields and double deletes."""
import asyncio

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

import azure.cosmos.aio as cosmos_aio
from savant.bff_api import ApiSettings
from savant.workspace_store import CosmosStore
from test_bff_api import OBJECT_ID, OWNER, AGENT_URL


class FakeContainer:
    def __init__(self, name):
        self.name, self.items, self.calls = name, {}, []

    def query_items(self, query, **kwargs):
        self.calls.append(("query", query, kwargs.get("partition_key")))
        values = [{**item, "_rid": "x", "_etag": "y", "_ts": 1} for item in self.items.values()]
        if "WHERE c.id" in query:
            values = [v for v in values if v["id"] == kwargs["parameters"][0]["value"]]
        if "WHERE c.sessionId" in query:
            values = [v for v in values if v["sessionId"] == kwargs["parameters"][0]["value"]]

        async def gen():
            for value in values:
                yield value
        return gen()

    async def upsert_item(self, item):
        self.items[item["id"]] = item

    async def delete_item(self, item, partition_key):
        self.calls.append(("delete", item, partition_key))
        if item not in self.items:
            raise CosmosResourceNotFoundError(message="gone")
        del self.items[item]


class FakeClient:
    containers = {}

    def __init__(self, endpoint, credential=None):
        self.endpoint, self.credential, self.closed = endpoint, credential, False

    def get_database_client(self, name):
        assert name == "sa2"
        client = self

        class Database:
            def get_container_client(self, container):
                return FakeClient.containers.setdefault(container, FakeContainer(container))
        return Database()

    async def close(self):
        self.closed = True


@pytest.fixture
def store(monkeypatch):
    FakeClient.containers = {}
    monkeypatch.setattr(cosmos_aio, "CosmosClient", FakeClient)
    return CosmosStore("https://cosmos-db-sa2.documents.azure.com:443/", object())


def test_system_fields_never_leave_the_store(store):
    async def scenario():
        await store.put_project({"id": "p", "name": "P"})
        return await store.projects()
    assert asyncio.run(scenario()) == [{"id": "p", "name": "P"}]


def test_messages_are_read_and_deleted_by_their_session_partition(store):
    async def scenario():
        await store.put_session({"id": "s1", "projectId": "main"})
        await store.put_messages("s1", [{"id": "m1", "at": 1}, {"id": "m2", "at": 2}])
        await store.put_messages("s2", [{"id": "m3", "at": 3}])
        assert [m["id"] for m in await store.messages("s1")] == ["m1", "m2"]
        await store.delete_session("s1")
        await store.delete_session("s1")  # already gone: not an error
    asyncio.run(scenario())
    messages = FakeClient.containers["messages"]
    assert set(messages.items) == {"m3"}
    assert ("delete", "m1", "s1") in messages.calls
    assert ("query", "SELECT * FROM c WHERE c.sessionId = @id ORDER BY c.at", "s1") in messages.calls
    assert ("delete", "s1", "s1") in FakeClient.containers["sessions"].calls


def test_close_closes_the_client(store):
    asyncio.run(store.close())
    assert store._client.closed


def env(monkeypatch, **values):
    for key, value in {"NOTION_OWNER_ID": OWNER, "AGENT_RESPONSES_URL": AGENT_URL,
                       "BFF_OWNER_OBJECT_ID": OBJECT_ID, **values}.items():
        monkeypatch.setenv(key, value)


def test_cosmos_settings_default_off_and_accept_only_an_azure_account_origin(monkeypatch):
    env(monkeypatch)
    assert ApiSettings.from_env().cosmos_endpoint == ""
    env(monkeypatch, COSMOS_ENDPOINT="https://cosmos-db-sa2.documents.azure.com:443/")
    settings = ApiSettings.from_env()
    assert (settings.cosmos_endpoint, settings.cosmos_database) == ("https://cosmos-db-sa2.documents.azure.com:443", "sa2")
    for bad in ("http://cosmos-db-sa2.documents.azure.com", "https://evil.example.com",
                "https://a.documents.azure.com/path", "https://u:p@a.documents.azure.com"):
        env(monkeypatch, COSMOS_ENDPOINT=bad)
        with pytest.raises(RuntimeError, match="COSMOS_ENDPOINT"):
            ApiSettings.from_env()
    env(monkeypatch, COSMOS_ENDPOINT="https://a.documents.azure.com", COSMOS_DATABASE="bad name!")
    with pytest.raises(RuntimeError, match="COSMOS_DATABASE"):
        ApiSettings.from_env()
