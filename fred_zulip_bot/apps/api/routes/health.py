"""Basic health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

router = APIRouter()


@router.get("/healthz")
def health() -> dict[str, str]:
    """Return liveness status."""

    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, str]:
    """Return readiness status."""

    return {"status": "ready"}


def register_health_routes(app: FastAPI) -> None:
    """Attach health routes to the provided application."""

    app.include_router(router)
