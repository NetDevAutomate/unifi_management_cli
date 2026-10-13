# Architecture

The overview, the C4 model and the codebase map live beside this file:

- [architecture-overview.md](architecture-overview.md): components, data flow and the safety
  model (read-only guards, redaction, preview-by-default writes)
- [c4-architecture.md](c4-architecture.md): C4 context, container and component diagrams
- [codemap.md](codemap.md): every module and command, generated-shape, for contributors
- [providers/](providers/): the UniFi Network, Protect/MQTT, AXIS and MCP provider notes

The short version that used to open the README follows.

# Architecture

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
└── MCP Server (96 tools via the MCP SDK's FastMCP)

Analysis Toolkit
├── Analysis Tools (57 tools)
├── Diagnostics (11 tools)
├── Discovery (5 tools)
├── Observability (7 tools)
├── Connectivity (4 tools)
├── Network Control (6 wrappers)
└── Protect Integration (5 wrappers)
```

For detailed architecture documentation, see:

- [C4 Architecture Diagrams](../architecture/c4-architecture.md) -- All four C4 levels with Mermaid and PlantUML
- [Architecture Overview](../architecture/architecture-overview.md) -- Layer deep dives, design patterns, sequence diagrams
- [Codebase Map](../architecture/codemap.md) -- Module-by-module reference with dependency graphs
- Provider/platform architecture:
  [UniFi Network](../architecture/providers/unifi-network.md),
  [UniFi Protect and MQTT](../architecture/providers/unifi-protect-mqtt.md),
  [AXIS provisioning](../architecture/providers/axis-provisioning.md),
  [MCP and automation](../architecture/providers/mcp-automation.md)

# Key Technical Solutions

## Ground Truth Verification

The UniFi API returns stale cached responses, causing false positive verification. This system implements multi-read consistency checking with cache-busting techniques to detect when the API reports incorrect configuration persistence.

## Device-Aware Intelligence

Different UniFi models have varying port naming support and firmware limitations. The device capability database provides model-specific update strategies, automatically handling restrictions on devices like the US-8-60W and USW Flex series.

## API Cache Dependency Fix

Previous implementations skipped necessary updates because the API reported stale "already correct" names. This version uses LLDP-based update decisions independent of API claims.

# Device Compatibility

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

# Analysis Capabilities

## Analysis Tools
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

## Diagnostics Tools
- Network Health: Overall infrastructure health monitoring
- Performance Analysis: Bottleneck identification
- Connectivity Analysis: Connection troubleshooting
- Security Audit: Security configuration review
- Comprehensive Runner: 15-check `diagnose all` with pass/warn/fail summary
- Gateway Latency Matrix: SSH-based ping sweep across all device and client IPs
- Bandwidth Test: iperf3-based throughput measurement via SSH to gateway
- DHCP Pool Analysis: Pool utilization and exhaustion detection
- PoE Budget Analysis: Per-switch PoE consumption vs capacity
- Client Density Analysis: AP client load distribution
- Uplink Redundancy: Multi-path and failover validation
- Switch Port Evidence Bundle: read-only `diagnose_switch_port` with raw port entry, override, profiles, clients, history, counters and a request audit
- All-Ports View: every port on a switch with negotiation, profile, LLDP peer and counters
- Port Profile Diff: key-by-key comparison of two port profiles and where each is used

## Discovery Tools
- Find Device: Search by name/IP/MAC
- Find IP: Locate device/port by IP address
- Find MAC: MAC address location tracking
- Client Trace: End-to-end client path analysis
- Client History: where the controller places a client, across current and offline client tables

## Observability Tools
- Device Events: events, alarms, system log and admin audit for a device, port or client, with observed retention per source
- Port Counter Rates: sampled error/CRC/link-down rates with a verdict that refuses false zeros from a stale device
- Device Stats: one device's CPU, memory, load, uptime, per-radio utilisation and per-VAP TX counters
- AP Retry Rates: every AP's reset-aware per-VAP retry percentage over an interval (blocks up to 240 s)
- Config Objects: raw WLAN, network, setting and AP-group objects with every secret key removed
- Recent Config Changes: objects created in a window, newest first, from the time each object's ID records
- Recent Events: site-wide events, alarms and system-log entries from the last N hours, with category, severity and text filters
