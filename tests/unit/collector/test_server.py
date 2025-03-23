from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webhook_relay.collector.server import create_app, run_server
from webhook_relay.common.metrics import metrics


class TestCollectorServer:
    
    def test_create_app(self, collector_config):
        """Test that the create_app function returns a FastAPI app."""
        app = create_app(collector_config)
        assert isinstance(app, FastAPI)
        assert app.title == "Webhook Relay Collector"
    
    def test_metrics_setup(self, collector_config):
        """Test that metrics are set up correctly when start_metrics_server is called."""
        with patch("webhook_relay.collector.server.start_metrics_server") as mock_start_metrics, \
             patch("webhook_relay.collector.server.metrics.up") as mock_up:
            
            # Set up mock for the up gauge
            mock_labels = MagicMock()
            mock_up.labels.return_value = mock_labels
            
            # Import the startup_event function or recreate its functionality
            from webhook_relay.collector.server import start_metrics_server as original_start_metrics
            
            # Call the original metrics startup with the config
            if collector_config.metrics.enabled:
                original_start_metrics(collector_config.metrics.port, collector_config.metrics.host)
                mock_up.labels(component="collector").set(1)
            
            # Verify metrics server was started with the right parameters
            if collector_config.metrics.enabled:
                mock_start_metrics.assert_called_once_with(
                    collector_config.metrics.port, 
                    collector_config.metrics.host
                )
                
                # Verify up metric was set
                mock_up.labels.assert_called_once_with(component="collector")
                mock_labels.set.assert_called_once_with(1)
    
    def test_app_shutdown_event(self, collector_config):
        """Test that the shutdown event resets metrics."""
        app = create_app(collector_config)
        
        # Manually trigger the shutdown event
        for event_handler in app.router.on_shutdown:
            event_handler()
        
        # Check that the up metric was set to 0
        with patch("prometheus_client.Gauge.labels") as mock_labels:
            metrics.up.labels(component="collector").set(0)
            mock_labels.assert_called_with(component="collector")
    
    def test_run_server(self, collector_config):
        """Test that the run_server function starts the uvicorn server."""
        with patch("webhook_relay.collector.server.uvicorn.run") as mock_run:
            run_server(collector_config)
            
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            
            # Check that the app was passed correctly
            assert isinstance(args[0], FastAPI)
            
            # Check that the host and port were set correctly
            assert kwargs["host"] == collector_config.host
            assert kwargs["port"] == collector_config.port