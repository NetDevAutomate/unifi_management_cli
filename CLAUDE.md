# UniFi Management CLI Development Guidelines

## Overview

Enterprise-grade UniFi network automation platform with intelligent device discovery, verified configuration management, and UniFi Protect integration.

## Technology Stack

- Python 3.12+
- Pydantic >= 2.10 (data validation)
- httpx (async HTTP client)
- Loguru >= 0.7.0 (logging)
- rich (TUI/tables)
- keyring (macOS Keychain credentials)
- typer (CLI framework)
- uiprotect >= 7.0.0 (UniFi Protect API)

## Project Structure

```text
src/
└── unifi_mapper/      # Main CLI application
    ├── analysis/      # Network analysis tools
    ├── connectivity/  # Path analysis, traceroute
    ├── core/          # Core models and utilities
    │   ├── models/    # Pydantic models
    │   └── utils/     # Client, auth, errors
    ├── diagnostics/   # Health, performance, security
    ├── discovery/     # Device/IP/MAC discovery
    ├── network/       # Network control plane (VLANs, firewall, etc.)
    └── protect/       # UniFi Protect integration

tests/
├── network/           # Network control plane tests
├── protect/           # UniFi Protect tests
└── ...
```

## Commands

```bash
# Development
uv sync --group dev
uv run pytest tests/ -v
uv run ruff check src/
uv run ruff format src/
uv run pyright src/

# CLI tools
unifi-mapper                  # Port mapping and inventory
unifi-network-toolkit         # Network analysis toolkit
unifi-inventory               # Device inventory
```

## Configuration

Config location: `~/.config/unifi_management_cli/prod.env`

## Code Style

- Python 3.12+ with type annotations
- Google-style docstrings
- Single quotes for strings (ruff format)
- Line length: 99 characters

## Development Workflow

- Never commit automatically after completing tasks
- Run tests before marking work complete
- Use ground truth verification for API-related changes
