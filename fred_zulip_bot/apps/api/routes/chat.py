"""Chat endpoint wiring for the FastAPI application."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, FastAPI

from fred_zulip_bot.core.models import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks) -> ChatResponse:
    """Forward chat requests to the legacy handler until services are extracted."""

    from fred_zulip_bot.legacy_app import handle_chat_request

    return handle_chat_request(request, background_tasks)


def register_chat_routes(app: FastAPI) -> None:
    """Attach chat routes to the provided application."""

    app.include_router(router)
