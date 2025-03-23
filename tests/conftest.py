import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from webhook_relay.collector.server import create_app
from webhook_relay.common.config import (
    AWSSQSConfig,
    CollectorConfig,
    ForwarderConfig,
    GCPPubSubConfig,
    QueueType,
)
from webhook_relay.common.models import QueueMessage, WebhookMetadata, WebhookPayload
from webhook_relay.common.queue import QueueClient


class MockQueueClient(QueueClient):
    """Mock implementation of QueueClient for testing."""

    def __init__(self):
        self.sent_messages = []
        self.available_messages = []
        self.deleted_messages = []

        # Create mocks that we can use to override behavior in tests
        self._send_message_mock = MagicMock(side_effect=self._send_message_impl)
        self._receive_message_mock = MagicMock(side_effect=self._receive_message_impl)
        self._delete_message_mock = MagicMock(side_effect=self._delete_message_impl)

    async def send_message(self, payload):
        """Implementation of abstract method that delegates to a mockable method."""
        return await self._send_message_mock(payload)

    async def receive_message(self):
        """Implementation of abstract method that delegates to a mockable method."""
        return await self._receive_message_mock()

    async def delete_message(self, message_id):
        """Implementation of abstract method that delegates to a mockable method."""
        return await self._delete_message_mock(message_id)

    async def _send_message_impl(self, payload):
        """Actual implementation for send_message."""
        message_id = f"mock-message-{len(self.sent_messages)}"
        self.sent_messages.append((message_id, payload))
        return message_id

    async def _receive_message_impl(self):
        """Actual implementation for receive_message."""
        if not self.available_messages:
            return None
        return self.available_messages.pop(0)

    async def _delete_message_impl(self, message_id):
        """Actual implementation for delete_message."""
        self.deleted_messages.append(message_id)
        return True

    def add_message_to_queue(self, message):
        """Helper method to add messages to the mock queue."""
        self.available_messages.append(message)


@pytest.fixture
def mock_queue_client():
    """Fixture that provides a mock queue client."""
    return MockQueueClient()


@pytest.fixture
def sample_webhook_payload():
    """Fixture that provides a sample webhook payload."""
    metadata = WebhookMetadata(
        source="github",
        headers={"X-GitHub-Event": "push"},
        signature="sha256=abc123",
    )
    content = {
        "repository": {"name": "test-repo", "full_name": "owner/test-repo"},
        "ref": "refs/heads/main",
        "commits": [
            {
                "id": "123456",
                "message": "Test commit",
                "author": {"name": "Test User", "email": "test@example.com"},
            }
        ],
    }
    return WebhookPayload(metadata=metadata, content=content)


@pytest.fixture
def sample_queue_message(sample_webhook_payload):
    """Fixture that provides a sample queue message."""
    return QueueMessage(
        id="test-message-id",
        payload=sample_webhook_payload,
        attempts=0,
    )


@pytest.fixture
def gcp_config():
    """Fixture that provides a sample GCP configuration."""
    return GCPPubSubConfig(
        project_id="test-project",
        topic_id="test-topic",
        subscription_id="test-subscription",
    )


@pytest.fixture
def aws_config():
    """Fixture that provides a sample AWS configuration."""
    return AWSSQSConfig(
        region_name="us-west-2",
        queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/test-queue",
    )


@pytest.fixture
def collector_config():
    """Fixture that provides a sample collector configuration."""
    return CollectorConfig(
        host="0.0.0.0",
        port=8000,
        log_level="INFO",
        queue_type=QueueType.GCP_PUBSUB,
        gcp_config=GCPPubSubConfig(
            project_id="test-project",
            topic_id="test-topic",
        ),
        webhook_sources=[
            {
                "name": "github",
                "secret": "test-secret",
                "signature_header": "X-Hub-Signature-256",
            },
            {
                "name": "gitlab",
                "secret": "test-secret",
                "signature_header": "X-Gitlab-Token",
            },
            {"name": "custom"},  # No signature verification
        ],
    )


@pytest.fixture
def forwarder_config():
    """Fixture that provides a sample forwarder configuration."""
    return ForwarderConfig(
        log_level="INFO",
        queue_type=QueueType.GCP_PUBSUB,
        gcp_config=GCPPubSubConfig(
            project_id="test-project",
            topic_id="test-topic",
            subscription_id="test-subscription",
        ),
        target_url="http://internal-service:8080/webhook",
        headers={"X-Webhook-Relay": "true", "Authorization": "Bearer test-token"},
        retry_attempts=3,
        retry_delay=1,
        timeout=5,
    )


@pytest.fixture
def collector_app(collector_config, mock_queue_client):
    """Fixture that provides a configured collector FastAPI app."""
    with patch("webhook_relay.collector.app.get_app_config") as mock_get_config, patch(
        "webhook_relay.collector.app.get_queue_client"
    ) as mock_get_queue:
        mock_get_config.return_value = collector_config
        mock_get_queue.return_value = mock_queue_client
        app = create_app(collector_config)
        yield app


@pytest.fixture
def collector_client(collector_app):
    """Fixture that provides a test client for the collector API."""
    return TestClient(collector_app)


# Define a fixture to provide an async event loop for testing asynchronous functions
@pytest.fixture
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
