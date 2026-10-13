"""The one place a tool failure's text is capped and redacted (issue 067).

A leaf module: it imports nothing from ``mcp/tools/`` (whose package ``__init__`` loads the
Protect client) or from the runner, so ``mcp/runner.py``, ``mcp/tools/network.py`` and
``mcp/tools/protect.py`` can all import it without a cycle and without loading each other.
"""

from __future__ import annotations

from loguru import logger
from unifi_mapper.core.utils.redact import redact_text


# The runner's cap for a domain error's message and suggestion, and the limit the tool
# wrappers redact their own error text to, so a real message is never cut twice.
ERROR_TEXT_LIMIT = 2000


def tool_failure(action: str, error: Exception) -> str:
    """Log a tool's failure and return its error text, both redacted.

    A lower layer's message can carry a credential, and the server's stderr ends up in the
    MCP client's own logs, so neither the log line nor the returned text shows it raw.

    Args:
        action: What the tool was doing, for the log line (``Failed to <action>: ...``).
        error: The exception the tool caught.

    Returns:
        The error's text, redacted and capped at :data:`ERROR_TEXT_LIMIT`.
    """
    text = redact_text(error, limit=ERROR_TEXT_LIMIT)
    logger.error('Failed to {}: {}', action, text)
    return text
