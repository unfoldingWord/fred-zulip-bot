from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from fred_zulip_bot.apps.api.routes.chat import register_chat_routes
from fred_zulip_bot.core.models import ChatRequest, ChatResponse


class StubChatService:
    def __init__(self) -> None:
        self.calls: list[ChatRequest] = []

    def handle_chat_request(
        self, request: ChatRequest, background_tasks: BackgroundTasks
    ) -> ChatResponse:
        self.calls.append(request)
        return ChatResponse()


def test_chat_route_invokes_service() -> None:
    app = FastAPI()
    stub = StubChatService()
    app.state.services = {"chat_service": stub}
    register_chat_routes(app)

    client = TestClient(app)

    payload = {
        "message": {
            "content": "hello",
            "display_recipient": "stream",
            "sender_email": "user@example.com",
            "subject": "topic",
            "type": "stream",
        },
        "token": "secret",
    }

    response = client.post("/chat", json=payload)

    assert response.status_code == 200  # noqa: S101
    assert stub.calls[0].message.content == "hello"  # noqa: S101
