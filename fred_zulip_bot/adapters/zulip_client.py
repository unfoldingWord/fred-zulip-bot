"""Zulip API client wrapper."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import requests


class ZulipClient:
    """Minimal wrapper around the Zulip messages API."""

    def __init__(self, realm_url: str, email: str, api_key: str) -> None:
        self._realm_url = realm_url.rstrip("/")
        self._email = email
        self._api_key = api_key

    def send(
        self,
        *,
        to: Iterable[str],
        msg_type: str,
        subject: str,
        content: str,
        channel_name: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "type": msg_type,
            "to": list(to),
            "content": content,
        }
        if msg_type == "stream":
            payload["subject"] = subject
            payload["to"] = channel_name

        requests.post(  # noqa: S113 - legacy behavior without explicit timeout
            f"{self._realm_url}/api/v1/messages",
            data=payload,
            auth=(self._email, self._api_key),
        )
