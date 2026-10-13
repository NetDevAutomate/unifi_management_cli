"""Print the port-naming compatibility report (``python -m unifi_mapper.analyze_network_capabilities``).

A thin script over :mod:`unifi_mapper.analysis.port_naming_capabilities`, the core that
``unifi-mapper capabilities`` and the MCP tool ``get_port_naming_capabilities`` share. It
reads the config the CLI would (``UNIFI_CONFIG``, then the usual search), not a fixed path.
"""

import asyncio
import sys
from unifi_mapper.analysis.port_naming_capabilities import (
    get_port_naming_capabilities,
    render_text,
)
from unifi_mapper.cli import get_default_config_path, load_env_from_config
from unifi_mapper.core.utils.errors import ToolError
from unifi_mapper.core.utils.redact import redact_text


def main() -> int:
    """Read the devices, print the compatibility report and return the exit code.

    Returns:
        0 on success, 1 when the devices could not be read.
    """
    load_env_from_config(str(get_default_config_path()))
    try:
        report = asyncio.run(get_port_naming_capabilities())
    except ToolError as e:
        print(f'Error: {e.message}', file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - a script: one redacted line, exit 1
        print(f'Error: {redact_text(e)}', file=sys.stderr)
        return 1
    print(render_text(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
