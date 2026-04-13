"""Tests for alert envelope model."""

from __future__ import annotations

import pytest

from src.core.models import AlertEnvelope


class TestAlertEnvelope:
    def test_from_raw_with_all_fields(self, sample_concealment_alert):
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)

        assert envelope.alert_type == "CONCEALMENT"
        assert envelope.metadata["poi_id"] == "person-001"
        assert envelope.metadata["camera_id"] == "cam-north-01"
        assert envelope.timestamp == "2025-01-15T10:30:00Z"
        assert envelope.payload == sample_concealment_alert

    def test_from_raw_missing_alert_type(self):
        envelope = AlertEnvelope.from_raw({"foo": "bar"})
        assert envelope.alert_type == "UNKNOWN"

    def test_from_raw_missing_metadata(self):
        envelope = AlertEnvelope.from_raw({"alert_type": "TEST"})
        assert envelope.metadata == {}

    def test_from_raw_auto_timestamp(self):
        envelope = AlertEnvelope.from_raw({"alert_type": "TEST"})
        assert envelope.timestamp is not None
        assert len(envelope.timestamp) > 0

    def test_to_dict(self, sample_concealment_alert):
        envelope = AlertEnvelope.from_raw(sample_concealment_alert)
        result = envelope.to_dict()

        assert result["alert_type"] == "CONCEALMENT"
        assert result["metadata"]["poi_id"] == "person-001"
        assert result["payload"] == sample_concealment_alert
