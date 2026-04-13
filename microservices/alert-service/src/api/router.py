"""API router combining all endpoint routers."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.endpoints import alerts, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(alerts.router)
