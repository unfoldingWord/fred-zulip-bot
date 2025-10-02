"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fred_zulip_bot.apps.api.routes.chat import register_chat_routes
from fred_zulip_bot.apps.api.routes.health import register_health_routes


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, title="fred-zulip-bot")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_chat_routes(app)
    register_health_routes(app)

    return app
