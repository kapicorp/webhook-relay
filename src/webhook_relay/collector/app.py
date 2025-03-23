import sys
from pathlib import Path
from typing import Optional

import click
import yaml
from loguru import logger

from webhook_relay.common.config import CollectorConfig
from webhook_relay.common.queue import QueueClient, create_queue_client
from webhook_relay.collector.server import run_server


_app_config: Optional[CollectorConfig] = None
_queue_client: Optional[QueueClient] = None


def get_app_config() -> CollectorConfig:
    global _app_config
    if not _app_config:
        raise RuntimeError("Application config not initialized")
    return _app_config


def get_queue_client() -> QueueClient:
    global _queue_client
    if not _queue_client:
        raise RuntimeError("Queue client not initialized")
    return _queue_client


def load_config_from_file(config_path: str) -> CollectorConfig:
    """Load configuration from a YAML file."""
    file_path = Path(config_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(file_path, "r") as f:
        config_data = yaml.safe_load(f)
    
    return CollectorConfig.model_validate(config_data)


def setup_app(config: CollectorConfig):
    """Initialize the application with the given config."""
    global _app_config, _queue_client
    
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
    
    _app_config = config
    
    logger.info("Webhook Relay Collector initialized")


@click.group()
def cli():
    """Webhook Relay Collector CLI"""
    pass


@cli.command("serve")
@click.option(
    "--config",
    "-c",
    required=True,
    help="Path to configuration file",
)
def serve(config: str):
    """Start the collector server."""
    try:
        config_obj = load_config_from_file(config)
        setup_app(config_obj)
        run_server(config_obj)
    except Exception as e:
        logger.error(f"Failed to start collector: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()