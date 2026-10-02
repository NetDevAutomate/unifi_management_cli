# UniFi Management CLI

Enterprise-grade network automation platform with intelligent device discovery, verified configuration management, and comprehensive UniFi Protect integration.

## Overview

This project provides a complete suite of tools for managing UniFi networks:

- **Network Automation**: LLDP/CDP-based discovery with automatic port naming
- **Device Intelligence**: Model-specific capability detection and update strategies
- **Ground Truth Verification**: Multi-read consistency checking prevents false positives
- **70 MCP Tools**: Network health, performance, security diagnostics, read-only switch-port evidence bundles and event history, STP safety, VLAN checks, SFP/radio analysis, radio optimisation, and Protect inventory
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
# Discover the network and generate reports; port names are only previewed
unifi-mapper --connected-devices

# Write the proposed port names to the controller (explicit opt-in)
unifi-mapper --connected-devices --apply

# Write port name updates and verify that they persisted
unifi-mapper --verify-updates --connected-devices --apply

# Preview with the smart (device-aware) mapper; --dry-run is the default and still accepted
unifi-mapper --dry-run --verify-updates
```

`discover` and its root shortcuts (`--connected-devices`, `--verify-updates`, `--dry-run`)
preview by default, like `ports refresh`: only `--apply` writes port names. Passing both
`--apply` and `--dry-run` is an error (exit 2).

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

5 GHz assignment works over whole 80 MHz blocks (36-48, 52-64, 100-112, 116-128, 132-144, 149-161) rather than primary channels, since two APs sharing a block occupy identical spectrum. Band is derived from the controller's radio id, so tri-band APs (U7 series) report 5 GHz and 6 GHz separately.

### Port Labels

```bash
# Preview port label changes derived from LLDP + wired clients
unifi-mapper ports refresh

# Apply
unifi-mapper ports refresh --apply

# Inspect a single port in depth (link state, LLDP peer, client identity, counters)
unifi-mapper ports inspect "Hotel3 India3 USW Flex 2.5G 5" 2
unifi-mapper ports inspect "Hotel3 India3 USW Flex 2.5G 5" 2 --json
```

`ports inspect` resolves the switch by name, model, IP or MAC and reports everything the
controller holds about one port: link state, the effective port profile and which VLANs it
actually forwards, the native network with its subnet and DHCP pool, the connected device,
an addressing verdict, the LLDP neighbour, the switch's remembered `last_connection`, port
config, PoE and error counters. It warns when cached controller state disagrees with ground
truth, which is the usual reason a port looks down while still carrying traffic.

The connected device is resolved whether or not it is UniFi gear. Adopted devices are named
from the device registry; third-party hosts are reported with their OUI vendor and the
controller's fingerprint model guess, shown alongside its confidence score because that
guess is regularly wrong. LLDP peers are resolved via the same registry, so switches and
access points are named even though they send no `system_name`.

The addressing verdict is what makes an L3-only fault legible:

| Verdict | Meaning |
|---------|---------|
| `leased` | A DHCP lease expiry exists — DHCP is working on this port |
| `static` | An address with no lease, configured on the host itself |
| `no_address` | Client present but unaddressed — suspect the VLAN path or DHCP, not the cable |
| `no_client` | Nothing reporting on the port |

A `no_address` verdict points at the uplink path: check that the native VLAN reaches the
gateway on every hop, and that the switch has been provisioned since the VLAN was created.
The tool also flags a DHCP pool that spans the gateway's own address, which can hand a
client a conflicting address.

Resolves each connected managed switch port, including the integrated LAN/SFP ports on UCG/UDM gateways, to either its LLDP peer or its wired client, and rewrites the label to match. LLDP peers are resolved via the adopted-device registry (`chassis_id`), so access points resolve correctly even though they do not send `system_name` — this is what recovers factory labels such as `PoE Out + Data` on PoE passthrough switches.

Down ports are reverted to their default (`Port N`): a label naming hardware that is no longer plugged in is misinformation. A disconnected port already carrying a factory placeholder such as `PoE Out + Data` or `SFP 1` is left alone, since those say what the port physically is. Four guards prevent bad rewrites:

| Guard | Prevents |
|-------|----------|
| Weak-label protection | `Google Streamer 4K` → `02:00:fe:02:00:0f` when a client stops reporting a hostname |
| Name ranking | A raw MAC representing a multi-client port instead of `Hotel3-Apple-TV +2` |
| Cosmetic-change skip | Churn such as `AI-Port` → `AI Port` |
| `+N` flap suppression | A device that comes and goes oscillating the multi-client counter every run |

Labels are written through `port_overrides`, merged per port, so `poe_mode`, `port_profile` and speed overrides are preserved. Re-running after an apply reports no changes needed.

### Port Diagnostics (read-only)

```bash
# Every port on a switch: speed, duplex, autoneg, profile, LLDP peer, clients, errors
unifi-mapper ports list "Office Flex XG"

# Key-by-key diff of two port profiles, plus every port that uses each one
unifi-mapper ports profile-diff "Access 10G" "Access Auto"

# Where does the controller place a client? Current, offline and historical records
unifi-mapper ports client aa:bb:cc:dd:ee:ff --switch "Office Flex XG" --port 5

# Events, alarms, system log and admin audit for a switch, a port, or a client
unifi-mapper ports events "Office Flex XG" 5 --client aa:bb:cc:dd:ee:ff --since-days 365

# Error counter rates for one port, sampled an inform interval apart, compared with the
# baselines and the recorded counter history (see "Link error baselines and history")
unifi-mapper ports counters "Office Flex XG" 5 --samples 3 --interval 100

# One JSON evidence bundle with all of the above, for a vendor ticket
unifi-mapper ports diagnose "Office Flex XG" 5 --compare-profile "Access 10G" --compare-profile "Access Auto"
```

Every diagnostic command accepts `--json`, resolves the switch by exact name or MAC
before trying a partial name (so `"USW Flex XG"` is not confused with
`"Hotel3 USW Flex XG 10G"`), and takes any switch and any port index.

They are read-only by construction, not by convention: after login the client's HTTP
session is wrapped by a transport guard that allows `GET` (except `cmd/` and `upd/`
paths) and `POST` only to the `stat/event`, `list/alarm` and v2 `system-log` query
endpoints. Anything else, including every `PUT`/`DELETE`, is refused before it leaves
the machine. If the client has to log in again mid-run, the new session is wrapped too.
Secret fields (`x_*`, passwords, tokens, PSKs, passphrases) are removed from every
output, and only their key paths are listed in `sanitised_paths`. These commands read
configuration only from `--config` (or the default config path), never from a stray
`./.env` in the working directory; `ports inspect` follows the same rule.

`ports diagnose` writes `reports/port-diagnostics-<switch>-p<N>-<timestamp>.json` (or
`-o PATH`). The bundle includes `request_audit`, the method and path of every request
made after login (login requests themselves are not listed), as evidence that collection
never wrote to the controller. Undocumented values such as `speed_caps` are reported raw,
alongside the ports that share the same value, rather than decoded by guesswork. Counter
rates are withheld when the device did not inform between samples, since a stale snapshot
would read as zero errors.

### Analysis Tools

```bash
# Link error rate tracking — set a baseline, then compare against it (read only)
unifi-mapper analyze link-errors --snapshot
unifi-mapper analyze link-errors --threshold 100

# Append one counter snapshot of every switch port to the history (the 5-minute cron task)
unifi-mapper analyze link-errors --record --retention-days 14


# Client roaming analysis — identify sticky clients and frequent roamers
unifi-mapper analyze roaming --snapshot
unifi-mapper analyze roaming

# Configuration drift detection — snapshot + diff against baseline
unifi-mapper analyze config-drift --snapshot
unifi-mapper analyze config-drift

# Neighbour AP scan — passive detection via stat/rogueap (always-fresh)
unifi-mapper analyze neighbours
unifi-mapper analyze neighbours --ap "Living Room"

# Neighbour trend tracking — baseline snapshot + diff over time
unifi-mapper analyze neighbours --snapshot
unifi-mapper analyze neighbours --diff
unifi-mapper analyze neighbours --diff --signal-delta 15
```

#### Link error baselines and history

`analyze link-errors` keeps its files under the XDG state directory,
`${XDG_STATE_HOME:-~/.local/state}/unifi_mapper/`, never in the working directory:

| File | Written by | Purpose |
|---|---|---|
| `link-error-baseline.json` | `--snapshot` | The comparison baseline for a plain `analyze link-errors` |
| `port-counters.json` | `--snapshot` | The per-port counter baseline compared by `ports counters`, `ports diagnose` and the MCP port tools |
| `port-counter-history.jsonl` | `--record` | One JSON line per switch per run: every port's error, drop, CRC, link-down and byte counters |

- A plain run only reads. Nothing writes a file unless `--snapshot` or `--record` is given;
  the two can be combined and share one controller read.
- Recording never moves the baseline. Set the baseline deliberately with `--snapshot`
  after a known-good physical state.
- The history keeps `--retention-days` days (default 14, 1-365) and at most 64 MiB; older
  lines are dropped when a run exceeds either cap.
- `ports counters`, `ports diagnose`, `get_port_counter_rates` and `diagnose_switch_port`
  report `baselines.history` for the port: the recorded window, deltas, resets (reboots or
  cleared counters) and `first_increase`, the first sample in which each counter rose.
  They only read it; `ports counters --history PATH` reads another file.
- A baseline left at the old `./reports/link-error-baseline.json` is still read when the
  XDG one does not exist, and is reported as legacy.
- `scripts/unifi-cron.sh` runs `analyze link-errors --record` every 5 minutes (the task is
  still named `link-error-snapshot`).

### Command Reference

Every command on the `unifi-mapper` entry point. All are read-only unless noted.

| Command | Purpose |
|---------|---------|
| `discover` | Discover topology and propose port names with LLDP intelligence (preview by default; `--apply` writes) |
| `diagram` | Generate a topology diagram only, no port renaming |
| `verify` | Port name verification with ground truth checking |
| `capabilities` | Analyze device capabilities for port naming support |
| `version` | Show version information |
| `install-completions` | Install shell completions |
| `find device` | Find a device by name, IP or MAC |
| `ports refresh` | Rewrite port labels from LLDP and wired clients (writes with `--apply`) |
| `ports inspect` | Deep single-port inspection: VLAN, client, addressing, LLDP (`--json` for raw fields) |
| `ports list` | Every port on a switch: speed, negotiation, profile, LLDP peer, clients, errors |
| `ports profile-diff` | Key-by-key diff of two port profiles and the ports using each |
| `ports client` | Where the controller places a client, across current and offline client tables |
| `ports events` | Events, alarms, system log and admin audit for a device, port or client |
| `ports counters` | Sample a port's error counters: per-minute rates with a trust verdict, baselines and recorded history |
| `ports diagnose` | JSON evidence bundle for one port, with a request audit (for vendor tickets) |
| `analyze link-quality` | Port statistics and error rates |
| `analyze link-errors` | Error-rate baseline (`--snapshot`), counter history (`--record`) and read-only delta comparison |
| `analyze port-profiles` | Validate STP Edge, BPDU Guard and uplink safety |
| `analyze vlan-coverage` | VLAN coverage on trunk and planned uplink ports |
| `analyze uplink-transparency` | Whether each elected uplink can carry tagged VLANs |
| `analyze mtu` | MTU consistency across inter-switch links |
| `analyze sfp` | SFP/SFP+ transceiver diagnostics |
| `analyze radio` | Wi-Fi channel and transmit power optimisation |
| `analyze lag-candidates` | Parallel links that may be LACP candidates |
| `analyze power-budget` | Switch *input* power headroom, distinct from PoE output |
| `analyze poe-budget` | PoE *output* budget per switch: drawn vs budget, high-draw ports |
| `analyze uplink-redundancy` | Uplinks per switch; single-uplink switches (single points of failure) |
| `analyze client-density` | Wireless clients per access point, with average signal |
| `analyze dhcp-pools` | DHCP pool utilisation per network (near-exhaustion warnings) |
| `analyze link-speeds` | Fleet-wide ports below their capability, forced-speed traps and half duplex (exit 2 on HIGH) |
| `analyze port-profile-usage` | Where each port profile is used; forced-speed, shadowing, dangling, duplicate and unused profiles |
| `analyze traffic-matrix` | Top flows and top talkers |
| `analyze roaming` | Sticky clients and frequent roamers |
| `analyze config-drift` | Full device config snapshot and diff |
| `analyze neighbours` | Passive neighbour AP detection and trend |
| `diagnose all` | Run every diagnostic with a pass/warn/fail summary |
| `diagnose health` | Overall network health check |
| `diagnose inter-vlan` | Inter-VLAN routing and firewall verdict between two endpoints |
| `diagnose latency-matrix` | SSH to the gateway and ping every device |
| `diagnose bandwidth` | iperf3 throughput test via the gateway |
| `inventory list` | List devices with upgrade information |
| `inventory check-updates` | Check for firmware updates |
| `inventory firmware-skew` | Report firmware version skew by model |
| `inventory update-firmware` | Update device firmware (writes) |
| `stp analyze` | Current STP topology and root eligibility |
| `stp optimize` | Preview or plan optimal priority changes |
| `stp apply` | Apply an approved change plan (writes) |
| `stp rollback` | Revert a previously applied plan (writes) |
| `stp preflight` | Simulate adding planned switches and report expected root state |
| `stp validate-10g` | Validate 10G readiness before adding switches |
| `stp guard` | Guard placement checks |
| `stp drift` | Compare live STP state against an intent file |
| `stp snapshot` | Capture an STP baseline |
| `stp diff` | Diff live state against a baseline |
| `stp report` | Generate a markdown STP report |
| `radio snapshot` | Snapshot radio configuration |
| `radio optimize` | Preview or apply optimised radio settings (writes with `--apply`) |
| `radio restore` | Restore a previous radio configuration (writes with `--apply`) |
| `radio auto-channel` | Utilization-weighted channel assignment (writes with `--apply`) |
| `radio report` | Generate a radio optimisation report |

Run any command with `--help` for its options.

> Invoke commands through the installed `unifi-mapper` script. `python -m unifi_mapper.typer_cli`
> also works, and a test asserts both paths expose the same command set.

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

**Available Tools (70 total):**

| Category | Tools | Description |
|----------|-------|-------------|
| discovery | 5 | Device/IP/MAC location, client tracing and client history |
| diagnostics | 8 | Health checks, performance analysis, security audit, single-port inspection, all-ports view, port profile diff, port evidence bundle |
| observability | 2 | Event, alarm, system-log and admin-audit history; port counter rates |
| connectivity | 4 | Firewall checks, path analysis, traceroute, inter-VLAN endpoint validation |
| network | 6 | Firewall zones/policies, ACLs, DNS, clients, VLANs |
| protect | 5 | Cameras, NVR, sensors, lights, doorbells |
| analysis | 40 | Capacity, link quality, STP, VLAN coverage, SFP, radio, LAG, traffic matrix, drift and change plans |

**Usage Example:**

Ask Claude: "Check the health of my UniFi network" → Claude uses `network_health_check` tool

Ask Claude: "Why isn't the device on port 2 of my office switch getting an IP?" → Claude uses `inspect_switch_port` tool

Ask Claude: "Collect evidence on why port 5 of my Flex XG won't link at 10G" → Claude uses `diagnose_switch_port` tool

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
└── MCP Server (70 tools via FastMCP)

Analysis Toolkit
├── Analysis Tools (40 tools)
├── Diagnostics (8 tools)
├── Discovery (5 tools)
├── Observability (2 tools)
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
- Switch Port Evidence Bundle: read-only `diagnose_switch_port` with raw port entry, override, profiles, clients, history, counters and a request audit
- All-Ports View: every port on a switch with negotiation, profile, LLDP peer and counters
- Port Profile Diff: key-by-key comparison of two port profiles and where each is used

### Discovery Tools
- Find Device: Search by name/IP/MAC
- Find IP: Locate device/port by IP address
- Find MAC: MAC address location tracking
- Client Trace: End-to-end client path analysis
- Client History: where the controller places a client, across current and offline client tables

### Observability Tools
- Device Events: events, alarms, system log and admin audit for a device, port or client, with observed retention per source
- Port Counter Rates: sampled error/CRC/link-down rates with a verdict that refuses false zeros from a stale device

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
2. Use verification: `unifi-mapper --verify-updates --apply`
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
