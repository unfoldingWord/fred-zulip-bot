from __future__ import annotations

from typing import Any

from fred_zulip_bot.adapters.zulip_client import ZulipClient


def test_zulip_client_send_stream(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, data, auth, timeout):  # type: ignore[override]
        captured["url"] = url
        captured["data"] = data
        captured["auth"] = auth
        captured["timeout"] = timeout

    monkeypatch.setattr("fred_zulip_bot.adapters.zulip_client.requests.post", fake_post)

    client = ZulipClient(realm_url="https://example.com/", email="bot@example.com", api_key="key")

    client.send(
        to=["recipient@example.com"],
        msg_type="stream",
        subject="topic",
        content="hello",
        channel_name="general",
    )

    expected = {
        "url": "https://example.com/api/v1/messages",
        "data": {
            "type": "stream",
            "to": "general",
            "content": "hello",
            "subject": "topic",
        },
        "auth": ("bot@example.com", "key"),
        "timeout": 10,
    }
    assert captured == expected  # noqa: S101


def test_zulip_client_send_private(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, data, auth, timeout):  # type: ignore[override]
        captured.update({"data": data, "auth": auth})

    monkeypatch.setattr("fred_zulip_bot.adapters.zulip_client.requests.post", fake_post)

    client = ZulipClient(realm_url="https://example.com", email="bot@example.com", api_key="key")
    client.send(
        to=["user@example.com"],
        msg_type="private",
        subject="ignored",
        content="hi",
        channel_name="ignored",
    )

    expected = {
        "data": {"type": "private", "to": ["user@example.com"], "content": "hi"},
        "auth": ("bot@example.com", "key"),
    }
    assert captured == expected  # noqa: S101
