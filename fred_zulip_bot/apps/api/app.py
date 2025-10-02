"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from fred_zulip_bot.adapters.history_repo.files_repo import FilesHistoryRepo
from fred_zulip_bot.adapters.mysql_client import MySqlClient
from fred_zulip_bot.adapters.zulip_client import ZulipClient
from fred_zulip_bot.apps.api.routes.chat import register_chat_routes
from fred_zulip_bot.apps.api.routes.health import register_health_routes
from fred_zulip_bot.services.chat_service import ChatService
from fred_zulip_bot.services.sql_service import SqlService
from logger import logger


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, title="fred-zulip-bot")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    services = _build_services()
    app.state.services = services
    app.state.logger = logger

    register_chat_routes(app)
    register_health_routes(app)

    return app


def _build_services() -> dict[str, Any]:
    base_history_dir = Path("./data/chat_histories")
    history_repo = FilesHistoryRepo(base_history_dir, logger=logger)
    sql_service = SqlService()

    if config.TEST_MODE:
        zulip_email = config.ZULIP_BOT_EMAIL_TEST or config.ZULIP_BOT_EMAIL
        zulip_token = config.ZULIP_BOT_TOKEN_TEST or config.ZULIP_BOT_TOKEN
        auth_token = config.ZULIP_AUTH_TOKEN_TEST or config.ZULIP_AUTH_TOKEN
    else:
        zulip_email = config.ZULIP_BOT_EMAIL
        zulip_token = config.ZULIP_BOT_TOKEN
        auth_token = config.ZULIP_AUTH_TOKEN

    zulip_client = ZulipClient(
        realm_url=config.ZULIP_SITE,
        email=zulip_email,
        api_key=zulip_token,
    )

    mysql_client = MySqlClient(
        host=config.DB_HOST,
        database=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        logger=logger,
    )

    chat_service = ChatService(
        zulip_client=zulip_client,
        history_repo=history_repo,
        mysql_client=mysql_client,
        sql_service=sql_service,
        auth_token=auth_token,
        logger=logger,
        api_key=config.GENAI_API_KEY,
    )

    return {
        "chat_service": chat_service,
        "history_repo": history_repo,
        "mysql_client": mysql_client,
        "zulip_client": zulip_client,
        "sql_service": sql_service,
    }
