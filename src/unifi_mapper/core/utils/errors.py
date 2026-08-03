"""Error handling utilities following AWS Labs MCP pattern."""


class ToolError(Exception):
    """Structured error for MCP tools."""

    def __init__(
        self,
        message: str,
        error_code: str,
        suggestion: str | None = None,
        related_tools: list[str] | None = None,
    ):
        """Initialize tool error with structured context.

        Args:
            message: Human-readable error description
            error_code: Structured error code (e.g., 'DEVICE_NOT_FOUND')
            suggestion: Optional recovery suggestion for the user
            related_tools: Optional list of tools that might help resolve the issue
        """
        self.message = message
        self.error_code = error_code
        self.suggestion = suggestion
        self.related_tools = related_tools or []
        super().__init__(self._format())

    def _format(self) -> str:
        """Format error message with structured information."""
        parts = [f'[{self.error_code}] {self.message}']

        if self.suggestion:
            parts.append(f'💡 Suggestion: {self.suggestion}')

        if self.related_tools:
            parts.append(f'🔧 Related tools: {", ".join(self.related_tools)}')

        return '\n'.join(parts)

    def to_dict(self) -> dict[str, str | list[str]]:
        """Convert to dictionary for structured logging."""
        return {
            'error_code': self.error_code,
            'message': self.message,
            'suggestion': self.suggestion or '',
            'related_tools': self.related_tools,
        }


# Common error codes for consistency
class ErrorCodes:
    """Standard error codes for UniFi MCP tools."""

    # Device/endpoint errors
    DEVICE_NOT_FOUND = 'DEVICE_NOT_FOUND'
    ENDPOINT_NOT_FOUND = 'ENDPOINT_NOT_FOUND'
    DEVICE_OFFLINE = 'DEVICE_OFFLINE'

    # Controller/connection errors
    CONTROLLER_UNREACHABLE = 'CONTROLLER_UNREACHABLE'
    AUTHENTICATION_FAILED = 'AUTHENTICATION_FAILED'
    API_ERROR = 'API_ERROR'
    TIMEOUT = 'TIMEOUT'

    # Configuration errors
    INVALID_VLAN = 'INVALID_VLAN'
    INVALID_PORT = 'INVALID_PORT'
    INVALID_MAC = 'INVALID_MAC'
    INVALID_IP = 'INVALID_IP'

    # Path/routing errors
    PATH_INCOMPLETE = 'PATH_INCOMPLETE'
    NO_ROUTE = 'NO_ROUTE'
    FIREWALL_BLOCKED = 'FIREWALL_BLOCKED'

    # Configuration errors
    CONFIG_INVALID = 'CONFIG_INVALID'
    BACKUP_NOT_FOUND = 'BACKUP_NOT_FOUND'

    # Data availability errors
    # Referenced by config_drift, roaming_analysis, neighbour_trend,
    # link_error_tracking and latency_matrix. It was never defined here, so every
    # `ErrorCodes.NO_DATA` raised AttributeError instead of the intended ToolError —
    # each of those modules crashed on its own error path (e.g. "no baseline snapshot
    # found") rather than reporting the condition.
    NO_DATA = 'NO_DATA'
