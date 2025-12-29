"""Unit tests for utility tools (simplified for environment)."""

import os
import sys


# Add src to path for imports
src_path = os.path.join(os.getcwd(), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def test_utility_tools_import():
    """Test that utility tools can be imported."""
    try:
        from unifi_mcp.tools.utility import __all__

        expected_tools = ['export_markdown', 'format_table', 'render_mermaid']
        assert set(__all__) == set(expected_tools)
    except ImportError as e:
        assert False, f'Cannot import utility module: {e}'


def test_format_table_imports():
    """Test format table tool import."""
    try:
        from unifi_mcp.tools.utility.format_table import format_table

        assert callable(format_table)
    except ImportError as e:
        assert False, f'Cannot import format_table: {e}'


def test_render_mermaid_imports():
    """Test render mermaid tool import."""
    try:
        from unifi_mcp.tools.utility.render_mermaid import render_mermaid

        assert callable(render_mermaid)
    except ImportError as e:
        assert False, f'Cannot import render_mermaid: {e}'


def test_export_markdown_imports():
    """Test export markdown tool import."""
    try:
        from unifi_mcp.tools.utility.export_markdown import export_markdown

        assert callable(export_markdown)
    except ImportError as e:
        assert False, f'Cannot import export_markdown: {e}'


def test_mermaid_helpers():
    """Test mermaid diagram helper functions."""
    try:
        from unifi_mcp.tools.utility.render_mermaid import _get_vlan_id_from_name

        # Mock VLAN data
        vlans = [
            {'id': 10, 'name': 'Corporate'},
            {'id': 20, 'name': 'Guest'},
            {'id': 30, 'name': 'IoT'},
        ]

        # Test VLAN ID lookup
        assert _get_vlan_id_from_name('Corporate', vlans) == 10
        assert _get_vlan_id_from_name('Guest', vlans) == 20
        assert _get_vlan_id_from_name('Unknown', vlans) == 1  # Default

    except ImportError as e:
        assert False, f'Cannot import mermaid helpers: {e}'


def test_markdown_generation_helpers():
    """Test markdown generation utilities."""
    try:
        from unifi_mcp.tools.utility.export_markdown import _format_data_section

        # Test dictionary formatting
        test_dict = {
            'name': 'Test Device',
            'type': 'switch',
            'enabled': True,
            'ports': 48,
        }

        result = _format_data_section(test_dict)
        assert isinstance(result, str)
        assert 'Test Device' in result
        assert '✅' in result  # Boolean formatting

        # Test list formatting
        test_list = ['item1', 'item2', 'item3']
        result = _format_data_section(test_list)
        assert isinstance(result, str)
        assert 'item1' in result

    except ImportError as e:
        assert False, f'Cannot import markdown helpers: {e}'


def test_table_formatting_helpers():
    """Test table formatting utilities."""
    try:
        from unifi_mcp.tools.utility.format_table import _generate_rich_table

        # Test basic table generation
        test_data = [
            {'name': 'Device1', 'type': 'switch', 'ip': '192.168.1.10'},
            {'name': 'Device2', 'type': 'ap', 'ip': '192.168.1.20'},
        ]

        result = _generate_rich_table(test_data)
        assert isinstance(result, str)
        assert len(result) > 0
        assert 'Device1' in result
        assert 'Device2' in result

    except ImportError as e:
        assert False, f'Cannot import table helpers: {e}'
