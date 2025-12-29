# Quickstart: UniFi Network MCP Server

**Feature**: 001-unifi-mcp-server
**Date**: 2024-12-28

## Prerequisites

- Python 3.12+
- UV package manager
- UniFi controller (UDM Pro Max 4.4.6 or compatible)
- MCP-compatible AI agent (Claude Code, etc.)

## Installation

### 1. Clone and Setup

```bash
cd /Users/ataylor/code/personal/unifi_port_mapper_mcp_server
uv sync
```

### 2. Configure Credentials

Choose one of three methods:

**Option A: Environment Variables (Recommended for CI/CD)**
```bash
export UNIFI_HOST="192.168.1.1"
export UNIFI_USERNAME="admin"
export UNIFI_PASSWORD="your-password"  # pragma: allowlist secret
export UNIFI_SITE="default"  # optional
```

**Option B: macOS Keychain**
```bash
# Store credentials in keychain
python -c "
import keyring
import json
keyring.set_password('unifi-mcp', 'controller', json.dumps({
    'host': '192.168.1.1',
    'username': 'admin',
    'password': 'your-password'  # pragma: allowlist secret
}))
"
```

**Option C: 1Password CLI**
```bash
# Create item in 1Password named "UniFi Controller"
# with fields: host, username, password
op item create --category login \
    --title "UniFi Controller" \
    --vault "Private" \
    host=192.168.1.1 \
    username=admin \
    password=your-password
```

### 3. Verify Installation

```bash
# Run server directly
uv run python -m unifi_mcp.server

# Or test connection
uv run pytest -m "not live" -v
```

## MCP Configuration

### Claude Code

Add to your `mcp.json`:

```json
{
  "mcpServers": {
    "unifi-network": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/ataylor/code/personal/unifi_port_mapper_mcp_server",
        "run",
        "python",
        "-m",
        "unifi_mcp.server"
      ],
      "env": {
        "UNIFI_HOST": "192.168.1.1",
        "UNIFI_USERNAME": "admin",
        "UNIFI_PASSWORD": "${UNIFI_PASSWORD}"
      }
    }
  }
}
```

### Kiro/VSCode

Add to your agent configuration:

```json
{
  "tools": ["unifi-network-mcp-server"],
  "mcpServers": {
    "command": "uv run python -m unifi_mcp.server",
    "workingDirectory": "/Users/ataylor/code/personal/unifi_port_mapper_mcp_server"
  }
}
```

## Basic Usage

### Find a Device

```
User: Find the device at IP 192.168.1.100
Agent: [Uses find_device tool]
Result: Device found - "Office Desktop" (MAC: aa:bb:cc:dd:ee:ff)
        Connected to: Core Switch port 24
        VLAN: 10 (Corporate)
```

### Trace Network Path

```
User: Why can't my CCTV camera reach the NVR?
Agent: [Uses traceroute tool]
Result: Path from Camera (192.168.30.10) to NVR (192.168.30.20):

        ✅ Camera → Switch-Rack1:port12 (VLAN 30)
        ✅ Switch-Rack1:port48 → Core-Switch:port1 (trunk)
        ❌ Core-Switch → BLOCKED by firewall rule "Isolate CCTV"

        💡 Suggestion: Check firewall rule "Isolate CCTV" - it's blocking
        traffic within VLAN 30. Use firewall_check() for details.
```

### Check VLAN Connectivity

```
User: Can the IoT VLAN talk to the Guest VLAN?
Agent: [Uses firewall_check tool]
Result: DENY - IoT (VLAN 20) cannot reach Guest (VLAN 40)

        Matching rules (in order):
        1. "Block IoT to Guest" (deny) - MATCHED
        2. "Allow Established" (allow) - not reached

        💡 This is intentional isolation per best practices.
```

### Audit Port Naming

```
User: Show me any unnamed ports
Agent: [Uses get_port_map tool with audit]
Result:
        | Switch      | Port | Status | Connected Device | Name    | Issue      |
        |-------------|------|--------|------------------|---------|------------|
        | Core-Switch | 12   | Up     | Unknown MAC      | -       | No name    |
        | Core-Switch | 15   | Up     | Printer-Office   | Server1 | Mismatch   |
        | Rack1-SW    | 8    | Up     | AP-Lobby         | -       | No name    |

        💡 3 ports need naming updates. Use port_config() to fix.
```

## Verbosity Modes

### Guided Mode (Default)

Plain English explanations for non-experts:

```
"Port 24 on your main switch is working correctly and connected
to the 'IoT Devices' network. The device on this port is your
Ring doorbell."
```

### Expert Mode

Technical details for network professionals:

```
"Port 1/0/24: state=forwarding, STP=rstp, speed=1000/full,
native_vlan=20, tagged=[1,10,20], poe=at/30W,
mac=aa:bb:cc:dd:ee:ff (Ring-Doorbell)"
```

Toggle with:
```
User: Switch to expert mode
Agent: [Sets verbosity='expert' for subsequent queries]
```

## Common Troubleshooting Workflows

### Connectivity Issues

1. `find_device()` - Verify both endpoints exist
2. `traceroute()` - See the path and find blockers
3. `firewall_check()` - Analyze blocking rules
4. `port_config()` - Check physical port settings

### Performance Issues

1. `system_load()` - Check device health
2. `link_quality()` - Find interface errors
3. `get_port_map()` - Check for duplex mismatches
4. `storm_detector()` - Look for broadcast storms

### Configuration Audit

1. `best_practice_check()` - Overall health check
2. `config_validator()` - Specific validation rules
3. `get_port_map()` - Port naming audit
4. `vlan_info()` - VLAN configuration review

## Testing

```bash
# Unit tests only (no controller needed)
uv run pytest -m "not live" -v

# All tests (requires controller access)
uv run pytest -v

# With coverage
uv run pytest --cov=src/unifi_mcp --cov-report=term-missing
```

## Logs

Logs are written to `~/.unifi-mcp/logs/` in JSON format:

```bash
# View recent logs
tail -f ~/.unifi-mcp/logs/unifi_mcp.log | jq .

# Search for errors
cat ~/.unifi-mcp/logs/unifi_mcp.log | jq 'select(.level == "ERROR")'
```

## Support

- Constitution: `.specify/memory/constitution.md`
- Specification: `specs/001-unifi-mcp-server/spec.md`
- Architecture: `docs/architecture.md` (after MVP-8)
