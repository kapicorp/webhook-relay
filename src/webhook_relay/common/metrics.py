from functools import wraps
import time
from typing import Callable, Dict, Optional

from prometheus_client import Counter, Gauge, Histogram, start_http_server


class MetricsRegistry:
    def __init__(self):
        # Collector metrics
        self.webhook_received_total = Counter(
            "webhook_relay_received_total",
            "Total number of webhooks received",
            ["source"]
        )
        self.webhook_processing_time = Histogram(
            "webhook_relay_processing_seconds",
            "Time spent processing webhooks",
            ["source"]
        )
        self.queue_publish_total = Counter(
            "webhook_relay_queue_publish_total",
            "Total number of messages published to queue",
            ["queue_type"]
        )
        self.queue_publish_errors = Counter(
            "webhook_relay_queue_publish_errors",
            "Total number of errors publishing to queue",
            ["queue_type"]
        )
        
        # Forwarder metrics
        self.queue_receive_total = Counter(
            "webhook_relay_queue_receive_total",
            "Total number of messages received from queue",
            ["queue_type"]
        )
        self.queue_delete_total = Counter(
            "webhook_relay_queue_delete_total",
            "Total number of messages deleted from queue",
            ["queue_type"]
        )
        self.forward_total = Counter(
            "webhook_relay_forward_total",
            "Total number of webhooks forwarded",
            ["target"]
        )
        self.forward_errors = Counter(
            "webhook_relay_forward_errors",
            "Total number of errors forwarding webhooks",
            ["target", "status_code"]
        )
        self.forward_retry_total = Counter(
            "webhook_relay_forward_retry_total",
            "Total number of webhook forward retries",
            ["target"]
        )
        self.forward_latency = Histogram(
            "webhook_relay_forward_seconds",
            "Time spent forwarding webhooks",
            ["target"]
        )
        
        # Common metrics
        self.up = Gauge(
            "webhook_relay_up",
            "Whether the webhook relay service is up",
            ["component"]
        )


# Global metrics registry
metrics = MetricsRegistry()


def start_metrics_server(port: int = 9090, addr: str = ""):
    """Start the Prometheus metrics server."""
    start_http_server(port, addr)


def measure_time(
    metric: Histogram,
    labels: Optional[Dict[str, str]] = None
) -> Callable:
    """Decorator to measure the execution time of a function."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            labels_dict = labels or {}
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                metric.labels(**labels_dict).observe(duration)
        return wrapper
    return decorator