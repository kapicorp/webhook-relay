import asyncio
import json
from typing import Dict, Optional
from urllib.parse import urlparse

import aiohttp
from loguru import logger

from webhook_relay.common.metrics import metrics, measure_time
from webhook_relay.common.models import QueueMessage
from webhook_relay.common.queue import QueueClient


class WebhookForwarder:
    def __init__(
        self,
        queue_client: QueueClient,
        target_url: str,
        headers: Dict[str, str] = None,
        retry_attempts: int = 3,
        retry_delay: int = 5,
        timeout: int = 10,
    ):
        self.queue_client = queue_client
        self.target_url = target_url
        self.headers = headers or {}
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.timeout = timeout
        
        # Extract hostname for metrics labels
        parsed_url = urlparse(target_url)
        self.target_label = f"{parsed_url.netloc}{parsed_url.path}"

    async def forward_webhook(self, message: QueueMessage) -> bool:
        """Forward a webhook to the target URL."""
        payload = message.payload
        
        # Prepare request headers
        headers = self.headers.copy()
        
        # Include original headers if they're JSON serializable
        try:
            for key, value in payload.metadata.headers.items():
                if key.lower() not in [h.lower() for h in headers]:
                    headers[key] = value
        except Exception as e:
            logger.warning(f"Could not include original headers: {e}")
        
        # Add source information
        headers["X-Webhook-Relay-Source"] = payload.metadata.source
        headers["X-Webhook-Relay-ID"] = message.id
        
        # Add original signature if present
        if payload.metadata.signature:
            headers["X-Webhook-Relay-Signature"] = payload.metadata.signature
        
        # Prepare request body
        body = json.dumps(payload.content)
        
        # Set up exponential backoff for retries
        backoff = self.retry_delay
        
        # Try to forward the webhook with retries
        for attempt in range(self.retry_attempts):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.target_url,
                        headers=headers,
                        data=body,
                        timeout=self.timeout,
                    ) as response:
                        if response.status < 400:
                            metrics.forward_total.labels(target=self.target_label).inc()
                            logger.info(
                                f"Webhook forwarded successfully to {self.target_url} "
                                f"(status={response.status})"
                            )
                            return True
                        else:
                            metrics.forward_errors.labels(
                                target=self.target_label,
                                status_code=response.status,
                            ).inc()
                            response_text = await response.text()
                            logger.error(
                                f"Failed to forward webhook to {self.target_url} "
                                f"(status={response.status}): {response_text}"
                            )
            except Exception as e:
                metrics.forward_errors.labels(
                    target=self.target_label,
                    status_code="error",
                ).inc()
                logger.error(f"Error forwarding webhook to {self.target_url}: {e}")
            
            # Check if we should retry
            if attempt < self.retry_attempts - 1:
                metrics.forward_retry_total.labels(target=self.target_label).inc()
                logger.info(
                    f"Retrying webhook forward to {self.target_url} "
                    f"(attempt {attempt + 1}/{self.retry_attempts}, "
                    f"backoff={backoff}s)"
                )
                await asyncio.sleep(backoff)
                backoff *= 2  # Exponential backoff
            else:
                logger.error(
                    f"Giving up forwarding webhook to {self.target_url} "
                    f"after {self.retry_attempts} attempts"
                )
        
        return False

    @measure_time(metrics.forward_latency, lambda self: {"target": self.target_label})
    async def process_message(self, message: QueueMessage) -> bool:
        """Process a message from the queue."""
        try:
            # Forward the webhook
            success = await self.forward_webhook(message)
            
            if success:
                # Delete the message from the queue if forwarding was successful
                deleted = await self.queue_client.delete_message(message.id)
                if deleted:
                    metrics.queue_delete_total.labels(
                        queue_type=self.queue_client.__class__.__name__
                    ).inc()
                    logger.debug(f"Deleted message {message.id} from queue")
                else:
                    logger.error(f"Failed to delete message {message.id} from queue")
            
            return success
        except Exception as e:
            logger.error(f"Error processing message {message.id}: {e}")
            return False

    async def run(self, shutdown_event: asyncio.Event):
        """Run the forwarder service."""
        logger.info(f"Starting webhook forwarder for {self.target_url}")
        
        while not shutdown_event.is_set():
            try:
                # Receive a message from the queue
                message = await self.queue_client.receive_message()
                
                if message:
                    metrics.queue_receive_total.labels(
                        queue_type=self.queue_client.__class__.__name__
                    ).inc()
                    logger.debug(f"Received message {message.id} from queue")
                    
                    # Process the message
                    await self.process_message(message)
                else:
                    # No message received, wait a bit before polling again
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in forwarder loop: {e}")
                await asyncio.sleep(5)  # Wait a bit before retrying
        
        logger.info("Forwarder service stopped")