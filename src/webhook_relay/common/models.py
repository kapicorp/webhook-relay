from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class WebhookMetadata(BaseModel):
    source: str
    received_at: datetime = Field(default_factory=datetime.utcnow)
    signature: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)


class WebhookPayload(BaseModel):
    metadata: WebhookMetadata
    content: Dict[str, Any]


class QueueMessage(BaseModel):
    id: str
    payload: WebhookPayload
    created_at: datetime = Field(default_factory=datetime.utcnow)
    attempts: int = 0