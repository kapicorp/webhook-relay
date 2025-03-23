import time
from functools import wraps
from typing import Callable, Dict, Optional, Union

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, start_http_server


class MetricsRegistry:
    def __init__(self, registry=None):
        # Use a provided registry or the default one
        self.registry = registry or REGISTRY

        # Collector metrics
        self.webhook_received_total = Counter(
            "webhook_relay_received_total",
            "Total number of webhooks received",
            ["source"],
            registry=self.registry,
        )
        self.webhook_processing_time = Histogram(
            "webhook_relay_processing_seconds",
            "Time spent processing webhooks",
            ["source"],
            registry=self.registry,
        )
        self.queue_publish_total = Counter(
            "webhook_relay_queue_publish_total",
            "Total number of messages published to queue",
            ["queue_type"],
            registry=self.registry,
        )
        self.queue_publish_errors = Counter(
            "webhook_relay_queue_publish_errors",
            "Total number of errors publishing to queue",
            ["queue_type"],
            registry=self.registry,
        )

        # Forwarder metrics
        self.queue_receive_total = Counter(
            "webhook_relay_queue_receive_total",
            "Total number of messages received from queue",
            ["queue_type"],
            registry=self.registry,
        )
        self.queue_delete_total = Counter(
            "webhook_relay_queue_delete_total",
            "Total number of messages deleted from queue",
            ["queue_type"],
            registry=self.registry,
        )
        self.forward_total = Counter(
            "webhook_relay_forward_total",
            "Total number of webhooks forwarded",
            ["target"],
            registry=self.registry,
        )
        self.forward_errors = Counter(
            "webhook_relay_forward_errors",
            "Total number of errors forwarding webhooks",
            ["target", "status_code"],
            registry=self.registry,
        )
        self.forward_retry_total = Counter(
            "webhook_relay_forward_retry_total",
            "Total number of webhook forward retries",
            ["target"],
            registry=self.registry,
        )
        self.forward_latency = Histogram(
            "webhook_relay_forward_seconds",
            "Time spent forwarding webhooks",
            ["target"],
            registry=self.registry,
        )

        # Common metrics
        self.up = Gauge(
            "webhook_relay_up",
            "Whether the webhook relay service is up",
            ["component"],
            registry=self.registry,
        )


# Global metrics registry
metrics = MetricsRegistry()


def start_metrics_server(port: int = 9090, host: str = "127.0.0.1"):
    """Start the Prometheus metrics server."""
    start_http_server(port, host)


def measure_time(
    metric: Histogram, labels: Optional[Union[Dict[str, str], Callable]] = None
) -> Callable:
    """Decorator to measure the execution time of a function."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get the labels dictionary
            labels_dict = {}
            if callable(labels) and args:
                # If labels is a lambda/function and we have args (self)
                try:
                    labels_dict = labels(args[0])
                except Exception as e:
                    logger.error(f"Error getting labels from function: {e}")
            elif isinstance(labels, dict):
                labels_dict = labels

            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                try:
                    metric.labels(**labels_dict).observe(duration)
                except Exception as e:
                    logger.error(f"Error recording metric: {e}")

        return wrapper

    return decorator
