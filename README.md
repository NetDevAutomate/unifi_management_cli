# UniFi Management CLI

Enterprise-grade network automation platform with intelligent device discovery, verified configuration management, and comprehensive UniFi Protect integration.

## Overview

This project provides a complete suite of tools for managing UniFi networks:

- **Network Automation**: LLDP/CDP-based discovery with automatic port naming
- **Device Intelligence**: Model-specific capability detection and update strategies
- **Ground Truth Verification**: Multi-read consistency checking prevents false positives
- **61 MCP Tools**: Network health, performance, security diagnostics, STP safety, VLAN checks, SFP/radio analysis, radio optimisation, and Protect inventory
- **UniFi Protect Integration**: Real-time event processing and Home Assistant MQTT bridge
- **MCP Server**: AI-assisted network troubleshooting via Model Context Protocol

## Installation

```bash
# Install dependencies
uv sync

# Install shell completions (optional)
uv run python -m unifi_mapper.cli install-completions bash
# or for zsh:
uv run python -m unifi_mapper.cli install-completions zsh
```

## Configuration

Create configuration file following XDG Base Directory specification:

```bash
mkdir -p ~/.config/unifi_management_cli
cp .env.example ~/.config/unifi_management_cli/prod.env
```

**Required Settings:**

```bash
UNIFI_URL=https://192.0.2.1           # UniFi controller URL
UNIFI_SITE=default                       # Site name (usually 'default')
UNIFI_CONSOLE_API_TOKEN=your_api_token   # Recommended authentication

# Alternative: Username/Password
# UNIFI_USERNAME=admin
# UNIFI_PASSWORD=your_password

UNIFI_VERIFY_SSL=false                   # false for self-signed certificates
UNIFI_TIMEOUT=10                         # API timeout in seconds

# SSH access (for latency matrix and bandwidth tests)
UNIFI_SSH_USERNAME=root                  # SSH user on UDM (default: root)
UNIFI_SSH_PASSWORD=your_ssh_password     # SSH password for gateway
```

## Usage

### Port Mapping

```bash
# Discover network and generate reports (read-only)
unifi-mapper --connected-devices

# Apply port name updates with verification
unifi-mapper --verify-updates --connected-devices

# Dry run - preview changes
unifi-mapper --dry-run --verify-updates
```

### Network Toolkit

```bash
# Network health diagnostics
unifi-network-toolkit diagnose network-health

# Link quality analysis
unifi-network-toolkit analyze link-quality

# Device discovery
unifi-network-toolkit find device "Office"
unifi-network-toolkit find ip 192.0.2.100
```

### STP Optimization

```bash
# Analyze current STP topology
unifi-mapper stp analyze

# Preview optimal priority changes and write a reversible plan
unifi-mapper stp optimize --dry-run
unifi-mapper stp optimize --plan reports/stp-plan.json

# Apply or rollback an approved maintenance-window plan
unifi-mapper stp apply --plan reports/stp-plan.json
unifi-mapper stp rollback reports/stp-plan.json

# Validate 10G readiness, guard placement, drift, and snapshots
unifi-mapper stp validate-10g --planned-switches 2
unifi-mapper stp guard
unifi-mapper stp drift --intent stp_intent.yaml
unifi-mapper stp snapshot --output reports/stp-baseline.json
unifi-mapper stp diff reports/stp-baseline.json

# Generate markdown report
unifi-mapper stp report -o stp-report.md
```

### Device Inventory

```bash
# List devices with upgrade information
unifi-mapper inventory list --filter switch --show-upgrade

# Check for firmware updates
unifi-mapper inventory check-updates
```

### Diagnostics

```bash
# Run all 11 diagnostic checks with pass/warn/fail summary
unifi-mapper diagnose all

# Gateway latency matrix — SSH to UDM, ping all device/client IPs
unifi-mapper diagnose latency-matrix
unifi-mapper diagnose latency-matrix --devices-only --count 5 --timeout 2

# Bandwidth test via iperf3 (requires iperf3 -s on target)
unifi-mapper diagnose bandwidth 192.0.2.50 --bidir --duration 10
unifi-mapper diagnose bandwidth 192.0.2.50 --reverse --parallel 4
```

The `diagnose all` runner checks: link quality, capacity, port profiles, MTU, SFP, radio, firmware skew, DHCP pool, PoE budget, client density, and uplink redundancy.

Latency matrix and bandwidth tests require `UNIFI_SSH_USERNAME` and `UNIFI_SSH_PASSWORD` in your config.

### Radio Management

```bash
# Snapshot current radio configuration (auto-saved before any changes)
unifi-mapper radio snapshot

# Preview optimised radio settings
unifi-mapper radio optimize

# Apply optimised radio settings (auto-snapshots first)
unifi-mapper radio optimize --apply

# Restore previous radio configuration
unifi-mapper radio restore --apply

# Auto-channel optimiser — utilization-weighted channel assignment
unifi-mapper radio auto-channel --band both --apply
unifi-mapper radio auto-channel --band 5ghz --report radio-report.md

# Generate radio optimisation report
unifi-mapper radio report -o radio-report.md
```

The auto-channel optimiser scores 5 GHz channels by measured utilization + DFS penalty + neighbour-AP congestion (RSSI-weighted, CCA-aligned), and distributes 2.4 GHz across channels 1/6/13 accounting for both own-AP utilization and adjacent-channel neighbour interference.

### Analysis Tools

```bash
# Link error rate tracking — baseline snapshot then delta comparison
unifi-mapper analyze link-errors --snapshot
unifi-mapper analyze link-errors --threshold 100

# Client roaming analysis — identify sticky clients and frequent roamers
unifi-mapper analyze roaming --snapshot
unifi-mapper analyze roaming

# Configuration drift detection — snapshot + diff against baseline
unifi-mapper analyze config-drift --snapshot
unifi-mapper analyze config-drift

# Neighbour AP scan — passive detection via stat/rogueap (always-fresh)
unifi-mapper analyze neighbours
unifi-mapper analyze neighbours --ap "Living Room"
```

### Scheduled Audits

```bash
# Install scheduled audit jobs (macOS launchd or Linux crontab)
./scripts/unifi-cron.sh install

# Check schedule status
./scripts/unifi-cron.sh status

# Run all audits immediately
./scripts/unifi-cron.sh run-all

# Update or remove schedules
./scripts/unifi-cron.sh update
./scripts/unifi-cron.sh uninstall
```

Schedules: link errors + roaming every 5 min, config drift + health + radio hourly, port naming every 30 min.

### MCP Server (AI-Assisted Troubleshooting)

The MCP Server enables AI assistants like Claude to directly query and troubleshoot your UniFi network infrastructure using the Model Context Protocol.

**Installation:**

```bash
# Run directly with uvx (recommended)
uvx run unifi-mcp

# Or install and run
uv tool install .
unifi-mcp
```

**Claude Desktop Configuration:**

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "unifi-management": {
      "command": "uvx",
      "args": ["--from", "unifi-management-cli", "unifi-mcp"],
      "env": {
        "UNIFI_URL": "https://192.0.2.1",
        "UNIFI_SITE": "default",
        "UNIFI_CONSOLE_API_TOKEN": "your_api_token",
        "PROTECT_HOST": "192.0.2.1",
        "PROTECT_USERNAME": "admin",
        "PROTECT_PASSWORD": "your_password"
      }
    }
  }
}
```

**Available Tools (61 total):**

| Category | Tools | Description |
|----------|-------|-------------|
| discovery | 4 | Device/IP/MAC location and client tracing |
| diagnostics | 4 | Health checks, performance analysis, security audit |
| connectivity | 4 | Firewall checks, path analysis, traceroute, inter-VLAN endpoint validation |
| network | 6 | Firewall zones/policies, ACLs, DNS, clients, VLANs |
| protect | 5 | Cameras, NVR, sensors, lights, doorbells |
| analysis | 30 | Capacity, link quality, STP, VLAN coverage, SFP, radio, LAG, traffic matrix, drift and change plans |
| radio | 5 | Channel optimization, snapshots, apply/restore radio config |

**Usage Example:**

Ask Claude: "Check the health of my UniFi network" → Claude uses `network_health_check` tool

Ask Claude: "Find all cameras and their status" → Claude uses `get_cameras` tool

Ask Claude: "What devices are connected to my network?" → Claude uses `get_clients` tool

### Advanced Verification

```bash
# Ground truth verification with consistency checking
python -m unifi_mapper.verify_cli --verify-all --consistency-check

# Device capability analysis
python -m unifi_mapper.analyze_network_capabilities
```

## Architecture

The system implements a layered architecture:

```
User Interface Layer
├── CLI Interface (unifi-mapper)
├── Network Toolkit CLI (unifi-network-toolkit)
└── Verification CLI

Intelligence Layer
├── Smart Port Mapper
├── Device Capabilities Database
└── Ground Truth Verifier

API Integration Layer
├── UniFi Network API Client
├── UniFi Protect Client
└── MCP Server (61 tools via FastMCP)

Analysis Toolkit
├── Analysis Tools (30 tools)
├── Diagnostics (4 tools)
├── Discovery (4 tools)
├── Connectivity (4 tools)
├── Network Control (6 wrappers)
└── Protect Integration (5 wrappers)
```

For detailed architecture documentation, see:

- [C4 Architecture Diagrams](docs/architecture/c4-architecture.md) -- All four C4 levels with Mermaid and PlantUML
- [Architecture Overview](docs/architecture/architecture-overview.md) -- Layer deep dives, design patterns, sequence diagrams
- [Codebase Map](docs/architecture/codemap.md) -- Module-by-module reference with dependency graphs
- Provider/platform architecture:
  [UniFi Network](docs/architecture/providers/unifi-network.md),
  [UniFi Protect and MQTT](docs/architecture/providers/unifi-protect-mqtt.md),
  [AXIS provisioning](docs/architecture/providers/axis-provisioning.md),
  [MCP and automation](docs/architecture/providers/mcp-automation.md)

## Key Technical Solutions

### Ground Truth Verification

The UniFi API returns stale cached responses, causing false positive verification. This system implements multi-read consistency checking with cache-busting techniques to detect when the API reports incorrect configuration persistence.

### Device-Aware Intelligence

Different UniFi models have varying port naming support and firmware limitations. The device capability database provides model-specific update strategies, automatically handling restrictions on devices like the US-8-60W and USW Flex series.

### API Cache Dependency Fix

Previous implementations skipped necessary updates because the API reported stale "already correct" names. This version uses LLDP-based update decisions independent of API claims.

## Device Compatibility

| Device Model | Support Level | Notes |
|--------------|---------------|-------|
| USW Flex 2.5G 8 PoE | Full | Reliable API port naming |
| USW-Ultra-210W | Full | Enterprise-grade reliability |
| Dream Machine Pro Max | Full | Gateway with full support |
| USW Flex Mini | Full | Compact switch, full features |
| USW Flex 2.5G 5 | Limited | Network override restrictions |
| US 8 60W | Limited | Port profile auto-reset in some firmware |
| USW Lite 8 PoE | Limited | VLAN selection issues in older firmware |

UniFi Network Application 10.0.162+ resolves most device-level rejection issues.

## Analysis Capabilities

### Analysis Tools
- Capacity Planning: Port utilization forecasting
- Link Quality: Interface error and drop analysis
- Link Error Rate Tracking: Baseline snapshot and delta comparison for active degradation detection
- Client Roaming Analysis: Periodic association snapshots to identify sticky clients and frequent roamers
- Configuration Drift Detection: Full device config snapshot and diff against baseline
- Neighbour AP Scan: Passive neighbour AP detection (always-fresh, no scan trigger needed)
- MAC Address Analysis: MAC table inspection and conflict detection
- VLAN Diagnostics: VLAN configuration validation
- Storm Detection: Broadcast storm identification
- Firmware Advisor: Device firmware compatibility analysis
- IP Conflicts: IP address conflict detection
- LAG Monitoring: Link Aggregation Group status
- QoS Validation: Quality of Service rule verification
- Port Profile Validation: STP Edge and BPDU Guard safety checks
- VLAN Coverage: trunk and planned-uplink VLAN validation
- MTU Audit: MTU and jumbo-frame consistency on inter-switch paths
- SFP Diagnostics: module identity, temperature, Tx/Rx power, and fault flags
- Radio Optimization: AP channel reuse and transmit-power checks
- Traffic Matrix: top-flow and top-talker placement evidence
- STP Optimization: root eligibility, path costs, guard/TCN checks, drift, snapshots, preflight simulation, 10G validation, apply/rollback plans

### Diagnostics Tools
- Network Health: Overall infrastructure health monitoring
- Performance Analysis: Bottleneck identification
- Connectivity Analysis: Connection troubleshooting
- Security Audit: Security configuration review
- Comprehensive Runner: 11-check `diagnose all` with pass/warn/fail summary
- Gateway Latency Matrix: SSH-based ping sweep across all device and client IPs
- Bandwidth Test: iperf3-based throughput measurement via SSH to gateway
- DHCP Pool Analysis: Pool utilization and exhaustion detection
- PoE Budget Analysis: Per-switch PoE consumption vs capacity
- Client Density Analysis: AP client load distribution
- Uplink Redundancy: Multi-path and failover validation

### Discovery Tools
- Find Device: Search by name/IP/MAC
- Find IP: Locate device/port by IP address
- Find MAC: MAC address location tracking
- Client Trace: End-to-end client path analysis

## UniFi Protect Integration

Comprehensive async Python library for UniFi Protect with real-time event processing and Home Assistant integration.

### Features

| Feature | Description |
|---------|-------------|
| Event Analytics | Real-time event correlation and smart detection tracking |
| AI Port Management | Smart detection subscriptions with paired camera tracking |
| Health Monitoring | Proactive device health tracking with configurable thresholds |
| MQTT Bridge | Home Assistant integration with automatic device discovery |

### Basic Usage

```python
from unifi_mapper.protect import ProtectConfig, UniFiProtectClient

config = ProtectConfig(
    host="192.0.2.1",
    username="admin",
    password="your_password",
    verify_ssl=False,
)

async with UniFiProtectClient(config) as client:
    for camera in client.cameras.values():
        print(f"{camera.name}: {camera.state}")
```

### MQTT Bridge for Home Assistant

```python
from unifi_mapper.protect import MQTTBridge, MQTTConfig

mqtt_config = MQTTConfig(
    host="192.0.2.100",
    port=1883,
    topic_prefix="unifi/protect",
    discovery_prefix="homeassistant",
)

async with UniFiProtectClient(protect_config) as client:
    bridge = MQTTBridge(client, mqtt_config)
    await bridge.start()
```

The bridge automatically creates Home Assistant entities for cameras, doorbells, sensors, and smart detections.

## Development

```bash
# Install development dependencies
uv sync --group dev

# Run tests
uv run pytest tests/ -v

# Run linting
uv run ruff check src/
uv run ruff format src/

# Type checking
uv run pyright src/
```

## AXIS Device Provisioning

> For the full provisioning guide including workflow diagrams, configuration reference, and troubleshooting, see [AXIS Provisioning Guide](docs/guides/axis-provisioning.md).

The `scripts/axis_provision.py` script automates AXIS camera and device configuration:

```bash
# Provision all devices from config
uv run python scripts/axis_provision.py

# Preview changes without applying
uv run python scripts/axis_provision.py --dry-run

# Provision specific device
uv run python scripts/axis_provision.py --device Camera 1

# Enable debug logging
uv run python scripts/axis_provision.py --debug
```

**Configuration:** `~/.config/axiscam/config.yaml`

### Firmware Limitations

Cameras with newer AXIS OS firmware (I8016-LVE, M3216-LVE, and similar models) have restricted the legacy VAPIX CGI APIs for user management. On these devices:

- **ONVIF users** must be created manually via the web UI: **System → ONVIF → Add account**
- **MQTT configuration** works via the modern JSON API and provisions correctly

This is an AXIS firmware decision to deprecate legacy APIs in favour of the web interface. The script cannot work around this limitation without AXIS providing a supported API for ONVIF user management.

Older devices (NVR S3008, speakers, legacy cameras) continue to work with full automated provisioning.

## Troubleshooting

> For the full troubleshooting guide with diagnostic flowcharts and operational runbook, see [Troubleshooting and Runbook](docs/operations/troubleshooting-and-runbook.md).
> For step-by-step workflow guides, see [Use Cases and How-To](docs/guides/use-cases-and-howto.md).

**Port names not persisting:**
1. Check device compatibility with `python -m unifi_mapper.analyze_network_capabilities`
2. Use verification: `unifi-mapper --verify-updates`
3. Upgrade to UniFi Network Application 10.0.162+

**API authentication failures:**
1. Verify controller URL and port (443 for UniFi OS, 8443 for legacy)
2. Check API token validity
3. Ensure local controller account (not UniFi Cloud account)

**Verification failures:**
1. Use ground truth verification: `python -m unifi_mapper.verify_cli --consistency-check`
2. Check for device auto-reset behavior
3. Consider manual UI configuration for problematic devices

## Attribution and Acknowledgments

### uiprotect

This project owes significant gratitude to the **[uiprotect](https://github.com/uilibs/uiprotect)** library, an unofficial Python API for UniFi Protect.

The uiprotect library has been invaluable for:

- **Debugging UniFi AI 3rd party camera issues**: Understanding how AI Port detection subscriptions work with non-Ubiquiti cameras
- **AI Port troubleshooting**: Diagnosing smart detection failures and pairing issues
- **Protocol understanding**: Reverse-engineering the UniFi Protect WebSocket event protocol
- **Bootstrap data structures**: Comprehensive models for cameras, sensors, and NVR configurations

**Original Authors and Maintainers:**
- [Bjarne Riis](https://github.com/briis/) - Original creator
- [Christopher Bailey](https://github.com/AngellusMortis/) - Previous maintainer

The uiprotect project demonstrates exceptional reverse-engineering work on an undocumented API, and this project builds upon that foundation for its Protect integration capabilities.

License: MIT

### Additional References

- **[unifi-protect](https://github.com/hjdhjd/unifi-protect)** by [HJD](https://github.com/hjdhjd) - TypeScript UniFi Protect API implementation used as protocol reference (ISC License)

## License

MIT License - See [LICENSE.md](LICENSE.md) for details.

---

Built with systematic debugging and comprehensive UniFi device research.
