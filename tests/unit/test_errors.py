"""Unit tests for error handling."""

from unifi_mcp.utils.errors import ErrorCodes, ToolError


class TestToolError:
    """Test ToolError class."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = ToolError(
            message='Something went wrong',
            error_code='TEST_ERROR',
        )
        assert error.error_code == 'TEST_ERROR'
        assert error.message == 'Something went wrong'
        assert error.suggestion is None
        assert error.related_tools == []

    def test_error_with_suggestion(self):
        """Test error with suggestion."""
        error = ToolError(
            message='Device not found',
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion='Check if device is online',
        )
        assert error.suggestion == 'Check if device is online'

    def test_error_with_related_tools(self):
        """Test error with related tools."""
        error = ToolError(
            message='Device not found',
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            related_tools=['find_device', 'get_network_topology'],
        )
        assert error.related_tools == ['find_device', 'get_network_topology']

    def test_error_formatting_basic(self):
        """Test basic error formatting."""
        error = ToolError(
            message='Test error',
            error_code='TEST',
        )
        expected = '[TEST] Test error'
        assert str(error) == expected

    def test_error_formatting_with_suggestion(self):
        """Test error formatting with suggestion."""
        error = ToolError(
            message='Test error',
            error_code='TEST',
            suggestion='Try this fix',
        )
        expected = '[TEST] Test error\n💡 Suggestion: Try this fix'
        assert str(error) == expected

    def test_error_formatting_complete(self):
        """Test error formatting with all fields."""
        error = ToolError(
            message='Device not found',
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion='Check device status',
            related_tools=['find_device', 'ping'],
        )
        expected = (
            '[DEVICE_NOT_FOUND] Device not found\n'
            '💡 Suggestion: Check device status\n'
            '🔧 Related tools: find_device, ping'
        )
        assert str(error) == expected

    def test_error_to_dict(self):
        """Test error conversion to dictionary."""
        error = ToolError(
            message='Test message',
            error_code='TEST_CODE',
            suggestion='Test suggestion',
            related_tools=['tool1', 'tool2'],
        )

        result = error.to_dict()
        expected = {
            'error_code': 'TEST_CODE',
            'message': 'Test message',
            'suggestion': 'Test suggestion',
            'related_tools': ['tool1', 'tool2'],
        }
        assert result == expected

    def test_error_to_dict_minimal(self):
        """Test error dictionary with minimal fields."""
        error = ToolError(
            message='Test message',
            error_code='TEST_CODE',
        )

        result = error.to_dict()
        expected = {
            'error_code': 'TEST_CODE',
            'message': 'Test message',
            'suggestion': '',
            'related_tools': [],
        }
        assert result == expected


class TestErrorCodes:
    """Test error code constants."""

    def test_error_codes_exist(self):
        """Test that all expected error codes are defined."""
        assert hasattr(ErrorCodes, 'DEVICE_NOT_FOUND')
        assert hasattr(ErrorCodes, 'CONTROLLER_UNREACHABLE')
        assert hasattr(ErrorCodes, 'AUTHENTICATION_FAILED')
        assert hasattr(ErrorCodes, 'API_ERROR')
        assert hasattr(ErrorCodes, 'PATH_INCOMPLETE')
        assert hasattr(ErrorCodes, 'FIREWALL_BLOCKED')

    def test_error_codes_are_strings(self):
        """Test that error codes are strings."""
        assert isinstance(ErrorCodes.DEVICE_NOT_FOUND, str)
        assert isinstance(ErrorCodes.API_ERROR, str)

    def test_error_codes_values(self):
        """Test specific error code values."""
        assert ErrorCodes.DEVICE_NOT_FOUND == 'DEVICE_NOT_FOUND'
        assert ErrorCodes.CONTROLLER_UNREACHABLE == 'CONTROLLER_UNREACHABLE'
        assert ErrorCodes.AUTHENTICATION_FAILED == 'AUTHENTICATION_FAILED'
