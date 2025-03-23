from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class QueueType(str, Enum):
    GCP_PUBSUB = "gcp_pubsub"
    AWS_SQS = "aws_sqs"


class GCPPubSubConfig(BaseModel):
    project_id: str
    topic_id: str
    subscription_id: Optional[str] = None  # Only needed for forwarder


class AWSSQSConfig(BaseModel):
    region_name: str
    queue_url: str
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    role_arn: Optional[str] = None


class MetricsConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 9090
    path: str = "/metrics"


class WebhookSourceConfig(BaseModel):
    name: str
    secret: Optional[str] = None
    signature_header: Optional[str] = None


class BaseConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_prefix="WEBHOOK_RELAY_",
        extra="ignore",
    )

    log_level: str = "INFO"
    queue_type: QueueType
    gcp_config: Optional[GCPPubSubConfig] = None
    aws_config: Optional[AWSSQSConfig] = None
    metrics: MetricsConfig = MetricsConfig()

    def validate_queue_config(self) -> None:
        if self.queue_type == QueueType.GCP_PUBSUB and not self.gcp_config:
            raise ValueError("GCP PubSub selected but no GCP configuration provided")
        if self.queue_type == QueueType.AWS_SQS and not self.aws_config:
            raise ValueError("AWS SQS selected but no AWS configuration provided")


class CollectorConfig(BaseConfig):
    host: str = "0.0.0.0"
    port: int = 8000
    webhook_sources: List[WebhookSourceConfig] = []


class ForwarderConfig(BaseConfig):
    target_url: str
    headers: Dict[str, str] = Field(default_factory=dict)
    retry_attempts: int = 3
    retry_delay: int = 5  # seconds
    timeout: int = 10  # seconds
