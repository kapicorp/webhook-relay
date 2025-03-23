import hmac
import hashlib
import json
from typing import Dict, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger

from webhook_relay.common.config import CollectorConfig
from webhook_relay.common.metrics import metrics, measure_time
from webhook_relay.common.models import WebhookMetadata, WebhookPayload
from webhook_relay.common.queue import QueueClient


router = APIRouter()


async def get_config() -> CollectorConfig:
    # This would typically be loaded from a file or environment variables
    # For the dependency injection in FastAPI
    from webhook_relay.collector.app import get_app_config
    return get_app_config()


async def get_queue_client() -> QueueClient:
    from webhook_relay.collector.app import get_queue_client
    return get_queue_client()


async def validate_webhook_signature(
    request: Request,
    source: str,
    config: CollectorConfig = Depends(get_config),
) -> bool:
    """Validate the webhook signature if configured."""
    webhook_source = next(
        (src for src in config.webhook_sources if src.name == source), None
    )
    
    if not webhook_source:
        raise HTTPException(status_code=404, detail=f"Unknown webhook source: {source}")
    
    if not webhook_source.secret or not webhook_source.signature_header:
        # No signature validation required
        return True
    
    signature_header = webhook_source.signature_header
    expected_signature = request.headers.get(signature_header)
    
    if not expected_signature:
        raise HTTPException(
            status_code=400,
            detail=f"Missing signature header: {signature_header}"
        )
    
    body = await request.body()
    
    # Calculate signature
    digest = hmac.new(
        webhook_source.secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    calculated_signature = f"sha256={digest}"
    
    if not hmac.compare_digest(calculated_signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    return True


@router.post("/{source}", status_code=202)
@measure_time(metrics.webhook_processing_time, {"source": "webhook"})
async def receive_webhook(
    source: str,
    request: Request,
    config: CollectorConfig = Depends(get_config),
    queue_client: QueueClient = Depends(get_queue_client),
    user_agent: str = Header(None),
):
    # Validate webhook source and signature
    await validate_webhook_signature(request, source, config)
    
    # Parse request body
    body = await request.body()
    try:
        content = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Extract headers
    headers = {k: v for k, v in request.headers.items()}
    
    # Create webhook metadata
    metadata = WebhookMetadata(
        source=source,
        signature=request.headers.get("X-Hub-Signature-256"),
        headers=headers,
    )
    
    # Create webhook payload
    payload = WebhookPayload(metadata=metadata, content=content)
    
    # Record metric
    metrics.webhook_received_total.labels(source=source).inc()
    
    try:
        # Send to queue
        message_id = await queue_client.send_message(payload)
        metrics.queue_publish_total.labels(queue_type=config.queue_type).inc()
        logger.info(f"Webhook from {source} queued with ID {message_id}")
        return {"status": "accepted", "message_id": message_id}
    except Exception as e:
        metrics.queue_publish_errors.labels(queue_type=config.queue_type).inc()
        logger.error(f"Failed to queue webhook from {source}: {e}")
        raise HTTPException(status_code=500, detail="Failed to queue webhook")


@router.get("/health")
async def health_check():
    return {"status": "ok"}