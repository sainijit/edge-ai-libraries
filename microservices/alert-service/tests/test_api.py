"""Tests for the alert API endpoints."""

from __future__ import annotations

import asyncio

import pytest


class TestHealthEndpoint:
    async def test_health(self, app_client):
        response = await app_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestAlertIngestion:
    async def test_accept_concealment_alert(
        self, app_client, sample_concealment_alert
    ):
        response = await app_client.post(
            "/api/v1/alerts", json=sample_concealment_alert
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["alert_type"] == "CONCEALMENT"

    async def test_accept_loitering_alert(
        self, app_client, sample_loitering_alert
    ):
        response = await app_client.post(
            "/api/v1/alerts", json=sample_loitering_alert
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["alert_type"] == "LOITERING"

    async def test_accept_intrusion_alert(
        self, app_client, sample_intrusion_alert
    ):
        response = await app_client.post(
            "/api/v1/alerts", json=sample_intrusion_alert
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["alert_type"] == "INTRUSION"

    async def test_accept_unknown_alert_type(self, app_client):
        response = await app_client.post(
            "/api/v1/alerts",
            json={"alert_type": "UNKNOWN_TYPE", "metadata": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"

    async def test_accept_minimal_payload(self, app_client):
        response = await app_client.post(
            "/api/v1/alerts", json={"foo": "bar"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["alert_type"] == "UNKNOWN"

    async def test_duplicate_alert_still_accepted(
        self, app_client, sample_concealment_alert
    ):
        """API always returns accepted; dedup happens in the worker."""
        r1 = await app_client.post(
            "/api/v1/alerts", json=sample_concealment_alert
        )
        r2 = await app_client.post(
            "/api/v1/alerts", json=sample_concealment_alert
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
