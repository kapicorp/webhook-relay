import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from webhook_relay.common.metrics import metrics
from webhook_relay.forwarder.app import (
    cli,
    get_app_config,
    get_queue_client,
    handle_signal,
    load_config_from_file,
    run_forwarder,
    setup_app,
)


class TestForwarderApp:

    def test_get_app_config_not_initialized(self):
        """Test that get_app_config raises an exception when not initialized."""
        with patch("webhook_relay.forwarder.app._app_config", None):
            with pytest.raises(
                RuntimeError, match="Application config not initialized"
            ):
                get_app_config()

    def test_get_queue_client_not_initialized(self):
        """Test that get_queue_client raises an exception when not initialized."""
        with patch("webhook_relay.forwarder.app._queue_client", None):
            with pytest.raises(RuntimeError, match="Queue client not initialized"):
                get_queue_client()

    def test_load_config_from_file(self, tmp_path, forwarder_config):
        """Test that load_config_from_file loads configuration from a YAML file."""
        # Create a temporary config file
        config_file = tmp_path / "config.yaml"
        config_dict = forwarder_config.model_dump()

        # Convert QueueType enum value to string
        config_dict["queue_type"] = config_dict["queue_type"].value

        with open(config_file, "w") as f:
            yaml.dump(config_dict, f)

        # Load the config
        loaded_config = load_config_from_file(str(config_file))

        # Check that the config was loaded correctly
        assert loaded_config.target_url == forwarder_config.target_url
        assert loaded_config.queue_type == forwarder_config.queue_type
        assert (
            loaded_config.gcp_config.project_id
            == forwarder_config.gcp_config.project_id
        )

    def test_load_config_from_file_not_found(self):
        """Test that load_config_from_file raises an exception when the file is not found."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config_from_file("/path/to/nonexistent/config.yaml")

    def test_setup_app(self, forwarder_config, mock_queue_client):
        """Test that setup_app initializes the application."""
        with patch(
            "webhook_relay.forwarder.app.create_queue_client"
        ) as mock_create_client, patch(
            "webhook_relay.forwarder.app.WebhookForwarder"
        ) as mock_forwarder_class, patch(
            "webhook_relay.forwarder.app.logger"
        ):

            mock_create_client.return_value = mock_queue_client
            mock_forwarder = MagicMock()
            mock_forwarder_class.return_value = mock_forwarder

            # Set up the app
            setup_app(forwarder_config)

            # Check that the queue client was created
            mock_create_client.assert_called_once_with(
                queue_type=forwarder_config.queue_type,
                gcp_config=forwarder_config.gcp_config,
                aws_config=forwarder_config.aws_config,
            )

            # Check that the forwarder was created
            mock_forwarder_class.assert_called_once_with(
                queue_client=mock_queue_client,
                target_url=forwarder_config.target_url,
                headers=forwarder_config.headers,
                retry_attempts=forwarder_config.retry_attempts,
                retry_delay=forwarder_config.retry_delay,
                timeout=forwarder_config.timeout,
            )

            # Check that the global variables were set
            assert get_app_config() == forwarder_config
            assert get_queue_client() == mock_queue_client

    @pytest.mark.asyncio
    async def test_run_forwarder(self, forwarder_config):
        """Test that run_forwarder starts the forwarder and metrics server."""
        mock_forwarder = AsyncMock()
        mock_forwarder.run = AsyncMock()
        mock_event = AsyncMock()

        with patch(
            "webhook_relay.forwarder.app.start_metrics_server"
        ) as mock_start_metrics, patch(
            "webhook_relay.forwarder.app.metrics.up"
        ) as mock_up, patch(
            "webhook_relay.forwarder.app.logger"
        ):

            # Set up the mock for _app_config, _forwarder, and _shutdown_event
            with patch(
                "webhook_relay.forwarder.app._app_config", forwarder_config
            ), patch("webhook_relay.forwarder.app._forwarder", mock_forwarder), patch(
                "webhook_relay.forwarder.app._shutdown_event", mock_event
            ):

                # Configure the up metric mock
                mock_labels = MagicMock()
                mock_up.labels.return_value = mock_labels

                # Run the forwarder
                await run_forwarder()

                # Check that metrics server was started
                mock_start_metrics.assert_called_once_with(
                    forwarder_config.metrics.port, forwarder_config.metrics.host
                )

                # Check that the forwarder's run method was called
                mock_forwarder.run.assert_called_once_with(mock_event)

                # Check that up metric was set to 1 and then 0
                mock_up.labels.assert_any_call(component="forwarder")
                mock_labels.set.assert_any_call(1)
                mock_labels.set.assert_any_call(0)

    def test_handle_signal(self):
        """Test that handle_signal sets the shutdown event."""
        mock_event = MagicMock()

        with patch("webhook_relay.forwarder.app._shutdown_event", mock_event):
            handle_signal(signal.SIGINT, None)

            mock_event.set.assert_called_once()

    def test_cli_serve_command(self, forwarder_config, tmp_path):
        """Test that the CLI serve command calls run_forwarder."""
        # Create a temporary config file
        config_file = tmp_path / "config.yaml"
        config_dict = forwarder_config.model_dump()

        # Convert QueueType enum value to string
        config_dict["queue_type"] = config_dict["queue_type"].value

        with open(config_file, "w") as f:
            yaml.dump(config_dict, f)

        with patch("webhook_relay.forwarder.app.setup_app") as mock_setup, patch(
            "webhook_relay.forwarder.app.signal.signal"
        ) as mock_signal, patch(
            "webhook_relay.forwarder.app.asyncio.run"
        ) as mock_run, patch(
            "webhook_relay.forwarder.app.logger"
        ):

            # Create a runner for the CLI
            from click.testing import CliRunner

            runner = CliRunner()

            # Run the serve command
            result = runner.invoke(cli, ["serve", "--config", str(config_file)])

            # Check that the command succeeded
            assert result.exit_code == 0

            # Check that setup_app was called
            mock_setup.assert_called_once()

            # Check that signal handlers were registered
            assert mock_signal.call_count == 2
            signal_args = [call_args[0][0] for call_args in mock_signal.call_args_list]
            assert signal.SIGINT in signal_args
            assert signal.SIGTERM in signal_args

            # Check that asyncio.run was called with run_forwarder
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0].__name__ == "run_forwarder"
