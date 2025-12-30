"""Table formatting tool for structured data display."""

from pydantic import Field
from rich.console import Console
from rich.table import Table
from typing import Annotated
from unifi_mcp.utils.errors import ToolError


async def format_table(
    data: Annotated[list[dict], Field(description='Data to format as table')],
    columns: Annotated[
        list[str] | None, Field(description='Columns to include (defaults to all)')
    ] = None,
    title: Annotated[str | None, Field(description='Table title')] = None,
) -> str:
    """Format data as a rich table with proper alignment and styling.

    When to use this tool:
    - Displaying structured data in readable format
    - Creating reports with device information
    - Formatting port maps, VLAN lists, or device inventories
    - Converting JSON data to human-readable tables

    Common workflow:
    1. Get structured data from other tools (get_port_map, find_device, etc.)
    2. Use format_table() to create readable output
    3. Use export_markdown() to save formatted results
    4. Share formatted reports with team members

    What to do next:
    - Use export_markdown() to save table in documentation
    - Combine with render_mermaid() for comprehensive reports
    - Use in troubleshooting reports for clear data presentation

    Args:
        data: List of dictionaries containing the data to format
        columns: Specific columns to include (defaults to all available columns)
        title: Optional title for the table

    Returns:
        Formatted table as string with proper alignment and borders

    Raises:
        ToolError: INVALID_DATA if data cannot be formatted as table
    """
    if not data:
        return 'No data to display'

    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ToolError(
            message='Data must be a list of dictionaries',
            error_code='INVALID_DATA',
            suggestion='Ensure data is in format: [{"col1": "val1", "col2": "val2"}, ...]',
        )

    try:
        return _generate_rich_table(data, columns, title)
    except Exception as e:
        raise ToolError(
            message=f'Failed to format table: {e}',
            error_code='INVALID_DATA',
            suggestion='Check data structure and column names',
        )


def _generate_rich_table(
    data: list[dict], columns: list[str] | None = None, title: str | None = None
) -> str:
    """Generate rich table using Rich library."""
    console = Console(width=120, legacy_windows=False)

    # Determine columns
    if columns is None:
        # Get all unique columns from data
        all_columns = set()
        for row in data:
            all_columns.update(row.keys())
        columns = sorted(all_columns)

    # Create table
    table = Table(title=title, show_header=True, header_style='bold magenta')

    # Add columns
    for col in columns:
        table.add_column(col.replace('_', ' ').title(), style='cyan', no_wrap=False)

    # Add rows
    for row in data:
        values = []
        for col in columns:
            value = row.get(col, '')

            # Format different types appropriately
            if isinstance(value, bool):
                values.append('✅' if value else '❌')
            elif isinstance(value, (list, dict)):
                values.append(str(value)[:50] + '...' if len(str(value)) > 50 else str(value))
            elif value is None:
                values.append('-')
            else:
                values.append(str(value))

        table.add_row(*values)

    # Capture table output
    with console.capture() as capture:
        console.print(table)

    return capture.get()


async def format_device_table(data: list[dict]) -> str:
    """Format device data with optimized columns."""
    if not data:
        return 'No devices found'

    # Optimized columns for device display
    device_columns = ['name', 'type', 'model', 'ip', 'uptime', 'connected_to']
    return await format_table(data, columns=device_columns, title='Network Devices')


async def format_port_table(data: list[dict]) -> str:
    """Format port data with optimized columns."""
    if not data:
        return 'No ports found'

    # Optimized columns for port display
    port_columns = [
        'device_name',
        'port_idx',
        'name',
        'up',
        'speed',
        'duplex',
        'vlan',
        'connected_device_name',
    ]
    return await format_table(data, columns=port_columns, title='Switch Ports')


async def format_vlan_table(data: list[dict]) -> str:
    """Format VLAN data with optimized columns."""
    if not data:
        return 'No VLANs found'

    # Optimized columns for VLAN display
    vlan_columns = ['id', 'name', 'subnet', 'gateway', 'dhcp_enabled', 'device_count']
    return await format_table(data, columns=vlan_columns, title='Network VLANs')
