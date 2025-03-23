import asyncio
import time
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY, CollectorRegistry

from webhook_relay.common.metrics import (
    MetricsRegistry,
    measure_time,
    metrics,
    start_metrics_server,
)


class TestMetricsRegistry:

    def test_metrics_initialization(self):
        """Test that the metrics registry is properly initialized."""
        # Use a separate registry for each test to avoid conflicts
        test_registry = CollectorRegistry()
        registry = MetricsRegistry(registry=test_registry)

        # Check that all expected metrics are created
        assert hasattr(registry, "webhook_received_total")
        assert hasattr(registry, "webhook_processing_time")
        assert hasattr(registry, "queue_publish_total")
        assert hasattr(registry, "queue_publish_errors")
        assert hasattr(registry, "queue_receive_total")
        assert hasattr(registry, "queue_delete_total")
        assert hasattr(registry, "forward_total")
        assert hasattr(registry, "forward_errors")
        assert hasattr(registry, "forward_retry_total")
        assert hasattr(registry, "forward_latency")
        assert hasattr(registry, "up")

    def test_global_metrics_instance(self):
        """Test that the global metrics instance is properly created."""
        assert metrics is not None
        assert isinstance(metrics, MetricsRegistry)
