"""The CLIs' loguru handler and the correlation-id logger helpers.

Every loguru handler in ``src/`` sets ``diagnose=False``: with it on, a logged traceback shows
the failing frames' variable values, which can hold a credential (issue 058).
"""

import os
import sys
from loguru import logger
from typing import Any


def _stderr_sink(message: str) -> None:
    # Resolve sys.stderr on every write, so the handler follows a redirected stream.
    sys.stderr.write(message)


def replace_default_loguru_handler(handler_id: int = 0) -> int | None:
    """Replace loguru's default stderr handler (``diagnose`` on) with one that has it off.

    The CLIs call this before anything logs. Loguru installs its default handler as id 0
    when imported; if that handler is already gone, someone configured loguru on purpose and
    their handlers are left alone. The new handler keeps the default's level
    (``LOGURU_LEVEL``, default ``DEBUG``).

    Args:
        handler_id: The handler to replace; loguru's default is 0.

    Returns:
        The new handler's id, or None when ``handler_id`` was not installed.
    """
    try:
        logger.remove(handler_id)
    except ValueError:
        return None
    level = os.environ.get('LOGURU_LEVEL') or 'DEBUG'
    return logger.add(_stderr_sink, level=level, diagnose=False)


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
