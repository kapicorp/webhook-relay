import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

import click
import yaml
from loguru import logger

from webhook_relay.common.config import ForwarderConfig
from webhook_relay.common.metrics import metrics, start_metrics_server
from webhook_relay.common.queue import QueueClient, create_queue_client
from webhook_relay.forwarder.client import WebhookForwarder


_app_config: Optional[ForwarderConfig] = None
_queue_client: Optional[QueueClient] = None
_forwarder: Optional[WebhookForwarder] = None
_shutdown_event: Optional[asyncio.Event] = None


def get_app_config() -> ForwarderConfig:
    global _app_config
    if not _app_config:
        raise RuntimeError("Application config not initialized")
    return _app_config


def get_queue_client() -> QueueClient:
    global _queue_client
    if not _queue_client:
        raise RuntimeError("Queue client not initialized")
    return _queue_client


def load_config_from_file(config_path: str) -> ForwarderConfig:
    """Load configuration from a YAML file."""
    file_path = Path(config_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(file_path, "r") as f:
        config_data = yaml.safe_load(f)
    
    return ForwarderConfig.model_validate(config_data)


def setup_app(config: ForwarderConfig):
    """Initialize the application with the given config."""
    global _app_config, _queue_client, _forwarder, _shutdown_event
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stderr,
        level=config.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )
    
    # Validate queue configuration
    config.validate_queue_config()
    
    # Create queue client
    _queue_client = create_queue_client(
        queue_type=config.queue_type,
        gcp_config=config.gcp_config,
        aws_config=config.aws_config,
    )
    
    # Create shutdown event
    _shutdown_event = asyncio.Event()
    
    # Create forwarder
    _forwarder = WebhookForwarder(
        queue_client=_queue_client,
        target_url=config.target_url,
        headers=config.headers,
        retry_attempts=config.retry_attempts,
        retry_delay=config.retry_delay,
        timeout=config.timeout,
    )
    
    _app_config = config
    
    logger.info("Webhook Relay Forwarder initialized")
    logger.info(f"Target URL: {config.target_url}")


async def run_forwarder():
    """Run the forwarder service."""
    global _app_config, _forwarder, _shutdown_event
    
    # Start metrics server if enabled
    if _app_config.metrics.enabled:
        start_metrics_server(_app_config.metrics.port, _app_config.metrics.host)
        logger.info(f"Metrics server started on {_app_config.metrics.host}:{_app_config.metrics.port}")
    
    # Set up service state metric
    metrics.up.labels(component="forwarder").set(1)
    
    logger.info("Webhook Relay Forwarder started")
    
    try:
        await _forwarder.run(_shutdown_event)
    except Exception as e:
        logger.error(f"Forwarder error: {e}")
    finally:
        metrics.up.labels(component="forwarder").set(0)
        logger.info("Webhook Relay Forwarder stopped")


def handle_signal(sig, frame):
    """Handle termination signals."""
    global _shutdown_event
    if _shutdown_event:
        logger.info(f"Received signal {sig}, shutting down...")
        _shutdown_event.set()


@click.group()
def cli():
    """Webhook Relay Forwarder CLI"""
    pass


@cli.command("serve")
@click.option(
    "--config",
    "-c",
    required=True,
    help="Path to configuration file",
)
def serve(config: str):
    """Start the forwarder service."""
    try:
        config_obj = load_config_from_file(config)
        setup_app(config_obj)
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
        
        # Run the forwarder
        asyncio.run(run_forwarder())
    except Exception as e:
        logger.error(f"Failed to start forwarder: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()