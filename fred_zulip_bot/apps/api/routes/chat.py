"""Chat endpoint wiring for the FastAPI application."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request

from fred_zulip_bot.core.models import ChatRequest, ChatResponse

if TYPE_CHECKING:
    from fred_zulip_bot.services.chat_service import ChatService

router: APIRouter = APIRouter()


def chat_endpoint(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
) -> ChatResponse:
    """Forward chat requests to the chat service."""

    chat_service = cast(
        "ChatService",
        http_request.app.state.services["chat_service"],
    )
    return chat_service.handle_chat_request(request, background_tasks)


def register_chat_routes(app: FastAPI) -> None:
    """Attach chat routes to the provided application."""

    router.add_api_route(
        "/chat",
        chat_endpoint,
        methods=["POST"],
        response_model=ChatResponse,
    )
    app.include_router(router)
