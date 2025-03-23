import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from webhook_relay.common.config import AWSSQSConfig, GCPPubSubConfig, QueueType
from webhook_relay.common.models import QueueMessage
from webhook_relay.common.queue import (
    AWSSQSClient,
    GCPPubSubClient,
    QueueClient,
    create_queue_client,
)


class TestCreateQueueClient:
    
    def test_create_gcp_client(self, gcp_config):
        """Test creating a GCP Pub/Sub client."""
        with patch("webhook_relay.common.queue.GCPPubSubClient") as mock_client:
            client = create_queue_client(
                queue_type=QueueType.GCP_PUBSUB,
                gcp_config=gcp_config,
            )
            mock_client.assert_called_once_with(gcp_config)
    
    def test_create_aws_client(self, aws_config):
        """Test creating an AWS SQS client."""
        with patch("webhook_relay.common.queue.AWSSQSClient") as mock_client:
            client = create_queue_client(
                queue_type=QueueType.AWS_SQS,
                aws_config=aws_config,
            )
            mock_client.assert_called_once_with(aws_config)
    
    def test_missing_gcp_config(self):
        """Test that an exception is raised when GCP config is missing."""
        with pytest.raises(ValueError, match="GCP PubSub selected but no GCP configuration provided"):
            create_queue_client(queue_type=QueueType.GCP_PUBSUB)
    
    def test_missing_aws_config(self):
        """Test that an exception is raised when AWS config is missing."""
        with pytest.raises(ValueError, match="AWS SQS selected but no AWS configuration provided"):
            create_queue_client(queue_type=QueueType.AWS_SQS)
    
    def test_unsupported_queue_type(self):
        """Test that an exception is raised for unsupported queue types."""
        with pytest.raises(ValueError, match="Unsupported queue type"):
            create_queue_client(queue_type="unsupported")


class TestGCPPubSubClient:
    
    @pytest.fixture
    def mock_publisher(self):
        """Fixture that provides a mock Pub/Sub publisher client."""
        mock = MagicMock()
        mock.topic_path.return_value = "projects/test-project/topics/test-topic"
        mock.publish.return_value = MagicMock()
        mock.publish.return_value.result.return_value = "mock-message-id"
        return mock
    
    @pytest.fixture
    def mock_subscriber(self):
        """Fixture that provides a mock Pub/Sub subscriber client."""
        mock = MagicMock()
        mock.subscription_path.return_value = "projects/test-project/subscriptions/test-subscription"
        mock.pull.return_value = MagicMock(
            received_messages=[
                MagicMock(
                    message=MagicMock(
                        data=json.dumps({
                            "id": "test-message-id",
                            "payload": {
                                "metadata": {
                                    "source": "github",
                                    "received_at": "2023-01-01T00:00:00",
                                    "headers": {"X-GitHub-Event": "push"},
                                },
                                "content": {"event": "test"},
                            },
                            "created_at": "2023-01-01T00:00:00",
                            "attempts": 0,
                        }).encode("utf-8"),
                    ),
                    ack_id="test-ack-id",
                )
            ]
        )
        return mock
    
    @pytest.fixture
    def patch_pubsub(self, mock_publisher, mock_subscriber):
        """Fixture that patches the google.cloud.pubsub_v1 module."""
        # Create a mock pubsub module
        pubsub_mock = MagicMock()
        pubsub_mock.PublisherClient.return_value = mock_publisher
        pubsub_mock.SubscriberClient.return_value = mock_subscriber
        
        # Use patch.dict to replace google.cloud.pubsub_v1 in sys.modules
        with patch.dict("sys.modules", {"google.cloud.pubsub_v1": pubsub_mock}):
            # Import the client class after patching sys.modules
            from webhook_relay.common.queue import GCPPubSubClient
            yield GCPPubSubClient
    
    @pytest.mark.asyncio
    async def test_send_message(self, patch_pubsub, gcp_config, sample_webhook_payload, mock_publisher):
        """Test sending a message to GCP Pub/Sub."""
        # Patch uuid4 to return a predictable value
        with patch('uuid.uuid4', return_value=MagicMock(__str__=lambda self: "mock-message-id")):
            client = patch_pubsub(gcp_config)
            
            message_id = await client.send_message(sample_webhook_payload)
            
            # Check that the message ID matches our mock
            assert message_id == "mock-message-id"
            
            # Verify the publisher was called
            mock_publisher.publish.assert_called_once()
            args, kwargs = mock_publisher.publish.call_args
            assert args[0] == "projects/test-project/topics/test-topic"
            
            # Verify the published data contains the payload
            # The data is passed as the second positional argument
            published_data_bytes = args[1]  # Get the second positional argument
            assert isinstance(published_data_bytes, bytes)
            
            # Decode and parse the JSON
            published_data = json.loads(published_data_bytes.decode("utf-8"))
            assert "id" in published_data
            assert "payload" in published_data
            assert published_data["payload"]["metadata"]["source"] == "github"
    
    @pytest.mark.asyncio
    async def test_receive_message(self, patch_pubsub, gcp_config, mock_subscriber):
        """Test receiving a message from GCP Pub/Sub."""
        client = patch_pubsub(gcp_config)
        
        message = await client.receive_message()
        
        mock_subscriber.pull.assert_called_once_with(
            request={"subscription": "projects/test-project/subscriptions/test-subscription", "max_messages": 1}
        )
        
        assert message is not None
        assert message.id == "test-message-id"
        assert message.payload.metadata.source == "github"
        assert message.attempts == 1  # Incremented from 0
        assert hasattr(message, "_ack_id")
        assert message._ack_id == "test-ack-id"
    
    @pytest.mark.asyncio
    async def test_receive_message_empty(self, patch_pubsub, gcp_config, mock_subscriber):
        """Test receiving a message when the queue is empty."""
        mock_subscriber.pull.return_value = MagicMock(received_messages=[])
        
        client = patch_pubsub(gcp_config)
        
        message = await client.receive_message()
        
        assert message is None
    
    @pytest.mark.asyncio
    async def test_delete_message(self, patch_pubsub, gcp_config, mock_subscriber):
        """Test deleting a message from GCP Pub/Sub."""
        client = patch_pubsub(gcp_config)
        
        # First receive a message to get the ack_id
        message = await client.receive_message()
        
        # Store the message as the current message
        setattr(client, "_current_message", message)
        
        # Delete the message
        result = await client.delete_message(message.id)
        
        mock_subscriber.acknowledge.assert_called_once_with(
            request={"subscription": "projects/test-project/subscriptions/test-subscription", "ack_ids": ["test-ack-id"]}
        )
        
        assert result is True


class TestAWSSQSClient:
    
    @pytest.fixture
    def mock_sqs_client(self):
        """Fixture that provides a mock SQS client."""
        mock = MagicMock()
        mock.send_message.return_value = {"MessageId": "mock-message-id"}
        mock.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "test-message-id",
                    "ReceiptHandle": "test-receipt-handle",
                    "Body": json.dumps({
                        "id": "test-message-id",
                        "payload": {
                            "metadata": {
                                "source": "github",
                                "received_at": "2023-01-01T00:00:00",
                                "headers": {"X-GitHub-Event": "push"},
                            },
                            "content": {"event": "test"},
                        },
                        "created_at": "2023-01-01T00:00:00",
                        "attempts": 0,
                    }),
                }
            ]
        }
        mock.delete_message.return_value = {}
        return mock
    
    @pytest.fixture
    def patch_boto3(self, mock_sqs_client):
        """Fixture that patches the boto3 module."""
        # Create a mock boto3 module
        boto3_mock = MagicMock()
        session_mock = MagicMock()
        session_mock.client.return_value = mock_sqs_client
        boto3_mock.session.Session.return_value = session_mock
        
        # Use patch.dict to replace boto3 in sys.modules
        with patch.dict("sys.modules", {"boto3": boto3_mock}):
            # Import the client class after patching sys.modules
            from webhook_relay.common.queue import AWSSQSClient
            yield AWSSQSClient
    
    @pytest.mark.asyncio
    async def test_send_message(self, patch_boto3, aws_config, sample_webhook_payload, mock_sqs_client):
        """Test sending a message to AWS SQS."""
        client = patch_boto3(aws_config)
        
        message_id = await client.send_message(sample_webhook_payload)
        
        assert message_id == "mock-message-id"
        mock_sqs_client.send_message.assert_called_once()
        kwargs = mock_sqs_client.send_message.call_args[1]
        assert kwargs["QueueUrl"] == aws_config.queue_url
        
        # Verify the message body contains the payload
        # Now using model_dump_json() directly
        message_body = json.loads(kwargs["MessageBody"])
        assert "id" in message_body
        assert "payload" in message_body
        assert message_body["payload"]["metadata"]["source"] == "github"
    
    @pytest.mark.asyncio
    async def test_receive_message(self, patch_boto3, aws_config, mock_sqs_client):
        """Test receiving a message from AWS SQS."""
        client = patch_boto3(aws_config)
        
        message = await client.receive_message()
        
        mock_sqs_client.receive_message.assert_called_once_with(
            QueueUrl=aws_config.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=5,
            AttributeNames=["All"],
        )
        
        assert message is not None
        assert message.id == "test-message-id"
        assert message.payload.metadata.source == "github"
        assert message.attempts == 1  # Incremented from 0
        assert hasattr(message, "_receipt_handle")
        assert message._receipt_handle == "test-receipt-handle"
    
    @pytest.mark.asyncio
    async def test_receive_message_empty(self, patch_boto3, aws_config, mock_sqs_client):
        """Test receiving a message when the queue is empty."""
        mock_sqs_client.receive_message.return_value = {}
        
        client = patch_boto3(aws_config)
        
        message = await client.receive_message()
        
        assert message is None
    
    @pytest.mark.asyncio
    async def test_delete_message(self, patch_boto3, aws_config, mock_sqs_client):
        """Test deleting a message from AWS SQS."""
        client = patch_boto3(aws_config)
        
        # First receive a message to get the receipt handle
        message = await client.receive_message()
        
        # Store the message as the current message
        setattr(client, "_current_message", message)
        
        # Delete the message
        result = await client.delete_message(message.id)
        
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=aws_config.queue_url,
            ReceiptHandle="test-receipt-handle"
        )
        
        assert result is True