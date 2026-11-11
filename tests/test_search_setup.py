"""Offline checks of the AI Search pipeline definitions: no credential, no request."""

import pytest

from scripts.search_setup import (
    CHUNK_CHARS,
    EXTENSIONS,
    config_from_env,
    datasource_definition,
    definitions,
    index_definition,
    indexer_definition,
    main,
    skillset_definition,
)

ENV = {
    "SEARCH_ENDPOINT": "https://ais-sa2.search.windows.net",
    "SEARCH_STORAGE_RESOURCE_ID": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/"
    "storageAccounts/stsavantazurian2",
    "SEARCH_EMBEDDING_ENDPOINT": "https://fp-savant-azurian-2-resource.services.ai.azure.com/",
    "SEARCH_EMBEDDING_DEPLOYMENT": "text-embedding-3-small",
}


def cfg(**overrides):
    return config_from_env({**ENV, **overrides})


def fields(index):
    return {field["name"]: field for field in index["fields"]}


def test_project_and_document_are_filterable_from_the_first_version():
    index = fields(index_definition(cfg()))
    # An existing field cannot be made filterable later: the isolation filter must exist from day one.
    assert index["project_id"]["filterable"] and index["document_id"]["filterable"]
    assert index["chunk_id"]["key"] and index["chunk_id"]["analyzer"] == "keyword"
    assert not index["chunk_vector"]["retrievable"]


def test_vector_field_skill_and_vectorizer_agree():
    c = cfg()
    index, skillset = index_definition(c), skillset_definition(c)
    embed = next(s for s in skillset["skills"] if s["name"] == "embed")
    assert fields(index)["chunk_vector"]["dimensions"] == embed["dimensions"] == 1536
    vectorizer = index["vectorSearch"]["vectorizers"][0]["azureOpenAIParameters"]
    assert vectorizer["deploymentId"] == embed["deploymentId"] and vectorizer["modelName"] == embed["modelName"]
    # Keyless: the search service uses its managed identity.
    assert "apiKey" not in vectorizer and "apiKey" not in embed
    assert vectorizer["resourceUri"] == "https://fp-savant-azurian-2-resource.services.ai.azure.com"


def test_every_chunk_carries_its_project_document_and_title():
    projection = skillset_definition(cfg())["indexProjections"]
    mapped = {m["name"]: m["source"] for m in projection["selectors"][0]["mappings"]}
    assert mapped["project_id"] == "/document/project_id"
    assert mapped["document_id"] == "/document/document_id"
    assert set(mapped) <= set(fields(index_definition(cfg())))
    assert projection["parameters"]["projectionMode"] == "skipIndexingParentDocuments"
    split = skillset_definition(cfg())["skills"][0]
    assert split["maximumPageLength"] == CHUNK_CHARS and split["pageOverlapLength"] < CHUNK_CHARS


def test_the_pipeline_is_wired_by_name_and_keyless():
    c = cfg(SEARCH_INDEX="sa2-test")
    names = [body["name"] for _, body in definitions(c)]
    assert names == ["sa2-test", "sa2-test-blob", "sa2-test-skillset", "sa2-test-indexer"]
    indexer = indexer_definition(c)
    assert (indexer["dataSourceName"], indexer["skillsetName"], indexer["targetIndexName"]) == tuple(names[1:3]) + (
        "sa2-test",
    )
    source = datasource_definition(c)
    assert source["credentials"]["connectionString"].startswith("ResourceId=/subscriptions/")
    assert "AccountKey" not in str(source)
    assert indexer["parameters"]["configuration"]["indexedFileNameExtensions"] == ",".join(EXTENSIONS)


@pytest.mark.parametrize(
    "name,value",
    [
        ("SEARCH_ENDPOINT", "http://ais-sa2.search.windows.net"),
        ("SEARCH_STORAGE_RESOURCE_ID", "stsavantazurian2"),
        ("SEARCH_EMBEDDING_ENDPOINT", "https://westeurope.api.cognitive.microsoft.com"),
        ("SEARCH_EMBEDDING_DEPLOYMENT", ""),
        ("SEARCH_EMBEDDING_MODEL", "gpt-6-luna"),
    ],
)
def test_bad_configuration_fails_before_any_request(name, value):
    with pytest.raises(ValueError, match=name):
        cfg(**{name: value})


def test_without_apply_nothing_is_sent(monkeypatch, capsys):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("scripts.search_setup.apply", lambda c: pytest.fail("must not send"))
    assert main([]) == 0
    assert "Nothing was sent" in capsys.readouterr().out
