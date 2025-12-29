# UniFi Network MCP Server

MCP server for UniFi network troubleshooting - enables AI agents to diagnose network issues through prescriptive tools.

## Features

- **Discovery**: Find devices by MAC, IP, or hostname
- **Topology**: Visualize network structure with Mermaid diagrams
- **Connectivity**: Trace paths between devices, analyze firewall rules
- **Diagnostics**: Check link quality, detect storms, monitor LAG
- **Configuration**: Inspect VLANs, QoS, port settings, track changes
- **Validation**: Best practice checks, capacity planning

## Installation

```bash
uv sync
```

## Configuration

Set credentials via environment variables:

```bash
export UNIFI_HOST="192.168.1.1"
export UNIFI_USERNAME="admin"
export UNIFI_PASSWORD="your-password"  # pragma: allowlist secret
```

Or use macOS Keychain or 1Password CLI.

## Usage

```bash
uv run python -m unifi_mcp.server
```

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest -m "not live"

# Run linting
uv run ruff check src/
uv run ruff format src/

# Type checking
uv run pyright src/
```

## License

MIT
