import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from webhook_relay.collector.routes import router
from webhook_relay.common.metrics import metrics


class TestWebhookRoutes:

    def test_health_check(self, collector_client):
        """Test the health check endpoint."""
        response = collector_client.get("/webhooks/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_receive_webhook_unknown_source(self, collector_client):
        """Test that receiving a webhook from an unknown source returns a 404."""
        response = collector_client.post(
            "/webhooks/unknown",
            json={"test": "data"},
            headers={"User-Agent": "test"},
        )
        assert response.status_code == 404
        assert "Unknown webhook source" in response.json()["detail"]

    def test_receive_webhook_no_signature(self, collector_client, mock_queue_client):
        """Test receiving a webhook with no signature verification."""
        # This uses the "custom" source from the fixture which has no signature verification
        payload = {"test": "data"}

        response = collector_client.post(
            "/webhooks/custom",
            json=payload,
            headers={"User-Agent": "test"},
        )

        assert response.status_code == 202
        assert "message_id" in response.json()

        # Check that the webhook was sent to the queue
        assert len(mock_queue_client.sent_messages) == 1
        message_id, message_payload = mock_queue_client.sent_messages[0]

        assert message_payload.metadata.source == "custom"
        assert message_payload.content == payload

        # Check that the metrics were updated
        with patch("prometheus_client.Counter.labels") as mock_labels:
            metrics.webhook_received_total.labels(source="custom").inc()
            mock_labels.assert_called_with(source="custom")

    def test_receive_webhook_missing_signature(self, collector_client):
        """Test that receiving a webhook missing a required signature returns a 400."""
        response = collector_client.post(
            "/webhooks/github",
            json={"test": "data"},
            headers={"User-Agent": "GitHub-Hookshot/abcdef"},
        )
        assert response.status_code == 400
        assert "Missing signature header" in response.json()["detail"]

    def test_receive_webhook_invalid_signature(
        self, collector_client, collector_config
    ):
        """Test that receiving a webhook with an invalid signature returns a 401."""
        # Get the GitHub source from the config
        github_source = next(
            src for src in collector_config.webhook_sources if src.name == "github"
        )

        payload = {"test": "data"}
        body = json.dumps(payload).encode()

        # Create an invalid signature
        invalid_signature = "sha256=invalid"

        response = collector_client.post(
            "/webhooks/github",
            json=payload,
            headers={
                "User-Agent": "GitHub-Hookshot/abcdef",
                "X-Hub-Signature-256": invalid_signature,
            },
        )

        assert response.status_code == 401
        assert "Invalid signature" in response.json()["detail"]

    def test_receive_webhook_valid_signature(
        self, collector_client, collector_config, mock_queue_client
    ):
        """Test receiving a webhook with a valid signature."""
        # Get the GitHub source from the config
        github_source = next(
            src for src in collector_config.webhook_sources if src.name == "github"
        )

        payload = {"test": "data"}
        body = json.dumps(payload).encode()

        # Create a valid signature
        digest = hmac.new(
            github_source.secret.encode(), body, hashlib.sha256
        ).hexdigest()
        valid_signature = f"sha256={digest}"

        response = collector_client.post(
            "/webhooks/github",
            content=body,
            headers={
                "User-Agent": "GitHub-Hookshot/abcdef",
                "Content-Type": "application/json",
                "X-Hub-Signature-256": valid_signature,
            },
        )

        assert response.status_code == 202
        assert "message_id" in response.json()

        # Check that the webhook was sent to the queue
        assert len(mock_queue_client.sent_messages) == 1
        message_id, message_payload = mock_queue_client.sent_messages[0]

        assert message_payload.metadata.source == "github"
        assert message_payload.content == payload
        assert message_payload.metadata.signature == valid_signature

    def test_receive_webhook_invalid_json(self, collector_client):
        """Test that receiving a webhook with invalid JSON returns a 400."""
        response = collector_client.post(
            "/webhooks/custom",
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert "Invalid JSON payload" in response.json()["detail"]

    def test_receive_webhook_queue_error(self, collector_client, mock_queue_client):
        """Test that a queue error returns a 500."""
        # Make the queue client raise an exception
        mock_queue_client._send_message_mock.side_effect = Exception("Queue error")

        response = collector_client.post(
            "/webhooks/custom",
            json={"test": "data"},
            headers={"User-Agent": "test"},
        )

        assert response.status_code == 500
        assert "Failed to queue webhook" in response.json()["detail"]
