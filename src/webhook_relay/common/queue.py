import json
import uuid
from abc import ABC, abstractmethod
from typing import Optional

from loguru import logger

from webhook_relay.common.config import AWSSQSConfig, GCPPubSubConfig, QueueType
from webhook_relay.common.models import QueueMessage, WebhookPayload


class QueueClient(ABC):
    @abstractmethod
    async def send_message(self, payload: WebhookPayload) -> str:
        pass

    @abstractmethod
    async def receive_message(self) -> Optional[QueueMessage]:
        pass

    @abstractmethod
    async def delete_message(self, message_id: str) -> bool:
        pass


class GCPPubSubClient(QueueClient):
    def __init__(self, config: GCPPubSubConfig):
        try:
            from google.cloud import pubsub_v1
        except ImportError:
            raise ImportError(
                "Google Cloud Pub/Sub client not installed. "
                "Install it with: pip install google-cloud-pubsub"
            )
        
        self.project_id = config.project_id
        self.topic_id = config.topic_id
        self.subscription_id = config.subscription_id
        
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_id)
        
        if self.subscription_id:
            self.subscriber = pubsub_v1.SubscriberClient()
            self.subscription_path = self.subscriber.subscription_path(
                self.project_id, self.subscription_id
            )
        else:
            self.subscriber = None
            self.subscription_path = None
        
        logger.info(f"Initialized GCP Pub/Sub client for topic {self.topic_path}")

    async def send_message(self, payload: WebhookPayload) -> str:
        message_id = str(uuid.uuid4())
        queue_message = QueueMessage(id=message_id, payload=payload)
        data = json.dumps(queue_message.model_dump()).encode("utf-8")
        
        try:
            future = self.publisher.publish(self.topic_path, data)
            future.result()  # Wait for message to be published
            logger.debug(f"Published message {message_id} to {self.topic_path}")
            return message_id
        except Exception as e:
            logger.error(f"Error publishing message to {self.topic_path}: {e}")
            raise

    async def receive_message(self) -> Optional[QueueMessage]:
        if not self.subscriber or not self.subscription_path:
            raise RuntimeError("Subscription ID not configured for receiving messages")
        
        try:
            response = self.subscriber.pull(
                request={"subscription": self.subscription_path, "max_messages": 1}
            )
            
            if not response.received_messages:
                return None
            
            received_message = response.received_messages[0]
            message_data = json.loads(received_message.message.data.decode("utf-8"))
            queue_message = QueueMessage.model_validate(message_data)
            queue_message.attempts += 1
            
            logger.debug(f"Received message {queue_message.id} from {self.subscription_path}")
            
            # Attach the ack_id to the message for later acknowledgement
            setattr(queue_message, "_ack_id", received_message.ack_id)
            
            return queue_message
        except Exception as e:
            logger.error(f"Error receiving message from {self.subscription_path}: {e}")
            return None

    async def delete_message(self, message_id: str) -> bool:
        if not self.subscriber or not self.subscription_path:
            raise RuntimeError("Subscription ID not configured for deleting messages")
        
        try:
            # Get the ack_id from the message object
            message = getattr(self, "_current_message", None)
            if not message or message.id != message_id:
                logger.error(f"No ack_id found for message {message_id}")
                return False
            
            ack_id = getattr(message, "_ack_id", None)
            if not ack_id:
                logger.error(f"No ack_id found for message {message_id}")
                return False
            
            self.subscriber.acknowledge(
                request={"subscription": self.subscription_path, "ack_ids": [ack_id]}
            )
            logger.debug(f"Acknowledged message {message_id} from {self.subscription_path}")
            return True
        except Exception as e:
            logger.error(f"Error acknowledging message {message_id}: {e}")
            return False


class AWSSQSClient(QueueClient):
    def __init__(self, config: AWSSQSConfig):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "AWS SQS client not installed. "
                "Install it with: pip install boto3"
            )
        
        session_kwargs = {}
        if config.access_key_id and config.secret_access_key:
            session_kwargs.update({
                "aws_access_key_id": config.access_key_id,
                "aws_secret_access_key": config.secret_access_key,
            })
        
        session = boto3.session.Session(**session_kwargs)
        
        client_kwargs = {"region_name": config.region_name}
        if config.role_arn:
            sts_client = session.client("sts", **client_kwargs)
            assumed_role = sts_client.assume_role(
                RoleArn=config.role_arn,
                RoleSessionName="webhook-relay-session"
            )
            client_kwargs.update({
                "aws_access_key_id": assumed_role["Credentials"]["AccessKeyId"],
                "aws_secret_access_key": assumed_role["Credentials"]["SecretAccessKey"],
                "aws_session_token": assumed_role["Credentials"]["SessionToken"],
            })
        
        self.sqs = session.client("sqs", **client_kwargs)
        self.queue_url = config.queue_url
        
        logger.info(f"Initialized AWS SQS client for queue {self.queue_url}")
        
        # Store current message receipt handle for deletion
        self._current_receipt_handle = None

    async def send_message(self, payload: WebhookPayload) -> str:
        message_id = str(uuid.uuid4())
        queue_message = QueueMessage(id=message_id, payload=payload)
        message_body = json.dumps(queue_message.model_dump())
        
        try:
            response = self.sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=message_body
            )
            logger.debug(f"Published message {message_id} to {self.queue_url}")
            return response["MessageId"]
        except Exception as e:
            logger.error(f"Error publishing message to {self.queue_url}: {e}")
            raise

    async def receive_message(self) -> Optional[QueueMessage]:
        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,
                AttributeNames=["All"],
            )
            
            if not response.get("Messages"):
                return None
            
            message = response["Messages"][0]
            receipt_handle = message["ReceiptHandle"]
            
            message_data = json.loads(message["Body"])
            queue_message = QueueMessage.model_validate(message_data)
            queue_message.attempts += 1
            
            logger.debug(f"Received message {queue_message.id} from {self.queue_url}")
            
            # Save receipt handle for later deletion
            self._current_receipt_handle = receipt_handle
            setattr(queue_message, "_receipt_handle", receipt_handle)
            
            return queue_message
        except Exception as e:
            logger.error(f"Error receiving message from {self.queue_url}: {e}")
            return None

    async def delete_message(self, message_id: str) -> bool:
        try:
            # Get the receipt handle from the message object
            message = getattr(self, "_current_message", None)
            if not message or message.id != message_id:
                logger.error(f"No receipt handle found for message {message_id}")
                return False
            
            receipt_handle = getattr(message, "_receipt_handle", None)
            if not receipt_handle:
                logger.error(f"No receipt handle found for message {message_id}")
                return False
            
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            logger.debug(f"Deleted message {message_id} from {self.queue_url}")
            return True
        except Exception as e:
            logger.error(f"Error deleting message {message_id}: {e}")
            return False


def create_queue_client(
    queue_type: QueueType,
    gcp_config: Optional[GCPPubSubConfig] = None,
    aws_config: Optional[AWSSQSConfig] = None,
) -> QueueClient:
    if queue_type == QueueType.GCP_PUBSUB:
        if not gcp_config:
            raise ValueError("GCP PubSub selected but no GCP configuration provided")
        return GCPPubSubClient(gcp_config)
    elif queue_type == QueueType.AWS_SQS:
        if not aws_config:
            raise ValueError("AWS SQS selected but no AWS configuration provided")
        return AWSSQSClient(aws_config)
    else:
        raise ValueError(f"Unsupported queue type: {queue_type}")