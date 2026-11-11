"""Minimal independently hosted OAuth return endpoint (no chat or tokens in HTML)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from savant.bff_api import ApiSettings, add_api
from savant.notion_oauth import NotionOAuth, OAuthError
from savant.workspace import WorkspaceService

logger = logging.getLogger("savant.bff")


def create_callback_app(
    service: NotionOAuth,
    api: tuple[ApiSettings, object] | None = None,
    workspace: WorkspaceService | None = None,
    documents=None,
) -> FastAPI:
    """`api` is (settings, async credential) when the owner-only PWA routes are enabled;
    `workspace` adds projects and sessions (Cosmos DB) to them."""

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            close = getattr(service.store, "close", None)
            if close is not None:
                await close()
            if workspace is not None:
                await workspace.close()
            if documents is not None:
                await documents.close()
            if api is not None:
                await api[1].close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/readiness")
    async def readiness():
        return {"status": "ready"}

    @app.get("/oauth/notion/callback", response_class=HTMLResponse)
    async def callback(state: str = "", code: str | None = None, error: str | None = None):
        try:
            await service.finish(state, code, error)
            logger.info("oauth_callback_completed")
            message = "Notion connected. Return to the same conversation and write “connected”."
            status = 200
        except OAuthError:
            logger.warning("oauth_callback_rejected")
            message = "Connection not completed, declined or expired. Ask for a new link in the chat."
            status = 400
        except Exception:
            logger.error("oauth_callback_failed")
            message = "Service temporarily unavailable. Try connecting again from the chat."
            status = 503
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Notion connection</title>'
            f"<body><p>{message}</p></body></html>",
            status_code=status,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    if api is not None:
        add_api(app, api[0], service, api[1], workspace=workspace, documents=documents)

    return app


def main():
    """Run separately from main.py; its callback must be browser-accessible."""
    import os

    import uvicorn
    from dotenv import load_dotenv

    from savant.bff_logging import LOGGING_CONFIG, configure_bff_logging
    from savant.oauth_key import oauth_azure_credential
    from savant.oauth_runtime import build_oauth_service

    configure_bff_logging()
    try:
        load_dotenv(override=False)
        callback_url = os.environ.get("NOTION_OAUTH_CALLBACK_URL", "").strip()
        store_url = os.environ.get("NOTION_OAUTH_STORE_URL", "").strip()
        service = build_oauth_service(callback_url, store_url)
        api_settings = ApiSettings.from_env()
        api = (api_settings, oauth_azure_credential(asynchronous=True)) if api_settings else None
        workspace = None
        if api_settings and api_settings.cosmos_endpoint:
            from savant.workspace_store import CosmosStore

            workspace = WorkspaceService(
                CosmosStore(api_settings.cosmos_endpoint, api[1], api_settings.cosmos_database)
            )
        documents = None
        if api_settings and api_settings.documents_account_url:
            from savant.document_library import AzureSearchIndex, BlobFiles, DocumentLibrary

            documents = DocumentLibrary(
                BlobFiles(api_settings.documents_account_url, api_settings.documents_container, api[1]),
                AzureSearchIndex(
                    api_settings.search_endpoint, api_settings.search_index, api_settings.search_indexer, api[1]
                ),
            )
        # Access logs contain OAuth codes in query strings; never enable them.
        uvicorn.run(
            create_callback_app(service, api, workspace, documents),
            host="0.0.0.0",
            port=int(os.environ.get("OAUTH_CALLBACK_PORT", "8090")),
            access_log=False,
            log_config=LOGGING_CONFIG,
        )
    except Exception:
        logger.error("bff_startup_failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
