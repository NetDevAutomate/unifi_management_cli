"""Basic tests to verify environment works."""

import os
import sys


def test_python_version():
    """Test Python version meets requirements."""
    assert sys.version_info >= (3, 12)


def test_src_in_path():
    """Test that src directory is in Python path."""
    src_path = os.path.join(os.getcwd(), 'src')
    # Check if we can access the directory
    assert os.path.exists(src_path)


def test_basic_import():
    """Test basic import without dependencies."""
    # This will fail if the import path is wrong
    try:
        from unifi_mcp.utils.errors import ErrorCodes, ToolError

        assert hasattr(ErrorCodes, 'DEVICE_NOT_FOUND')
        assert issubclass(ToolError, Exception)
    except ImportError as e:
        # If this fails, our package structure has issues
        raise AssertionError(f'Failed to import basic modules: {e}')


def test_model_imports():
    """Test model imports work."""
    try:
        # Test importing without using conftest fixtures
        from unifi_mcp.models.device import Device
        from unifi_mcp.models.port import Port

        # Create simple instances to verify they work
        device = Device(
            mac='aa:bb:cc:dd:ee:ff',
            name='Test',
            model='Test',
            type='switch',
        )
        assert device.mac == 'aa:bb:cc:dd:ee:ff'

        port = Port(port_idx=1)
        assert port.port_idx == 1

    except ImportError as e:
        raise AssertionError(f'Failed to import models: {e}')
