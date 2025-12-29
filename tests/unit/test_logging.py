"""Unit tests for logging configuration."""

import os
import tempfile
from loguru import logger
from pathlib import Path
from unifi_mcp.utils.logging import configure_logging, get_logger, log_tool_call, log_tool_result
from unittest.mock import patch


class TestLoggingConfiguration:
    """Test logging configuration."""

    def test_configure_logging_default(self):
        """Test default logging configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / 'test.log'

            # Remove existing handlers
            logger.remove()

            configure_logging(str(log_file))

            # Test that logging works
            test_logger = get_logger('test-id')
            test_logger.info('Test message')

            # Check log file was created
            assert log_file.exists()

    def test_configure_logging_with_console(self):
        """Test logging configuration with console output."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / 'test.log'

            logger.remove()
            configure_logging(str(log_file), include_console=True)

            # Should not raise any errors
            test_logger = get_logger('test-id')
            test_logger.info('Test console message')

    def test_get_logger_with_correlation_id(self):
        """Test getting logger with correlation ID."""
        test_logger = get_logger('test-correlation-123')

        # Should return a logger (exact type testing would be too implementation-specific)
        assert test_logger is not None

    def test_log_tool_call(self):
        """Test tool call logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / 'test.log'
            logger.remove()
            configure_logging(str(log_file), log_level='DEBUG')

            log_tool_call('find_device', {'identifier': '192.168.1.10'}, 'test-correlation')

            # Verify log file has content
            assert log_file.exists()
            log_content = log_file.read_text()
            assert 'find_device' in log_content

    def test_log_tool_result_success(self):
        """Test successful tool result logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / 'test.log'
            logger.remove()
            configure_logging(str(log_file), log_level='DEBUG')

            log_tool_result(
                'find_device',
                success=True,
                result={'mac': 'aa:bb:cc:dd:ee:ff'},
                correlation_id='test-correlation',
            )

            assert log_file.exists()
            log_content = log_file.read_text()
            assert 'Tool call completed' in log_content

    def test_log_tool_result_failure(self):
        """Test failed tool result logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / 'test.log'
            logger.remove()
            configure_logging(str(log_file), log_level='DEBUG')

            log_tool_result(
                'find_device',
                success=False,
                error='Device not found',
                correlation_id='test-correlation',
            )

            assert log_file.exists()
            log_content = log_file.read_text()
            assert 'Tool call failed' in log_content


class TestEnvironmentVariables:
    """Test environment variable handling in logging."""

    def test_debug_mode_from_env(self):
        """Test debug mode activation from environment."""
        with patch.dict(os.environ, {'UNIFI_MCP_DEBUG': '1'}):
            with tempfile.TemporaryDirectory() as temp_dir:
                log_file = Path(temp_dir) / 'test.log'
                logger.remove()

                # Should enable console logging due to env var
                configure_logging(str(log_file), include_console=False)

                # Hard to test console output, but this should not raise
                test_logger = get_logger()
                test_logger.info('Debug mode test')

    def test_log_levels(self):
        """Test different log levels."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / 'test.log'
            logger.remove()
            configure_logging(str(log_file), log_level='WARNING')

            test_logger = get_logger('test')

            # These should all work without error
            test_logger.debug('Debug message')  # Should not appear
            test_logger.info('Info message')  # Should not appear
            test_logger.warning('Warning message')  # Should appear
            test_logger.error('Error message')  # Should appear

            log_content = log_file.read_text()
            assert 'Warning message' in log_content
            assert 'Error message' in log_content
            # Debug/info should be filtered out at WARNING level
            assert 'Debug message' not in log_content
            assert 'Info message' not in log_content
