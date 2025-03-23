import sys
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from webhook_relay.collector.routes import router
from webhook_relay.common.config import CollectorConfig
from webhook_relay.common.metrics import metrics, start_metrics_server


def create_app(config: CollectorConfig) -> FastAPI:
    app = FastAPI(
        title="Webhook Relay Collector",
        description="Receives webhooks and relays them to internal services",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/webhooks")

    @app.on_event("startup")
    async def startup_event():
        # Set up logging
        logger.remove()
        logger.add(
            sys.stderr,
            level=config.log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        )

        # Start metrics server if enabled
        if config.metrics.enabled:
            start_metrics_server(config.metrics.port, config.metrics.host)
            logger.info(
                f"Metrics server started on {config.metrics.host}:{config.metrics.port}"
            )

        # Set up service state metric
        metrics.up.labels(component="collector").set(1)

        logger.info(f"Webhook Relay Collector started on {config.host}:{config.port}")

        # Log registered webhook sources
        for source in config.webhook_sources:
            signature_check = (
                "with signature validation"
                if source.secret
                else "without signature validation"
            )
            logger.info(f"Registered webhook source: {source.name} {signature_check}")

    @app.on_event("shutdown")
    async def shutdown_event():
        metrics.up.labels(component="collector").set(0)
        logger.info("Webhook Relay Collector shutting down")

    return app


def run_server(config: Optional[CollectorConfig] = None):
    if not config:
        from webhook_relay.collector.app import get_app_config

        config = get_app_config()

    app = create_app(config)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
    )
