import os
import pytest
from pydantic import ValidationError

from webhook_relay.common.config import (
    AWSSQSConfig,
    BaseConfig,
    CollectorConfig,
    ForwarderConfig,
    GCPPubSubConfig,
    MetricsConfig,
    QueueType,
    WebhookSourceConfig,
)


class TestBaseConfig:
    
    def test_validate_queue_config_gcp(self, gcp_config):
        """Test that validate_queue_config passes with valid GCP config."""
        config = BaseConfig(queue_type=QueueType.GCP_PUBSUB, gcp_config=gcp_config)
        config.validate_queue_config()  # Should not raise an exception
    
    def test_validate_queue_config_aws(self, aws_config):
        """Test that validate_queue_config passes with valid AWS config."""
        config = BaseConfig(queue_type=QueueType.AWS_SQS, aws_config=aws_config)
        config.validate_queue_config()  # Should not raise an exception
    
    def test_validate_queue_config_missing_gcp(self):
        """Test that validate_queue_config raises an exception when GCP config is missing."""
        config = BaseConfig(queue_type=QueueType.GCP_PUBSUB)
        with pytest.raises(ValueError, match="GCP PubSub selected but no GCP configuration provided"):
            config.validate_queue_config()
    
    def test_validate_queue_config_missing_aws(self):
        """Test that validate_queue_config raises an exception when AWS config is missing."""
        config = BaseConfig(queue_type=QueueType.AWS_SQS)
        with pytest.raises(ValueError, match="AWS SQS selected but no AWS configuration provided"):
            config.validate_queue_config()
    
    def test_env_variables(self, monkeypatch):
        """Test that environment variables are correctly loaded."""
        monkeypatch.setenv("WEBHOOK_RELAY_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("WEBHOOK_RELAY_QUEUE_TYPE", "aws_sqs")
        monkeypatch.setenv("WEBHOOK_RELAY_AWS_CONFIG__REGION_NAME", "us-west-2")
        monkeypatch.setenv("WEBHOOK_RELAY_AWS_CONFIG__QUEUE_URL", "https://sqs.example.com/queue")
        
        config = BaseConfig()
        assert config.log_level == "DEBUG"
        assert config.queue_type == QueueType.AWS_SQS
        assert config.aws_config is not None
        assert config.aws_config.region_name == "us-west-2"
        assert config.aws_config.queue_url == "https://sqs.example.com/queue"


class TestGCPPubSubConfig:
    
    def test_valid_config(self):
        """Test that a valid GCP PubSub config passes validation."""
        config = GCPPubSubConfig(
            project_id="test-project",
            topic_id="test-topic",
        )
        assert config.project_id == "test-project"
        assert config.topic_id == "test-topic"
        assert config.subscription_id is None
    
    def test_with_subscription(self):
        """Test that a GCP PubSub config with subscription ID passes validation."""
        config = GCPPubSubConfig(
            project_id="test-project",
            topic_id="test-topic",
            subscription_id="test-subscription",
        )
        assert config.subscription_id == "test-subscription"


class TestAWSSQSConfig:
    
    def test_valid_config(self):
        """Test that a valid AWS SQS config passes validation."""
        config = AWSSQSConfig(
            region_name="us-west-2",
            queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/test-queue",
        )
        assert config.region_name == "us-west-2"
        assert config.queue_url == "https://sqs.us-west-2.amazonaws.com/123456789012/test-queue"
        assert config.access_key_id is None
        assert config.secret_access_key is None
        assert config.role_arn is None
    
    def test_with_credentials(self):
        """Test that an AWS SQS config with credentials passes validation."""
        config = AWSSQSConfig(
            region_name="us-west-2",
            queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/test-queue",
            access_key_id="test-access-key",
            secret_access_key="test-secret-key",
        )
        assert config.access_key_id == "test-access-key"
        assert config.secret_access_key == "test-secret-key"
    
    def test_with_role_arn(self):
        """Test that an AWS SQS config with role ARN passes validation."""
        config = AWSSQSConfig(
            region_name="us-west-2",
            queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/test-queue",
            role_arn="arn:aws:iam::123456789012:role/test-role",
        )
        assert config.role_arn == "arn:aws:iam::123456789012:role/test-role"


class TestMetricsConfig:
    
    def test_default_values(self):
        """Test that default values are set correctly."""
        config = MetricsConfig()
        assert config.enabled is True
        assert config.host == "127.0.0.1"  # Check the new default host value
        assert config.port == 9090
        assert config.path == "/metrics"
    
    def test_custom_values(self):
        """Test that custom values are set correctly."""
        config = MetricsConfig(
            enabled=False,
            host="0.0.0.0",  # Test with a custom host value
            port=8000,
            path="/custom-metrics",
        )
        assert config.enabled is False
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.path == "/custom-metrics"


class TestWebhookSourceConfig:
    
    def test_minimal_config(self):
        """Test that a minimal webhook source config passes validation."""
        config = WebhookSourceConfig(name="test-source")
        assert config.name == "test-source"
        assert config.secret is None
        assert config.signature_header is None
    
    def test_with_signature_verification(self):
        """Test that a webhook source config with signature verification passes validation."""
        config = WebhookSourceConfig(
            name="test-source",
            secret="test-secret",
            signature_header="X-Signature",
        )
        assert config.secret == "test-secret"
        assert config.signature_header == "X-Signature"


class TestCollectorConfig:
    
    def test_default_values(self):
        """Test that default values are set correctly."""
        config = CollectorConfig(
            queue_type=QueueType.GCP_PUBSUB,
            gcp_config=GCPPubSubConfig(
                project_id="test-project",
                topic_id="test-topic",
            ),
        )
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.log_level == "INFO"
        assert config.webhook_sources == []
    
    def test_with_webhook_sources(self, collector_config):
        """Test that webhook sources are parsed correctly."""
        assert len(collector_config.webhook_sources) == 3
        assert collector_config.webhook_sources[0].name == "github"
        assert collector_config.webhook_sources[0].secret == "test-secret"
        assert collector_config.webhook_sources[0].signature_header == "X-Hub-Signature-256"
        assert collector_config.webhook_sources[2].name == "custom"
        assert collector_config.webhook_sources[2].secret is None
        assert collector_config.webhook_sources[2].signature_header is None


class TestForwarderConfig:
    
    def test_required_values(self):
        """Test that required values are validated."""
        with pytest.raises(ValidationError):
            # Missing target_url
            ForwarderConfig(
                queue_type=QueueType.GCP_PUBSUB,
                gcp_config=GCPPubSubConfig(
                    project_id="test-project",
                    topic_id="test-topic",
                    subscription_id="test-subscription",
                ),
            )
    
    def test_default_values(self, forwarder_config):
        """Test that default values are set correctly."""
        assert forwarder_config.log_level == "INFO"
        assert forwarder_config.retry_attempts == 3
        assert forwarder_config.retry_delay == 1
        assert forwarder_config.timeout == 5
        assert forwarder_config.headers == {"X-Webhook-Relay": "true", "Authorization": "Bearer test-token"}