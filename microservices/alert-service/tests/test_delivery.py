"""Tests for delivery handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.core.config import DeliveryTarget
from src.core.models import AlertEnvelope
from src.delivery.log import LogHandler
from src.delivery.registry import get_handler
from src.delivery.webhook import WebhookHandler


class TestLogHandler:
    async def test_deliver_logs(self, sample_concealment_alert, caplog):
        handler = LogHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="log")

        with caplog.at_level("INFO"):
            await handler.deliver(envelope, target)

        assert "ALERT DELIVERED" in caplog.text
        assert "CONCEALMENT" in caplog.text


class TestWebhookHandler:
    async def test_deliver_success(self, sample_concealment_alert):
        handler = WebhookHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="webhook", url="http://test.local/hook")

        import httpx

        mock_response = httpx.Response(200, request=httpx.Request("POST", "http://test.local/hook"))

        with patch.object(handler, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get.return_value = mock_client

            await handler.deliver(envelope, target)
            mock_client.post.assert_called_once()

    async def test_deliver_no_url_raises(self, sample_concealment_alert):
        handler = WebhookHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="webhook", url="")

        with pytest.raises(ValueError, match="Webhook URL not configured"):
            await handler.deliver(envelope, target)


class TestDeliveryRegistry:
    def test_get_log_handler(self):
        handler = get_handler("log")
        assert isinstance(handler, LogHandler)

    def test_get_webhook_handler(self):
        handler = get_handler("webhook")
        assert isinstance(handler, WebhookHandler)

    def test_unknown_handler_raises(self):
        with pytest.raises(ValueError, match="Unknown delivery type"):
            get_handler("carrier_pigeon")
