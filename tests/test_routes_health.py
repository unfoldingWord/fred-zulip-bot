from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fred_zulip_bot.apps.api.routes.health import register_health_routes


def test_health_routes_return_ok() -> None:
    app = FastAPI()
    register_health_routes(app)
    client = TestClient(app)

    health_response = client.get("/healthz")
    ready_response = client.get("/ready")

    assert health_response.status_code == 200  # noqa: S101
    assert ready_response.status_code == 200  # noqa: S101
