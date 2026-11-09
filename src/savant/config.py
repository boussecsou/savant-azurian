"""Non-secret runtime configuration."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse
from dataclasses import dataclass

from dotenv import load_dotenv


NOTION_MCP_DEFAULT_URL = "https://mcp.notion.com/mcp"
# "" means: send nothing and keep the provider default.
REASONING_EFFORTS = frozenset({"", "minimal", "low", "medium", "high"})


def _env_names(name: str) -> tuple[str, ...]:
    """Parse a comma-separated list of MCP tool names."""

    return tuple(
        dict.fromkeys(
            value.strip()
            for value in os.environ.get(name, "").split(",")
            if value.strip()
        )
    )


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean (true/false).")


@dataclass(frozen=True)
class Settings:
    """Values supplied by the local environment or the Foundry host."""

    azure_openai_base_url: str
    model_deployment_name: str
    port: int = 8088
    notion_mcp_enabled: bool = False
    notion_mcp_url: str = NOTION_MCP_DEFAULT_URL
    notion_read_tool_names: tuple[str, ...] = ()
    notion_write_tool_names: tuple[str, ...] = ()
    notion_backend: str = "direct"
    notion_toolbox_name: str = "sa2-notion-tools"
    foundry_project_endpoint: str = ""
    toolbox_endpoint: str = ""
    notion_oauth_callback_url: str = ""
    notion_oauth_store_url: str = ""
    notion_local_user_id: str = ""
    notion_owner_id: str = ""
    notion_tool_policy: str = "dynamic"
    notion_identity_diagnostics: bool = False
    semantic_approval_model: str = ""
    semantic_approval_timeout: float = 10.0
    # Reasoning effort of the main chat model. "" leaves the provider default (medium for this
    # model family), which made a plain greeting take about 7 s.
    model_reasoning_effort: str = "low"
    # Bounded model calls: the SDK retries 408/429/5xx and network errors with backoff, at most this often.
    model_timeout: float = 90.0
    model_max_retries: int = 2
    # Fast path: a first tool-free call (no reasoning) answers simple turns in ~1.5 s and hands
    # anything that needs a tool to the full agent. MODEL_FAST_PATH=false turns it off.
    model_fast_path: bool = True
    # SSH tool: all of host, user, host key, vault URL and secret name, or none of them.
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_host_key: str = ""
    ssh_key_vault_url: str = ""
    ssh_key_secret_name: str = ""
    ssh_connect_timeout: float = 10.0
    ssh_command_timeout: float = 30.0
    # Document search (Azure AI Search, docs/search-documents.md): on when SEARCH_ENDPOINT is set.
    search_endpoint: str = ""
    search_index: str = "sa2-docs"

    @property
    def ssh_enabled(self) -> bool:
        return bool(self.ssh_host)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(override=False)
        base_url = os.environ.get("AZURE_OPENAI_BASE_URL", "").strip()
        model_name = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()
        if not base_url or not model_name:
            raise RuntimeError(
                "AZURE_OPENAI_BASE_URL and AZURE_AI_MODEL_DEPLOYMENT_NAME must be set "
                "before starting the Savant runtime."
            )

        port_value = os.environ.get("PORT", "8088")
        try:
            port = int(port_value)
        except ValueError as error:
            raise RuntimeError("PORT must be an integer.") from error

        notion_enabled = _env_bool("NOTION_MCP_ENABLED")
        identity_diagnostics = _env_bool("NOTION_IDENTITY_DIAGNOSTICS")
        backend = os.environ.get("NOTION_BACKEND", "direct").strip()
        toolbox_name = os.environ.get("NOTION_TOOLBOX_NAME", "sa2-notion-tools").strip()
        project_endpoint = (os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")).strip()
        toolbox_endpoint = os.environ.get("TOOLBOX_ENDPOINT", "").strip()
        callback_url = os.environ.get("NOTION_OAUTH_CALLBACK_URL", "").strip()
        store_url = os.environ.get("NOTION_OAUTH_STORE_URL", "").strip()
        local_user = os.environ.get("NOTION_LOCAL_USER_ID", "").strip()
        owner_id = os.environ.get("NOTION_OWNER_ID", "").strip()
        tool_policy = os.environ.get("NOTION_TOOL_POLICY", "dynamic").strip()
        if tool_policy not in {"dynamic", "allowlist"}:
            raise RuntimeError("NOTION_TOOL_POLICY must be dynamic or allowlist.")
        if toolbox_endpoint:
            parsed = urlparse(toolbox_endpoint)
            match = re.fullmatch(r"(/api/projects/[^/]+)/toolboxes/[^/]+(?:/versions/[^/]+)?/mcp", parsed.path)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or not match or parsed.query != "api-version=v1":
                raise RuntimeError("TOOLBOX_ENDPOINT must be an HTTPS Foundry MCP endpoint with api-version=v1.")
            project_endpoint = f"https://{parsed.netloc}{match[1]}"
            if notion_enabled and not (backend == "direct" and callback_url):
                raise RuntimeError("Configure either TOOLBOX_ENDPOINT or NOTION_MCP_ENABLED, not both.")
        if backend not in {"direct", "foundry"}:
            raise RuntimeError("NOTION_BACKEND must be direct or foundry.")
        if callback_url:
            if notion_enabled and backend != "direct":
                raise RuntimeError("Chat OAuth requires NOTION_BACKEND=direct.")
            callback = urlparse(callback_url)
            local_callback = callback.hostname in {"localhost", "127.0.0.1", "::1"}
            if (callback.scheme != "https" and not (callback.scheme == "http" and local_callback)) or not callback.hostname or callback.username or callback.password or callback.query or callback.fragment or callback.path != "/oauth/notion/callback":
                raise RuntimeError("NOTION_OAUTH_CALLBACK_URL must be HTTPS with path /oauth/notion/callback (HTTP loopback is allowed locally).")
            if not store_url:
                raise RuntimeError("NOTION_OAUTH_STORE_URL is required for chat OAuth.")
            if local_user and not local_callback:
                raise RuntimeError("NOTION_LOCAL_USER_ID is only allowed with a loopback callback.")
            if os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT") and local_callback:
                raise RuntimeError("A cloud Hosted Agent cannot use a loopback OAuth callback.")
            if notion_enabled and not local_callback and not owner_id:
                raise RuntimeError("NOTION_OWNER_ID is required for single-owner cloud OAuth.")
            if not local_callback and not store_url.startswith("https://"):
                raise RuntimeError("Cloud chat OAuth requires shared HTTPS Blob storage.")
            if notion_enabled and not local_callback and not project_endpoint:
                raise RuntimeError("Cloud chat OAuth requires FOUNDRY_PROJECT_ENDPOINT for durable conversations.")
        if notion_enabled and backend == "foundry" and (not project_endpoint or not toolbox_name):
            raise RuntimeError("Foundry Notion requires a project endpoint and NOTION_TOOLBOX_NAME.")
        notion_url = os.environ.get("NOTION_MCP_URL", NOTION_MCP_DEFAULT_URL).strip()
        if callback_url and notion_url != NOTION_MCP_DEFAULT_URL:
            raise RuntimeError("Chat OAuth must use the official Notion MCP endpoint.")
        read_tool_names = _env_names("NOTION_READ_TOOL_NAMES")
        write_tool_names = _env_names("NOTION_WRITE_TOOL_NAMES")

        if notion_enabled and not notion_url:
            raise RuntimeError("NOTION_MCP_URL must not be empty when Notion MCP is enabled.")
        if set(read_tool_names) & set(write_tool_names):
            raise RuntimeError(
                "A Notion MCP tool cannot be configured as both read and write."
            )

        approval_model = os.environ.get("SEMANTIC_APPROVAL_MODEL", "").strip()
        try:
            approval_timeout = float(os.environ.get("SEMANTIC_APPROVAL_TIMEOUT", "10"))
        except ValueError as error:
            raise RuntimeError("SEMANTIC_APPROVAL_TIMEOUT must be a number.") from error
        if not 0 < approval_timeout <= 30:
            raise RuntimeError("SEMANTIC_APPROVAL_TIMEOUT must be between 0 and 30 seconds.")

        reasoning_effort = os.environ.get("MODEL_REASONING_EFFORT", "low").strip().lower()
        if reasoning_effort not in REASONING_EFFORTS:
            raise RuntimeError(
                "MODEL_REASONING_EFFORT must be one of: "
                + ", ".join(repr(value) for value in sorted(REASONING_EFFORTS)) + "."
            )

        ssh = _ssh_settings()
        try:
            model_timeout = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "90"))
            model_max_retries = int(os.environ.get("MODEL_MAX_RETRIES", "2"))
        except ValueError as error:
            raise RuntimeError("MODEL_TIMEOUT_SECONDS and MODEL_MAX_RETRIES must be numbers.") from error
        if not 0 < model_timeout <= 240 or not 0 <= model_max_retries <= 5:
            raise RuntimeError("MODEL_TIMEOUT_SECONDS must be in (0, 240] and MODEL_MAX_RETRIES in [0, 5].")

        fast_path = os.environ.get("MODEL_FAST_PATH", "true").strip().lower()
        if fast_path not in {"true", "false"}:
            raise RuntimeError("MODEL_FAST_PATH must be true or false.")

        return cls(
            azure_openai_base_url=base_url.rstrip("/") + "/",
            model_deployment_name=model_name,
            port=port,
            notion_mcp_enabled=notion_enabled,
            notion_mcp_url=notion_url,
            notion_read_tool_names=read_tool_names,
            notion_write_tool_names=write_tool_names,
            notion_backend=backend,
            notion_toolbox_name=toolbox_name,
            foundry_project_endpoint=project_endpoint,
            toolbox_endpoint=toolbox_endpoint,
            notion_oauth_callback_url=callback_url,
            notion_oauth_store_url=store_url,
            notion_local_user_id=local_user,
            notion_owner_id=owner_id,
            notion_tool_policy=tool_policy,
            notion_identity_diagnostics=identity_diagnostics,
            semantic_approval_model=approval_model,
            semantic_approval_timeout=approval_timeout,
            model_reasoning_effort=reasoning_effort,
            model_timeout=model_timeout,
            model_max_retries=model_max_retries,
            model_fast_path=fast_path == "true",
            **ssh,
            **_search_settings(),
        )


def _search_settings() -> dict:
    """Document search: an Azure AI Search endpoint (keyless) and an index name, or nothing."""

    endpoint = os.environ.get("SEARCH_ENDPOINT", "").strip().rstrip("/")
    index = os.environ.get("SEARCH_INDEX", "sa2-docs").strip()
    if not endpoint:
        return {}
    if not re.fullmatch(r"https://[a-z0-9][a-z0-9-]{0,59}\.search\.windows\.net", endpoint):
        raise RuntimeError("SEARCH_ENDPOINT must be https://<service>.search.windows.net.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,127}", index):
        raise RuntimeError("SEARCH_INDEX must be an Azure AI Search index name.")
    return {"search_endpoint": endpoint, "search_index": index}


_SSH_REQUIRED = ("SSH_HOST", "SSH_USER", "SSH_HOST_KEY", "SSH_KEY_VAULT_URL", "SSH_KEY_SECRET_NAME")


def _ssh_settings() -> dict:
    """Validate the SSH tool configuration: all required values or none."""

    values = {name: os.environ.get(name, "").strip() for name in _SSH_REQUIRED}
    if not any(values.values()):
        return {}
    if not all(values.values()):
        raise RuntimeError("SSH configuration is partial: " + ", ".join(_SSH_REQUIRED) + " must all be set.")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", values["SSH_HOST"]):
        raise RuntimeError("SSH_HOST must be a host name or IP address.")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", values["SSH_USER"]):
        raise RuntimeError("SSH_USER must be a Unix account name.")
    key_parts = values["SSH_HOST_KEY"].split()
    if len(key_parts) < 2 or not key_parts[0].startswith(("ssh-", "ecdsa-")):
        raise RuntimeError("SSH_HOST_KEY must be a public host key line such as 'ssh-ed25519 AAAA...'.")
    vault = urlparse(values["SSH_KEY_VAULT_URL"])
    if (vault.scheme != "https" or not vault.hostname or not vault.hostname.endswith(".vault.azure.net")
            or vault.netloc != vault.hostname or vault.path not in {"", "/"} or vault.query or vault.fragment):
        raise RuntimeError("SSH_KEY_VAULT_URL must be an HTTPS Azure Key Vault URL.")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", values["SSH_KEY_SECRET_NAME"]):
        raise RuntimeError("SSH_KEY_SECRET_NAME must name a Key Vault secret.")
    try:
        port = int(os.environ.get("SSH_PORT", "22"))
        connect = float(os.environ.get("SSH_CONNECT_TIMEOUT", "10"))
        command = float(os.environ.get("SSH_COMMAND_TIMEOUT", "30"))
    except ValueError as error:
        raise RuntimeError("SSH_PORT and the SSH timeouts must be numbers.") from error
    if not 0 < port < 65536 or not 0 < connect <= 60 or not 0 < command <= 120:
        raise RuntimeError("SSH_PORT or an SSH timeout is out of range.")
    return {"ssh_host": values["SSH_HOST"], "ssh_port": port, "ssh_user": values["SSH_USER"],
            "ssh_host_key": " ".join(key_parts[:2]), "ssh_key_vault_url": values["SSH_KEY_VAULT_URL"],
            "ssh_key_secret_name": values["SSH_KEY_SECRET_NAME"],
            "ssh_connect_timeout": connect, "ssh_command_timeout": command}
