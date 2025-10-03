"""Basic health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

router: APIRouter = APIRouter()


def health() -> dict[str, str]:
    """Return liveness status."""

    return {"status": "ok"}


def ready() -> dict[str, str]:
    """Return readiness status."""

    return {"status": "ready"}


def register_health_routes(app: FastAPI) -> None:
    """Attach health routes to the provided application."""

    router.add_api_route("/healthz", health, methods=["GET"])
    router.add_api_route("/ready", ready, methods=["GET"])
    app.include_router(router)
