"""Markdown export tool for saving results and reports."""

import datetime
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.utils.errors import ToolError


async def export_markdown(
    content: Annotated[Any, Field(description='Content to export as markdown')],
    title: Annotated[str | None, Field(description='Document title')] = None,
    include_timestamp: Annotated[bool, Field(description='Include generation timestamp')] = True,
    include_toc: Annotated[bool, Field(description='Include table of contents')] = False,
) -> str:
    """Export results as formatted markdown document.

    When to use this tool:
    - Creating documentation from network analysis results
    - Saving troubleshooting reports for future reference
    - Generating network audit reports
    - Creating formatted reports to share with team members

    Common workflow:
    1. Gather data from multiple tools (topology, traceroute, etc.)
    2. Use format_table() and render_mermaid() to format sections
    3. Use export_markdown() to combine into comprehensive document
    4. Save or share the resulting markdown document

    What to do next:
    - Save markdown to file for documentation
    - Share with team members for collaborative troubleshooting
    - Include in network documentation or runbooks

    Args:
        content: Content to export - can be:
                - String (direct content)
                - Dictionary (will be formatted as sections)
                - List (will be formatted as sections)
        title: Optional document title
        include_timestamp: Whether to include generation timestamp
        include_toc: Whether to generate table of contents

    Returns:
        Formatted markdown document as string

    Raises:
        ToolError: INVALID_DATA if content cannot be converted to markdown
    """
    try:
        return _build_markdown_document(content, title, include_timestamp, include_toc)
    except Exception as e:
        raise ToolError(
            message=f'Failed to export markdown: {e}',
            error_code='INVALID_DATA',
            suggestion='Check content format and structure',
        )


def _build_markdown_document(
    content: Any,
    title: str | None,
    include_timestamp: bool,
    include_toc: bool,
) -> str:
    """Build complete markdown document."""
    lines = []

    # Add title
    if title:
        lines.extend([f'# {title}', ''])

    # Add timestamp
    if include_timestamp:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        lines.extend([f'*Generated: {timestamp}*', ''])

    # Add table of contents placeholder
    if include_toc:
        lines.extend(['## Table of Contents', '', '<!-- TOC will be generated here -->', ''])

    # Process content based on type
    if isinstance(content, str):
        lines.append(content)

    elif isinstance(content, dict):
        # Format dictionary as sections
        for section_name, section_content in content.items():
            section_title = section_name.replace('_', ' ').title()
            lines.extend([f'## {section_title}', ''])

            if isinstance(section_content, str):
                lines.append(section_content)
            elif isinstance(section_content, (list, dict)):
                lines.append(_format_data_section(section_content))
            else:
                lines.append(str(section_content))

            lines.append('')

    elif isinstance(content, list):
        # Format list as numbered sections
        for i, item in enumerate(content, 1):
            lines.extend([f'## Section {i}', ''])

            if isinstance(item, str):
                lines.append(item)
            elif isinstance(item, dict):
                lines.append(_format_data_section(item))
            else:
                lines.append(str(item))

            lines.append('')

    else:
        # Convert other types to string
        lines.append(str(content))

    # Generate TOC if requested
    if include_toc:
        toc = _generate_toc(lines)
        # Replace TOC placeholder
        markdown_content = '\n'.join(lines)
        markdown_content = markdown_content.replace('<!-- TOC will be generated here -->', toc)
        return markdown_content

    return '\n'.join(lines)


def _format_data_section(data: Any) -> str:
    """Format data section for markdown."""
    if isinstance(data, dict):
        # Format as key-value pairs
        items = []
        for key, value in data.items():
            formatted_key = key.replace('_', ' ').title()
            if isinstance(value, bool):
                formatted_value = '✅ Yes' if value else '❌ No'
            elif isinstance(value, (list, dict)) and len(str(value)) > 100:
                formatted_value = f'`{str(value)[:100]}...`'
            else:
                formatted_value = f'`{value}`' if value is not None else '-'

            items.append(f'- **{formatted_key}**: {formatted_value}')

        return '\n'.join(items)

    elif isinstance(data, list):
        # Format as bullet points
        items = []
        for item in data:
            if isinstance(item, dict):
                # Show first few key-value pairs
                summary = ', '.join(f'{k}: {v}' for k, v in list(item.items())[:3])
                items.append(f'- {summary}')
            else:
                items.append(f'- {item}')

        return '\n'.join(items)

    else:
        return str(data)


def _generate_toc(lines: list[str]) -> str:
    """Generate table of contents from markdown lines."""
    toc_lines = []

    for line in lines:
        if line.startswith('# '):
            # H1 - skip (usually document title)
            continue
        elif line.startswith('## '):
            # H2
            title = line[3:].strip()
            anchor = title.lower().replace(' ', '-').replace('(', '').replace(')', '')
            toc_lines.append(f'- [{title}](#{anchor})')
        elif line.startswith('### '):
            # H3
            title = line[4:].strip()
            anchor = title.lower().replace(' ', '-').replace('(', '').replace(')', '')
            toc_lines.append(f'  - [{title}](#{anchor})')

    return '\n'.join(toc_lines)
