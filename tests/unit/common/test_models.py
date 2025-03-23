import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from webhook_relay.common.models import QueueMessage, WebhookMetadata, WebhookPayload


class TestWebhookMetadata:

    def test_minimal_metadata(self):
        """Test that minimal metadata passes validation."""
        metadata = WebhookMetadata(source="github")
        assert metadata.source == "github"
        assert metadata.signature is None
        assert metadata.headers == {}
        assert isinstance(metadata.received_at, datetime)

    def test_full_metadata(self):
        """Test that complete metadata passes validation."""
        now = datetime.utcnow()
        headers = {"X-GitHub-Event": "push", "User-Agent": "GitHub-Hookshot/abcdef"}
        metadata = WebhookMetadata(
            source="github",
            received_at=now,
            signature="sha256=abc123",
            headers=headers,
        )
        assert metadata.source == "github"
        assert metadata.received_at == now
        assert metadata.signature == "sha256=abc123"
        assert metadata.headers == headers

    def test_json_serialization(self):
        """Test that metadata can be serialized to JSON."""
        metadata = WebhookMetadata(
            source="github",
            signature="sha256=abc123",
            headers={"X-GitHub-Event": "push"},
        )
        # Use Pydantic's model_dump_json instead of manual JSON serialization
        json_str = metadata.model_dump_json()
        assert "github" in json_str
        assert "sha256=abc123" in json_str
        assert "X-GitHub-Event" in json_str

        # Ensure the datetime is properly serialized
        assert "received_at" in json_str
        # The datetime should be in ISO format which includes 'T' and 'Z' or '+' for timezone
        # We can check if the string contains typical datetime characters
        assert ":" in json_str  # Time separator
        assert "-" in json_str  # Date separator


class TestWebhookPayload:

    def test_minimal_payload(self):
        """Test that minimal payload passes validation."""
        metadata = WebhookMetadata(source="github")
        content = {"event": "test"}
        payload = WebhookPayload(metadata=metadata, content=content)
        assert payload.metadata == metadata
        assert payload.content == content

    def test_nested_content(self):
        """Test that payload with nested content passes validation."""
        metadata = WebhookMetadata(source="github")
        content = {
            "repository": {"name": "test-repo", "owner": "test-owner"},
            "commits": [
                {"id": "abc123", "message": "Test commit"},
                {"id": "def456", "message": "Another commit"},
            ],
        }
        payload = WebhookPayload(metadata=metadata, content=content)
        assert payload.metadata == metadata
        assert payload.content == content
        assert payload.content["repository"]["name"] == "test-repo"
        assert len(payload.content["commits"]) == 2

    def test_json_serialization(self):
        """Test that payload can be serialized to JSON."""
        metadata = WebhookMetadata(source="github")
        content = {"event": "test"}
        payload = WebhookPayload(metadata=metadata, content=content)

        # Use Pydantic's model_dump_json instead of manual JSON serialization
        json_str = payload.model_dump_json()
        assert "metadata" in json_str
        assert "content" in json_str
        assert "github" in json_str
        assert "test" in json_str

        # Check if datetime from metadata was properly serialized
        assert "received_at" in json_str


class TestQueueMessage:

    def test_minimal_message(self, sample_webhook_payload):
        """Test that minimal queue message passes validation."""
        message = QueueMessage(
            id="test-id",
            payload=sample_webhook_payload,
        )
        assert message.id == "test-id"
        assert message.payload == sample_webhook_payload
        assert message.attempts == 0
        assert isinstance(message.created_at, datetime)

    def test_full_message(self, sample_webhook_payload):
        """Test that complete queue message passes validation."""
        now = datetime.utcnow()
        message = QueueMessage(
            id="test-id",
            payload=sample_webhook_payload,
            created_at=now,
            attempts=3,
        )
        assert message.id == "test-id"
        assert message.payload == sample_webhook_payload
        assert message.created_at == now
        assert message.attempts == 3

    def test_json_serialization(self, sample_webhook_payload):
        """Test that queue message can be serialized to JSON."""
        message = QueueMessage(
            id="test-id",
            payload=sample_webhook_payload,
        )
        # Use Pydantic's model_dump_json instead of manual JSON serialization
        json_str = message.model_dump_json()
        assert "test-id" in json_str
        assert "payload" in json_str
        assert "metadata" in json_str
        assert "content" in json_str
        assert "github" in json_str

        # Check if datetime was properly serialized
        assert "created_at" in json_str

    def test_json_roundtrip(self, sample_webhook_payload):
        """Test that queue message can be serialized and deserialized."""
        original = QueueMessage(
            id="test-id",
            payload=sample_webhook_payload,
            attempts=2,
        )
        # Use Pydantic's model_dump_json for serialization
        json_str = original.model_dump_json()
        data = json.loads(json_str)

        # Use Pydantic's model_validate for deserialization
        reconstructed = QueueMessage.model_validate(data)
        assert reconstructed.id == original.id
        assert reconstructed.attempts == original.attempts
        assert reconstructed.payload.metadata.source == original.payload.metadata.source
        assert reconstructed.payload.content == original.payload.content

        # Also verify datetime fields were properly serialized and deserialized
        assert isinstance(reconstructed.created_at, datetime)
        assert isinstance(reconstructed.payload.metadata.received_at, datetime)
