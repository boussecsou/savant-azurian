import pytest

from savant.config import Settings


def test_settings_reads_non_secret_azure_openai_configuration(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model.example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "sa2-gpt-6-luna")

    settings = Settings.from_env()

    assert settings.azure_openai_base_url == "https://model.example.openai.azure.com/openai/v1/"
    assert settings.model_deployment_name == "sa2-gpt-6-luna"


def test_settings_requires_azure_openai_endpoint_and_model_name(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.delenv("AZURE_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", raising=False)

    with pytest.raises(
        RuntimeError,
        match="AZURE_OPENAI_BASE_URL and AZURE_AI_MODEL_DEPLOYMENT_NAME",
    ):
        Settings.from_env()


def test_notion_is_disabled_by_default_and_reads_tool_allowlists(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model.example/openai/v1")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model")
    monkeypatch.delenv("NOTION_MCP_ENABLED", raising=False)
    monkeypatch.delenv("NOTION_READ_TOOL_NAMES", raising=False)
    monkeypatch.delenv("NOTION_WRITE_TOOL_NAMES", raising=False)

    settings = Settings.from_env()

    assert settings.notion_mcp_enabled is False
    assert settings.notion_read_tool_names == ()
    assert settings.notion_write_tool_names == ()


def test_settings_rejects_read_write_allowlist_overlap(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model.example/openai/v1")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model")
    monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
    monkeypatch.setenv("NOTION_READ_TOOL_NAMES", "search, update_page")
    monkeypatch.setenv("NOTION_WRITE_TOOL_NAMES", "update_page")

    with pytest.raises(RuntimeError, match="cannot be configured as both"):
        Settings.from_env()


def test_settings_rejects_invalid_notion_enabled_value(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model.example/openai/v1")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model")
    monkeypatch.setenv("NOTION_MCP_ENABLED", "sometimes")

    with pytest.raises(RuntimeError, match="NOTION_MCP_ENABLED must be a boolean"):
        Settings.from_env()


@pytest.mark.parametrize("version_path", ["", "/versions/2"])
def test_toolbox_endpoint_selects_exact_project_without_enabling_notion(monkeypatch, version_path):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model/openai/v1")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model")
    monkeypatch.setenv("NOTION_MCP_ENABLED", "false")
    endpoint = f"https://account.services.ai.azure.com/api/projects/project/toolboxes/lab{version_path}/mcp?api-version=v1"
    monkeypatch.setenv("TOOLBOX_ENDPOINT", endpoint)
    settings = Settings.from_env()
    assert settings.toolbox_endpoint == endpoint
    assert settings.foundry_project_endpoint == "https://account.services.ai.azure.com/api/projects/project"
    monkeypatch.setenv("TOOLBOX_ENDPOINT", endpoint.replace("https:", "http:"))
    with pytest.raises(RuntimeError, match="TOOLBOX_ENDPOINT"):
        Settings.from_env()
    monkeypatch.setenv("TOOLBOX_ENDPOINT", endpoint)
    monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
    with pytest.raises(RuntimeError, match="either"):
        Settings.from_env()


def chat_env(monkeypatch):
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model")
    monkeypatch.setenv("NOTION_MCP_ENABLED", "true")
    monkeypatch.setenv("NOTION_BACKEND", "direct")
    monkeypatch.setenv("NOTION_OWNER_ID", "trusted-owner")
    monkeypatch.setenv("NOTION_OAUTH_CALLBACK_URL", "https://callback.example/oauth/notion/callback")
    monkeypatch.setenv("NOTION_OAUTH_STORE_URL", "https://storage.blob.core.windows.net/private/oauth.enc")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://project")
    monkeypatch.delenv("NOTION_LOCAL_USER_ID", raising=False)


def test_chat_oauth_can_coexist_with_toolbox(monkeypatch):
    chat_env(monkeypatch)
    monkeypatch.setenv("TOOLBOX_ENDPOINT", "https://account.services.ai.azure.com/api/projects/project/toolboxes/lab/mcp?api-version=v1")
    settings = Settings.from_env()
    assert settings.notion_backend == "direct"
    assert settings.notion_oauth_store_url.endswith("oauth.enc")


@pytest.mark.parametrize("name,value,error", [
    ("NOTION_OAUTH_CALLBACK_URL", "http://public.example/oauth/notion/callback", "CALLBACK_URL"),
    ("NOTION_OAUTH_CALLBACK_URL", "https://callback.example/wrong", "CALLBACK_URL"),
    ("NOTION_LOCAL_USER_ID", "shared-user", "LOCAL_USER_ID"),
    ("NOTION_OAUTH_STORE_URL", "sqlite:///tmp/oauth.db", "shared"),
    ("NOTION_MCP_URL", "https://attacker.example/mcp", "official"),
    ("NOTION_BACKEND", "foundry", "direct"),
])
def test_chat_oauth_rejects_unsafe_configuration(monkeypatch, name, value, error):
    chat_env(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=error):
        Settings.from_env()


def test_document_search_is_optional_and_validated(monkeypatch):
    import pytest as _pytest
    from savant.config import Settings as _Settings
    monkeypatch.setattr("savant.config.load_dotenv", lambda **_: None)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://model/")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "m")
    monkeypatch.delenv("SEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("SEARCH_INDEX", raising=False)
    assert _Settings.from_env().search_endpoint == ""
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://ais-sa2.search.windows.net/")
    settings = _Settings.from_env()
    assert (settings.search_endpoint, settings.search_index) == ("https://ais-sa2.search.windows.net", "sa2-docs")
    for bad in ("http://ais-sa2.search.windows.net", "https://evil.example.com"):
        monkeypatch.setenv("SEARCH_ENDPOINT", bad)
        with _pytest.raises(RuntimeError, match="SEARCH_ENDPOINT"):
            _Settings.from_env()
