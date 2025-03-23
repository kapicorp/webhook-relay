import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from webhook_relay.forwarder.client import WebhookForwarder
from webhook_relay.common.metrics import metrics


class TestWebhookForwarder:
    
    @pytest.fixture
    def forwarder(self, mock_queue_client, forwarder_config):
        """Fixture that provides a configured webhook forwarder."""
        return WebhookForwarder(
            queue_client=mock_queue_client,
            target_url=forwarder_config.target_url,
            headers=forwarder_config.headers,
            retry_attempts=forwarder_config.retry_attempts,
            retry_delay=forwarder_config.retry_delay,
            timeout=forwarder_config.timeout,
        )
    
    @pytest.mark.asyncio
    async def test_forward_webhook_success(self, forwarder, sample_queue_message):
        """Test that forwarding a webhook successfully works."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            # Configure mock session
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            
            # Configure mock response
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value="OK")
            
            # Create a context manager mock
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=mock_response)
            cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.post.return_value = cm
            
            # Patch metrics to avoid errors
            with patch("webhook_relay.forwarder.client.metrics") as mock_metrics:
                mock_forward_total = MagicMock()
                mock_metrics.forward_total = mock_forward_total
                mock_labels = MagicMock()
                mock_forward_total.labels.return_value = mock_labels
                
                # Forward the webhook
                result = await forwarder.forward_webhook(sample_queue_message)
                
                # Check that the forwarder returned success
                assert result is True
                
                # Check that post was called
                mock_session.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_forward_webhook_error_status(self, forwarder, sample_queue_message):
        """Test that forwarding a webhook with an error status code fails."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            # Configure mock session
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            
            # Configure mock response
            mock_response = MagicMock()
            mock_response.status = 400
            mock_response.text = AsyncMock(return_value="Bad Request")
            
            # Create a context manager mock
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=mock_response)
            cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.post.return_value = cm
            
            # Patch forwarder to make it use only one retry
            original_retry_attempts = forwarder.retry_attempts
            forwarder.retry_attempts = 1
            
            # Patch metrics to avoid errors
            with patch("webhook_relay.forwarder.client.metrics") as mock_metrics:
                mock_forward_errors = MagicMock()
                mock_metrics.forward_errors = mock_forward_errors
                mock_error_labels = MagicMock()
                mock_forward_errors.labels.return_value = mock_error_labels
                
                mock_forward_retry = MagicMock()
                mock_metrics.forward_retry_total = mock_forward_retry
                mock_retry_labels = MagicMock()
                mock_forward_retry.labels.return_value = mock_retry_labels
                
                # Forward the webhook
                result = await forwarder.forward_webhook(sample_queue_message)
                
                # Check that the forwarder returned failure
                assert result is False
                
                # Restore original retry attempts
                forwarder.retry_attempts = original_retry_attempts
    
    @pytest.mark.asyncio
    async def test_forward_webhook_exception(self, forwarder, sample_queue_message):
        """Test that forwarding a webhook with an exception fails."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            # Configure mock session to raise an exception
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            mock_session.post.side_effect = Exception("Connection error")
            
            # Patch forwarder to make it use only one retry
            original_retry_attempts = forwarder.retry_attempts
            forwarder.retry_attempts = 1
            
            # Patch metrics to avoid errors
            with patch("webhook_relay.forwarder.client.metrics") as mock_metrics:
                mock_forward_errors = MagicMock()
                mock_metrics.forward_errors = mock_forward_errors
                mock_error_labels = MagicMock()
                mock_forward_errors.labels.return_value = mock_error_labels
                
                mock_forward_retry = MagicMock()
                mock_metrics.forward_retry_total = mock_forward_retry
                mock_retry_labels = MagicMock()
                mock_forward_retry.labels.return_value = mock_retry_labels
                
                # Forward the webhook
                result = await forwarder.forward_webhook(sample_queue_message)
                
                # Check that the forwarder returned failure
                assert result is False
                
                # Restore original retry attempts
                forwarder.retry_attempts = original_retry_attempts
    
    @pytest.mark.asyncio
    async def test_process_message_success(self, forwarder, sample_queue_message, mock_queue_client):
        """Test that processing a message successfully works."""
        # Patch the forward_webhook method directly and the measure_time decorator
        with patch.object(forwarder, "forward_webhook", AsyncMock(return_value=True)), \
             patch("webhook_relay.forwarder.client.metrics") as mock_metrics, \
             patch("webhook_relay.common.metrics.measure_time", side_effect=lambda x, y: lambda f: f):
            
            # Configure mocks for metrics
            mock_delete_metric = MagicMock()
            mock_metrics.queue_delete_total = mock_delete_metric
            mock_delete_labels = MagicMock()
            mock_delete_metric.labels.return_value = mock_delete_labels
            
            # Process the message
            result = await forwarder.process_message(sample_queue_message)
            
            # Check that the processor returned success
            assert result is True
            
            # Check that forward_webhook was called with the message
            forwarder.forward_webhook.assert_called_once_with(sample_queue_message)
            
            # Check that the message was deleted from the queue
            assert mock_queue_client._delete_message_mock.call_count == 1
            assert mock_queue_client._delete_message_mock.call_args[0][0] == sample_queue_message.id
    
    @pytest.mark.asyncio
    async def test_process_message_forward_failure(self, forwarder, sample_queue_message, mock_queue_client):
        """Test that processing a message with a forwarding failure doesn't delete the message."""
        # Patch the forward_webhook method directly and the measure_time decorator
        with patch.object(forwarder, "forward_webhook", AsyncMock(return_value=False)), \
             patch("webhook_relay.common.metrics.measure_time", side_effect=lambda x, y: lambda f: f):
            
            # Process the message
            result = await forwarder.process_message(sample_queue_message)
            
            # Check that the processor returned failure
            assert result is False
            
            # Check that forward_webhook was called with the message
            forwarder.forward_webhook.assert_called_once_with(sample_queue_message)
            
            # Check that the message was not deleted from the queue
            assert mock_queue_client._delete_message_mock.call_count == 0
    
    @pytest.mark.asyncio
    async def test_run(self, forwarder, sample_queue_message, mock_queue_client):
        """Test that the run method processes messages until shutdown."""
        # Configure mock queue to return one message and then None
        mock_queue_client._receive_message_mock.side_effect = [sample_queue_message, None]
        
        # Create a shutdown event
        shutdown_event = asyncio.Event()
        
        # Create a mock for forward_webhook
        forward_mock = AsyncMock(return_value=True)
        
        # Patch metrics and the forward_webhook method
        with patch.object(forwarder, "forward_webhook", forward_mock), \
             patch("webhook_relay.forwarder.client.metrics") as mock_metrics:
            
            # Configure metrics mocks
            mock_receive = MagicMock()
            mock_metrics.queue_receive_total = mock_receive
            mock_receive_labels = MagicMock()
            mock_receive.labels.return_value = mock_receive_labels
            
            mock_delete = MagicMock()
            mock_metrics.queue_delete_total = mock_delete
            mock_delete_labels = MagicMock()
            mock_delete.labels.return_value = mock_delete_labels
            
            # Set the shutdown event after a short delay
            async def set_shutdown():
                await asyncio.sleep(0.1)
                shutdown_event.set()
            
            # Run the forwarder and the shutdown task
            run_task = asyncio.create_task(forwarder.run(shutdown_event))
            set_task = asyncio.create_task(set_shutdown())
            
            # Wait for both tasks to complete
            await asyncio.gather(run_task, set_task)
            
            # Check that receive_message was called
            assert mock_queue_client._receive_message_mock.call_count >= 1
            
            # Give the forward_webhook mock a chance to be called
            await asyncio.sleep(0.1)
            
            # Check that forward_webhook was called with the message
            forward_mock.assert_called_once_with(sample_queue_message)