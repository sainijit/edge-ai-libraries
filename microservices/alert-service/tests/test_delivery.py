"""Tests for delivery handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.core.config import DeliveryTarget
from src.core.models import AlertEnvelope
from src.delivery.log import LogHandler
from src.delivery.mqtt import MqttHandler
from src.delivery.registry import get_handler
from src.delivery.webhook import WebhookHandler


class TestLogHandler:
    async def test_deliver_logs(self, sample_concealment_alert, caplog):
        """LogHandler writes ALERT DELIVERED to the application log."""
        handler = LogHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="log")

        with caplog.at_level("INFO"):
            await handler.deliver(envelope, target)

        assert "ALERT DELIVERED" in caplog.text
        assert "CONCEALMENT" in caplog.text


class TestWebhookHandler:
    async def test_deliver_success(self, sample_concealment_alert):
        """WebhookHandler posts JSON and succeeds on 200 response."""
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
        """WebhookHandler raises ValueError when URL is empty."""
        handler = WebhookHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="webhook", url="")

        with pytest.raises(ValueError, match="Webhook URL not configured"):
            await handler.deliver(envelope, target)


class TestMqttHandler:
    async def test_deliver_publishes(self, sample_concealment_alert):
        """MqttHandler publishes to the specified topic."""
        handler = MqttHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="mqtt", topic="alerts/concealment")

        mock_client = AsyncMock()
        mock_client.publish = AsyncMock()

        with patch("src.delivery.mqtt.aiomqtt.Client") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await handler.deliver(envelope, target)

            MockClient.assert_called_once()
            call_kwargs = MockClient.call_args[1]
            assert "hostname" in call_kwargs
            assert call_kwargs["port"] == 1883

            mock_client.publish.assert_called_once()
            topic_arg = mock_client.publish.call_args[0][0]
            assert topic_arg == "alerts/concealment"

    async def test_deliver_default_topic(self, sample_concealment_alert):
        """MqttHandler defaults topic to alerts/{alert_type}."""
        handler = MqttHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="mqtt")  # no topic set

        mock_client = AsyncMock()
        mock_client.publish = AsyncMock()

        with patch("src.delivery.mqtt.aiomqtt.Client") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await handler.deliver(envelope, target)

            topic_arg = mock_client.publish.call_args[0][0]
            assert topic_arg == "alerts/concealment"

    async def test_deliver_with_auth(self, sample_concealment_alert):
        """MqttHandler passes username and password when configured."""
        handler = MqttHandler()
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        target = DeliveryTarget(type="mqtt")

        mock_client = AsyncMock()
        mock_client.publish = AsyncMock()

        with patch("src.delivery.mqtt.aiomqtt.Client") as MockClient, \
             patch("src.delivery.mqtt.settings") as mock_settings:
            mock_settings.mqtt_broker = "broker.example.com"
            mock_settings.MQTT_PORT = 1883
            mock_settings.MQTT_USERNAME = "user"
            mock_settings.MQTT_PASSWORD = "pass"

            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await handler.deliver(envelope, target)

            call_kwargs = MockClient.call_args[1]
            assert call_kwargs["hostname"] == "broker.example.com"
            assert call_kwargs["username"] == "user"
            assert call_kwargs["password"] == "pass"


class TestDeliveryRegistry:
    def test_get_log_handler(self):
        """Registry returns a LogHandler for type 'log'."""
        handler = get_handler("log")
        assert isinstance(handler, LogHandler)

    def test_get_webhook_handler(self):
        """Registry returns a WebhookHandler for type 'webhook'."""
        handler = get_handler("webhook")
        assert isinstance(handler, WebhookHandler)

    def test_unknown_handler_raises(self):
        """Registry raises ValueError for an unknown handler type."""
        with pytest.raises(ValueError, match="Unknown delivery type"):
            get_handler("carrier_pigeon")
