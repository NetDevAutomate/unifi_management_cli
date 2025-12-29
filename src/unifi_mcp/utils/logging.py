"""Structured JSON logging configuration."""

import os
import sys
from loguru import logger
from pathlib import Path
from typing import Any


def configure_logging(
    log_file: str | None = None,
    log_level: str = 'DEBUG',
    include_console: bool = False,
) -> None:
    """Configure structured JSON logging.

    Args:
        log_file: Path to log file (defaults to ~/.unifi-mcp/logs/unifi_mcp.log)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        include_console: Whether to also log to console
    """
    # Remove default handler
    logger.remove()

    # Create log directory
    if not log_file:
        log_dir = Path.home() / '.unifi-mcp' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = str(log_dir / 'unifi_mcp.log')

    # JSON file logging with rotation
    logger.add(
        log_file,
        format='{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {extra[correlation_id]} | {message}',
        serialize=True,  # JSON output
        rotation='10 MB',
        retention='7 days',
        compression='gz',
        level=log_level,
        backtrace=True,
        diagnose=True,
    )

    # Optional console logging for development
    if include_console or os.getenv('UNIFI_MCP_DEBUG'):
        logger.add(
            sys.stderr,
            format='<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>',
            level=log_level,
            colorize=True,
        )

    # Set default correlation ID
    logger.configure(extra={'correlation_id': ''})


def get_logger(correlation_id: str = '') -> Any:
    """Get logger with correlation ID for request tracing.

    Args:
        correlation_id: Unique identifier for tracking requests

    Returns:
        Logger instance with correlation ID bound
    """
    return logger.bind(correlation_id=correlation_id)


def log_tool_call(tool_name: str, params: dict[str, Any], correlation_id: str = '') -> None:
    """Log MCP tool call with parameters.

    Args:
        tool_name: Name of the tool being called
        params: Tool parameters
        correlation_id: Request correlation ID
    """
    log = get_logger(correlation_id)
    log.info('Tool call started', tool=tool_name, params=params)


def log_tool_result(
    tool_name: str,
    success: bool,
    result: Any = None,
    error: str | None = None,
    correlation_id: str = '',
) -> None:
    """Log MCP tool call result.

    Args:
        tool_name: Name of the tool
        success: Whether tool call succeeded
        result: Tool result (logged only if success=True)
        error: Error message (logged only if success=False)
        correlation_id: Request correlation ID
    """
    log = get_logger(correlation_id)

    if success:
        log.info('Tool call completed', tool=tool_name, result_type=type(result).__name__)
    else:
        log.error('Tool call failed', tool=tool_name, error=error)
