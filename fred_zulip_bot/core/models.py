"""Pydantic models shared across the FastAPI application."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ZulipMessage(BaseModel):
    """Represents the Zulip message payload forwarded to the bot."""

    content: str
    display_recipient: Any
    sender_email: str
    subject: str
    type: str


class ChatRequest(BaseModel):
    """Incoming chat request containing the Zulip message and secret token."""

    message: ZulipMessage
    token: str


class ChatResponse(BaseModel):
    """Standard response for the `/chat` endpoint."""

    response_not_required: bool = True
