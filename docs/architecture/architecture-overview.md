# UniFi Management CLI - Architecture Overview

**Document version**: 1.1
**Last updated**: 2026-05-03
**Codebase root**: `src/unifi_mapper/`

> **See also**: [C4 Architecture](c4-architecture.md) | [Codebase Map](codemap.md) | [Use Cases](../guides/use-cases-and-howto.md) | [Troubleshooting](../operations/troubleshooting-and-runbook.md)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Layered Architecture](#2-layered-architecture)
3. [Layer 1: User Interface](#3-layer-1-user-interface)
4. [Layer 2: Intelligence](#4-layer-2-intelligence)
5. [Layer 3: API Integration](#5-layer-3-api-integration)
6. [Layer 4: Analysis Toolkit](#6-layer-4-analysis-toolkit)
7. [Layer 5: Network Control Plane](#7-layer-5-network-control-plane)
8. [Layer 6: Protect Integration](#8-layer-6-protect-integration)
9. [Layer 7: Core Domain](#9-layer-7-core-domain)
10. [Layer 8: SSH Integration](#10-layer-8-ssh-integration)
11. [Layer 9: Scheduling and Automation](#11-layer-9-scheduling-and-automation)
12. [Design Patterns](#12-design-patterns)
13. [Key Workflows (Sequence Diagrams)](#13-key-workflows-sequence-diagrams)
14. [Module Dependency Graph](#14-module-dependency-graph)
15. [External Interfaces](#15-external-interfaces)
16. [Configuration and Credential Management](#16-configuration-and-credential-management)

---

## 1. System Overview

The UniFi Management CLI is an enterprise-grade Python automation platform for managing UniFi networks. It solves three distinct operational problems:

- **Topology discovery and port naming**: LLDP-driven automatic port labelling with device-aware capability detection.
- **Network diagnostics**: 40+ analysis and diagnostic tools covering IP conflicts, STP, VLANs, QoS, performance, security, DHCP pools, PoE budgets, client density, uplink redundancy, latency, radio configuration, roaming, and configuration drift.
- **AI-assisted troubleshooting**: An MCP server exposing the full tool surface to Claude and other AI agents for natural-language network operations.

The platform is delivered as four CLI entry points plus an MCP server, all installed from a single Python package:

| Entry point | Module | Framework |
| --- | --- | --- |
| `unifi-mapper` | `typer_cli.py` | Typer + Rich |
| `unifi-network-toolkit` | `network_cli.py` | argparse |
| `unifi-inventory` | `inventory_cli.py` | argparse |
| `unifi-mcp` | `mcp/server.py` | FastMCP |

---

## 2. Layered Architecture

The system is organised into nine layers. Dependencies flow strictly downward; the only upward flow is return values and events.

```mermaid
graph TB
    subgraph UI["Layer 1 - User Interface"]
        TC["typer_cli.py\nunifi-mapper"]
        NC["network_cli.py\nunifi-network-toolkit"]
        IC["inventory_cli.py\nunifi-inventory"]
        MCP["mcp/server.py\nunifi-mcp"]
    end

    subgraph SCHED["Layer 9 - Scheduling"]
        CRON["unifi-cron.sh\nlaunchd / crontab"]
    end

    subgraph INT["Layer 2 - Intelligence"]
        SPM["smart_port_mapper.py\nDevice-Aware Port Naming"]
        PM["port_mapper.py\nTopology Building"]
        DC["device_capabilities.py\nCapability Database"]
        GTV["ground_truth_verification.py\nCache-Bust Verification"]
        NT["enhanced_network_topology.py\nDiagram Generation"]
    end

    subgraph API["Layer 3 - API Integration"]
        AC["api_client.py\nUniFi Network REST"]
        EAC["enhanced_api_client.py\nExtended Methods"]
        PC["protect/client.py\nAsync Protect WebSocket"]
        TA["toolkit_adapters.py\nAdapter Bridge"]
        CFG["config.py\nConfiguration"]
    end

    subgraph AT["Layer 4 - Analysis Toolkit"]
        AN["analysis/ (42 registered tools)"]
        DG["diagnostics/ (4 tools)"]
        DS["discovery/ (4 tools)"]
        CN["connectivity/ (4 registered tools)"]
    end

    subgraph SSH["Layer 8 - SSH Integration"]
        SSHL["asyncssh\nGateway SSH tunnel"]
        PING["Latency matrix\nping via UDM"]
        IPERF["Bandwidth test\niperf3 via UDM"]
    end

    subgraph NCP["Layer 5 - Network Control Plane"]
        NW["network/ module\nacl, firewall, dns, dpi\nclient, vlan, statistics"]
    end

    subgraph PR["Layer 6 - Protect Integration"]
        PE["protect/events.py\nWebSocket Events"]
        PQ["protect/mqtt.py\nHome Assistant Bridge"]
        PAI["protect/aiport.py\nONVIF AI Port"]
        PAN["protect/analytics.py\nEvent Analytics"]
        PRE["protect/repository.py\nDevice Cache"]
    end

    subgraph CD["Layer 7 - Core Domain"]
        MD["models.py\nPortInfo, DeviceInfo"]
        CM["core/models/\nPydantic typed models"]
        CU["core/utils/\nauth, client, errors, logging"]
        EX["exceptions.py\nException hierarchy"]
    end

    SCHED -->|"invokes CLI"| UI
    UI --> INT
    UI --> API
    UI --> AT
    INT --> API
    INT --> CD
    API --> CD
    AT --> API
    AT --> SSH
    AT --> NCP
    AT --> CD
    NCP --> API
    PR --> PC
    PR --> CD
    MCP --> AT
    MCP --> PR
    SSH --> CD
```

---

## 3. Layer 1: User Interface

### Component diagram

```mermaid
graph LR
    subgraph typer_cli["typer_cli.py - unifi-mapper"]
        APP["app: Typer\n(root)"]
        CMD_DISCOVER["discover\nLLDP topology + port naming"]
        CMD_FIND["find\nDevice / IP / MAC / client"]
        CMD_ANALYZE["analyze\nLink quality / VLANs / STP / QoS\nlink-errors / roaming / config-drift / neighbours"]
        CMD_DIAGNOSE["diagnose\nHealth / perf / connectivity\nall / latency-matrix / bandwidth"]
        CMD_STP["stp\nSTP topology and optimization"]
        CMD_RADIO["radio\nsnapshot / optimize / restore\nauto-channel / report"]
        CMD_INV["inventory\nDevice management"]
        CMD_VFY["verify\nPort update verification"]
        CMD_DIAG["diagram\nGraphviz / Mermaid output"]
        CMD_CAP["capabilities\nDevice capability report"]
    end

    subgraph network_cli["network_cli.py - unifi-network-toolkit"]
        NC_MAIN["main() argparse"]
        NC_DISC["discover"]
        NC_AN["analyze"]
        NC_FIND["find"]
        NC_DIAG["diagnose"]
    end

    subgraph mcp_server["mcp/server.py - unifi-mcp"]
        MCP_SEARCH["search_tools()"]
        MCP_LIST["list_categories()"]
        MCP_INFO["get_tool_info()"]
        REGISTRY["ToolRegistry\nYAML manifests"]
    end

    subgraph cli_shared["cli.py - shared entry point"]
        XDG["get_default_config_path()\nXDG Base Dir"]
        LOAD["load_env_from_config()"]
    end

    APP --> CMD_DISCOVER
    APP --> CMD_FIND
    APP --> CMD_ANALYZE
    APP --> CMD_DIAGNOSE
    APP --> CMD_STP
    APP --> CMD_RADIO
    APP --> CMD_INV
    APP --> CMD_VFY
    APP --> CMD_DIAG
    APP --> CMD_CAP

    cli_shared --> typer_cli
    cli_shared --> network_cli

    MCP_SEARCH --> REGISTRY
    MCP_LIST --> REGISTRY
    MCP_INFO --> REGISTRY
```

### typer_cli.py

The primary CLI, `unifi-mapper`, is built with [Typer](https://typer.tiangolo.com/) and uses Rich for terminal output. All subcommands share a `State` singleton for the config path and debug flag:

```python
class State:
    """Global CLI state."""
    config_path: Optional[Path] = None
    debug: bool = False

state = State()

app = typer.Typer(
    name="unifi-mapper",
    rich_markup_mode="rich",
    invoke_without_command=True,
)
```

The root callback intercepts `--connected-devices`, `--dry-run`, and `--verify-updates` flags so users can invoke the discover workflow without explicitly naming the subcommand.

### cli.py (shared entry point)

`cli.py` is the shared foundation consumed by both `typer_cli.py` and `network_cli.py`. It provides:

- **XDG Base Directory resolution** for config files — searches `$XDG_CONFIG_HOME/unifi_management_cli/` before falling back to `.env` in the current directory.
- **`load_env_from_config(path)`** — reads a `.env` file and injects each key-value pair into `os.environ`.

### MCP Server (mcp/server.py)

The `unifi-mcp` server is built on FastMCP. It exposes three public discovery meta-tools that implement the Code Mode pattern (see [Section 12](#12-design-patterns)):

| Tool | Purpose |
| --- | --- |
| `search_tools` | Discover tools by query, category, or tag |
| `list_categories` | Enumerate all category groups |
| `get_tool_info` | Fetch full parameter schema for a named tool |

The MCP server does not hard-code any domain logic. It delegates discovery to the `ToolRegistry` and underlying YAML manifests. Executable `ToolProxy` objects are available through the registry for host code and tests; they are not currently a public FastMCP `execute_tool` surface.

### New CLI command groups (v1.1)

**`radio` subcommand group** — manages Wi-Fi radio configuration with reversible operations:

| Command | Module | Purpose |
| --- | --- | --- |
| `radio snapshot` | `analysis/radio_config.py` | Backup current AP radio settings to JSON |
| `radio optimize` | `analysis/radio_config.py` | Apply optimised radio settings (auto-snapshots first) |
| `radio restore` | `analysis/radio_config.py` | Restore a previous radio snapshot |
| `radio auto-channel` | `analysis/channel_optimiser.py` | Utilization-weighted channel assignment |
| `radio report` | `analysis/channel_optimiser.py` | Generate markdown radio optimisation report |

**New `diagnose` commands** — comprehensive diagnostics runner and gateway-level tools:

| Command | Module | Purpose |
| --- | --- | --- |
| `diagnose all` | 11 analysis modules | Run all checks with pass/warn/fail summary table |
| `diagnose latency-matrix` | `analysis/latency_matrix.py` | SSH to UDM, ping all device/client IPs |
| `diagnose bandwidth` | `analysis/bandwidth_test.py` | iperf3 throughput test via SSH to gateway |

**New `analyze` commands** — time-series analysis with snapshot/compare pattern:

| Command | Module | Purpose |
| --- | --- | --- |
| `analyze link-errors` | `analysis/link_error_tracking.py` | Baseline snapshot + delta comparison |
| `analyze roaming` | `analysis/roaming_analysis.py` | Client-to-AP association tracking |
| `analyze config-drift` | `analysis/config_drift.py` | Device config snapshot + diff |
| `analyze neighbours` | `analysis/neighbour_scan.py` | RF spectrum scan for external networks |

---

## 4. Layer 2: Intelligence

This layer contains the domain-specific reasoning that goes beyond raw API calls: understanding device limitations, verifying API responses, building topology graphs.

```mermaid
graph TD
    subgraph intelligence["Intelligence Layer"]
        SPM["SmartPortMapper\nsmart_port_mapper.py"]
        DC["DeviceCapabilityDetector\ndevice_capabilities.py"]
        GTV["GroundTruthVerifier\nground_truth_verification.py"]
        PM["UnifiPortMapper\nport_mapper.py"]
        NT["NetworkTopology\nenhanced_network_topology.py"]
    end

    SPM -->|"detect_capabilities(model, fw)"| DC
    SPM -->|"verify_port_updates_ground_truth()"| GTV
    SPM -->|"update_port_overrides()"| API_CLIENT["api_client"]
    PM -->|"owns"| API_CLIENT
    PM -->|"builds"| NT
    GTV -->|"multi-read check"| API_CLIENT
```

### smart_port_mapper.py

`SmartPortMapper` is the orchestration class for LLDP-driven port naming. It:

1. Calls `DeviceCapabilityDetector` to determine whether a device supports port naming at all.
2. Constructs port name proposals from LLDP data.
3. Applies updates via the API client using the correct write field (`port_overrides`, not `port_table`).
4. Optionally calls `GroundTruthVerifier` to confirm persistence.

```python
class SmartPortMapper:
    def __init__(self, api_client):
        self.api_client = api_client
        self.capability_detector = DeviceCapabilityDetector()

    def smart_update_ports(
        self,
        devices_data: List[Dict],
        lldp_data: Dict[str, Dict],
        verify_updates: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        ...
```

### device_capabilities.py

Encodes community-researched knowledge about UniFi device firmware quirks into a structured capability database:

```python
class PortNamingSupport(Enum):
    FULL_SUPPORT = "full"
    UI_ONLY = "ui_only"
    LIMITED = "limited"
    RESETS_AUTOMATICALLY = "resets"
    NOT_SUPPORTED = "none"

@dataclass
class DeviceCapability:
    model: str
    firmware_version: str
    port_naming_support: PortNamingSupport
    known_issues: List[str]
    workarounds: List[str]
    api_endpoint_restrictions: List[str]
    max_port_name_length: Optional[int] = 32
    supports_port_profiles: bool = True
```

Known device issues are keyed by `(model_code, firmware_version)` tuples. A wildcard `"*"` firmware matches all versions. This allows the system to skip unsafe operations (e.g., firmware 7.2.123 on US-8-60W automatically resets port profiles and cycles PoE ports).

### ground_truth_verification.py

The UniFi API caches device state aggressively. After a port-override write, the API may return the old value for several seconds or indefinitely. `GroundTruthVerifier` addresses this with two strategies:

**Strategy 1: Multi-read consistency check**
Reads the same port name N times with configurable delays, adding cache-busting HTTP headers on each request. Consistency across reads (all N reads agree on the new value) is used as the verification signal.

**Strategy 2: Browser verification (optional)**
Uses browser automation against the UniFi controller UI, which reads directly from the controller's internal state rather than the cached API layer. This requires credentials and is opt-in.

```python
def _multi_read_consistency_check(
    self, device_id, port_idx, expected_name,
    num_reads=5, delay_between_reads=2.0
) -> Dict[str, Any]:
    # Cache-busting headers added per read:
    self.api_client.session.headers.update({
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "X-Cache-Bust": str(int(time.time() * 1000)),
    })
```

### enhanced_network_topology.py

Wraps `DeviceInfo` and `PortInfo` objects into a graph and renders diagrams via Graphviz (PNG/SVG/DOT) or produces Mermaid markup directly. `network_topology.py` is a thin re-export shim so existing code imports continue to work without modification.

---

## 5. Layer 3: API Integration

### API layer components

```mermaid
graph TD
    subgraph api_layer["API Integration Layer"]
        AC["UnifiApiClient\napi_client.py\n(requests, sync)"]
        EAC["EnhancedUnifiApiClient\nenhanced_api_client.py\n(requests + httpx, sync)"]
        PC["UniFiProtectClient\nprotect/client.py\n(httpx + uiprotect, async)"]
        UC["UniFiClient\ncore/utils/client.py\n(httpx, async)"]
        TA["ToolkitAdapter\ntoolkit_adapters.py\n(bridges sync/async)"]
        CFG["UnifiConfig\nconfig.py"]
        CRED["Credentials\ncore/utils/auth.py"]
    end

    CFG -->|"from_env()"| AC
    CRED -->|"from_env()\nfrom_keychain()\nfrom_onepassword()"| UC
    UC -->|"used by"| AT["Analysis Toolkit"]
    AC -->|"used by"| INT["Intelligence Layer"]
    EAC -->|"extends"| AC
    TA -->|"adapts"| AC
    TA -->|"used by"| MCP["MCP Server"]
    PC -->|"wraps"| UIPROTECT["uiprotect library"]
```

### UnifiApiClient (api_client.py)

The primary synchronous client for the UniFi Network REST API.

**Dual endpoint detection**: The client probes both the UniFi OS path (`/proxy/network/api/...`) and the legacy path (`/api/...`) during login, storing the working endpoint for subsequent requests.

**Authentication strategies**:

| Strategy | HTTP mechanism | Preferred for |
| --- | --- | --- |
| API token | `X-API-KEY` header | UniFi OS (UDM, UDR, UDM SE) |
| Username + password | Session cookie (POST `/api/login`) | Legacy controllers |

**Retry with exponential backoff**: The `_retry_request()` method wraps every outbound call. It respects the retryable vs permanent distinction in the exception hierarchy — authentication failures (401/403) and bad-request errors (4xx) are not retried; server errors (5xx), timeouts, and connection failures are retried up to `max_retries` with `delay * 2^attempt` spacing.

```python
def _retry_request(self, func, *args, **kwargs):
    for attempt in range(self.max_retries):
        try:
            return func(*args, **kwargs)
        except Timeout as e:
            delay = self.retry_delay * (2 ** attempt)
            time.sleep(delay)
        except HTTPError as e:
            if e.response.status_code in [401, 403]:
                raise UniFiAuthenticationError(...)  # No retry
            ...
```

**Input sanitisation**: All values passed to the API are validated before use. Logging helpers (`_sanitize_for_logging`, `_hash_for_verification`) ensure credentials are never written to log output.

### EnhancedUnifiApiClient (enhanced_api_client.py)

Extends `UnifiApiClient` with additional methods for port configuration, provisioning, and statistics. Also imports `httpx` for async-capable endpoints where needed alongside the synchronous `requests` session.

### UniFiProtectClient (protect/client.py)

A fully async wrapper around the `uiprotect` library's `ProtectApiClient`. Manages:

- A `ConnectionState` finite state machine: `DISCONNECTED → CONNECTING → CONNECTED ⇄ RECONNECTING → ERROR`.
- Context manager lifecycle (`__aenter__` / `__aexit__`) for clean resource management.
- WebSocket subscription plumbing for real-time event delivery.
- Typed property accessors for all Protect device types: cameras, AI ports, sensors, lights, chimes, door locks.

```python
async with UniFiProtectClient(config) as client:
    cameras = client.cameras        # dict[str, Camera]
    ai_ports = client.ai_ports      # dict[str, AiPort]
    bootstrap = client.bootstrap    # full Bootstrap snapshot
```

### UniFiClient (core/utils/client.py)

A second async client built with `httpx` for use by the analysis toolkit. Consumes credentials from the `get_credentials()` fallback chain (see Section 16). This client follows the async context manager pattern and is the standard client for all toolkit tools.

### ToolkitAdapter (toolkit_adapters.py)

The adapter bridges the async-capable toolkit with the synchronous `UnifiApiClient` used by older CLI paths. It wraps each toolkit function in a synchronous `_sync` variant that fetches data directly from the API client without requiring an async event loop.

---

## 6. Layer 4: Analysis Toolkit

The toolkit is 42 individual async functions organised across four sub-packages plus an SSH integration layer. All tools are registered via YAML manifests and exposed through the MCP server.

### Tool inventory

```mermaid
graph TD
    subgraph analysis["analysis/ (42 registered tools)"]
        direction LR
        subgraph original["Original Tools"]
            A1["detect_ip_conflicts"]
            A2["detect_storms"]
            A3["diagnose_vlans"]
            A4["analyze_link_quality"]
            A5["get_capacity_report"]
            A6["monitor_lags"]
            A7["validate_qos"]
            A8["analyze_mac_table"]
            A9["get_firmware_report"]
            A10["STP suite (5 tools)\ndiscover, optimize, report\napply, format"]
        end
        subgraph new_infra["Infrastructure Health (new)"]
            N1["check_dhcp_pool_utilization"]
            N2["check_poe_budget"]
            N3["analyze_client_density"]
            N4["check_uplink_redundancy"]
        end
        subgraph new_radio["Radio Management (new)"]
            N5["snapshot_radio_config"]
            N6["apply_radio_config"]
            N7["restore_radio_config"]
            N8["analyze_channels\n(channel_optimiser)"]
            N9["optimize_channels\n(channel_optimiser)"]
        end
        subgraph new_ssh["SSH-Based (new)"]
            N10["run_latency_matrix\n(asyncssh → UDM → ping)"]
            N11["run_bandwidth_test\n(asyncssh → UDM → iperf3)"]
        end
        subgraph new_timeseries["Time-Series Analysis (new)"]
            N12["snapshot_link_errors\ncompare_link_errors"]
            N13["snapshot_client_associations\nanalyze_roaming"]
            N14["snapshot_config\ncompare_config"]
            N15["scan_neighbours"]
        end
    end

    subgraph diagnostics["diagnostics/ (4 tools)"]
        D1["analyze_connectivity"]
        D2["check_network_health"]
        D3["analyze_performance"]
        D4["run_security_audit"]
    end

    subgraph discovery["discovery/ (4 tools)"]
        DS1["find_device"]
        DS2["find_ip"]
        DS3["find_mac"]
        DS4["trace_client"]
    end

    subgraph connectivity["connectivity/ (4 registered tools)"]
        C1["check_firewall_path"]
        C2["analyze_path"]
        C3["traceroute"]
    end
```

### New analysis module categories

The 12 new analysis modules fall into four functional groups:

**Infrastructure health** — single-shot checks that return a Pydantic report:

| Module | Function | Returns |
| --- | --- | --- |
| `dhcp_pool.py` | `check_dhcp_pool_utilization()` | `DHCPPoolReport` — per-network pool size, active clients, exhaustion warnings |
| `poe_budget.py` | `check_poe_budget()` | `PoEBudgetReport` — per-switch PoE consumption vs capacity |
| `client_density.py` | `analyze_client_density()` | `ClientDensityReport` — per-AP client count, avg signal, overload flags |
| `uplink_redundancy.py` | `check_uplink_redundancy()` | `UplinkRedundancyReport` — single-uplink SPOF detection |

**Radio management** — snapshot/apply/restore lifecycle:

| Module | Functions | Purpose |
| --- | --- | --- |
| `radio_config.py` | `snapshot_radio_config`, `apply_radio_config`, `restore_radio_config` | Reversible AP radio changes |
| `channel_optimiser.py` | `analyze_channels`, `optimize_channels` | Utilization-weighted channel assignment with DFS penalty scoring |

**SSH-based tools** — require `asyncssh` and gateway SSH credentials:

| Module | Function | Purpose |
| --- | --- | --- |
| `latency_matrix.py` | `run_latency_matrix()` | SSH to UDM, ping all device/client IPs, build RTT/loss matrix |
| `bandwidth_test.py` | `run_bandwidth_test()` | SSH to UDM, run iperf3 to target, report throughput |

**Time-series analysis** — snapshot/compare pattern with JSON baselines:

| Module | Functions | Purpose |
| --- | --- | --- |
| `link_error_tracking.py` | `snapshot_link_errors`, `compare_link_errors` | Port error counter deltas to distinguish active degradation from historical |
| `roaming_analysis.py` | `snapshot_client_associations`, `analyze_roaming` | Track client-to-AP associations over time, identify sticky clients |
| `config_drift.py` | `snapshot_config`, `compare_config` | Full device config snapshot + diff against baseline |
| `neighbour_scan.py` | `scan_neighbours` | RF spectrum scan for external networks per channel |

### YAML manifest pattern

Each category has a manifest file under `mcp/manifests/`. The manifest declares the tool's module path, handler function, description, priority, and tags. This decouples tool metadata from implementation and allows the MCP server to serve discovery without importing any tool code at startup.

```yaml
# mcp/manifests/analysis.yaml
category: analysis
tools:
  detect_ip_conflicts:
    module: unifi_mapper.analysis.ip_conflicts
    handler: detect_ip_conflicts
    description: Find IP address conflicts between devices on the network
    priority: P1
    tags: [ip, conflict, layer3, diagnostic]
```

Priority levels (`P1` through `P3`) help AI agents decide which tools to invoke first when investigating a reported symptom.

### Tool implementation pattern

Every analysis tool follows the same four-phase pattern:

```mermaid
flowchart LR
    A["async function\n(public API)"] --> B["UniFiClient\n(async context manager)"]
    B --> C["Pure analysis\n(no I/O, testable)"]
    C --> D["Pydantic model\n(typed return)"]
```

1. **Async entry point**: The public function is always `async def`. CLI commands wrap it with `asyncio.run()`.
2. **Data fetch via `UniFiClient`**: All API calls happen inside an `async with UniFiClient() as client:` block. The client handles auth, retries, and session cleanup.
3. **Pure analysis**: A private `_analyze_*()` function receives raw API dicts and returns structured results. This function has no I/O — it is pure computation and fully unit-testable.
4. **Pydantic model return**: The result is always a typed Pydantic v2 model from `core/models/`, ensuring consistent serialisation for CLI, MCP, and test consumers.

```python
# Canonical pattern (all 12 new modules follow this exactly)
async def check_dhcp_pool_utilization() -> DHCPPoolReport:
    async with UniFiClient() as client:
        networks = await client.get_networks()
        clients = await client.get_clients()

    pools, warnings, recs = _analyze_dhcp_pools(networks, clients)
    return DHCPPoolReport(pools=pools, warnings=warnings, ...)
```

**SSH-based tools** extend this pattern by adding an `asyncssh` connection phase between data fetch and analysis:

```python
async def run_latency_matrix(...) -> LatencyMatrixReport:
    creds = Credentials.from_env()
    async with UniFiClient() as client:
        devices = await client.get_devices()       # Phase 2: API fetch
    targets = _build_target_list(devices, ...)      # Phase 3: pure analysis
    results = await _ping_targets_via_ssh(creds, targets, ...)  # SSH phase
    return LatencyMatrixReport(results=results, ...)  # Phase 4: Pydantic model
```

**Time-series tools** use a snapshot/compare variant where the first call writes a JSON baseline and the second call diffs against it:

```python
# Snapshot phase (writes baseline)
async def snapshot_link_errors(output_path: str) -> dict:
    async with UniFiClient() as client:
        devices = await client.get_devices()
    snapshot = _build_snapshot(devices)
    Path(output_path).write_text(json.dumps(snapshot))
    return snapshot

# Compare phase (reads baseline, fetches current, diffs)
async def compare_link_errors(baseline_path: str, threshold: int) -> dict:
    async with UniFiClient() as client:
        devices = await client.get_devices()
    baseline = json.loads(Path(baseline_path).read_text())
    return _compute_deltas(baseline, _build_snapshot(devices), threshold)
```

---

## 7. Layer 5: Network Control Plane

The `network/` sub-package models the writable configuration objects of the UniFi controller. It is used by both the CLI and the analysis toolkit for configuration reads and writes.

```mermaid
graph LR
    subgraph network_module["network/ module"]
        ACL["acl.py\nACL rules"]
        FW["firewall.py\nFirewall policies"]
        DNS["dns.py\nDNS records"]
        DPI["dpi.py\nDPI signatures"]
        CLI_MOD["client.py\nClient management"]
        CLIENTS["clients.py\nClient listing"]
        CFG_MOD["config.py\nSite configuration"]
        MOD["models.py\nShared data models"]
        NET["networks.py\nNetwork/VLAN definitions"]
        SITES["sites.py\nSite management"]
        STATS["statistics.py\nDevice statistics"]
        TM["traffic_matching.py\nTraffic rules"]
    end
```

This layer maps directly to the UniFi controller's API resource hierarchy: each module corresponds to one or more REST endpoints and provides typed Python access to create, read, update, and delete those resources.

---

## 8. Layer 6: Protect Integration

The Protect integration is a self-contained subsystem for real-time camera and sensor management.

### Protect subsystem components

```mermaid
graph TD
    subgraph protect_subsystem["protect/ subsystem"]
        CLIENT["UniFiProtectClient\nclient.py\nLifecycle + WebSocket"]
        CFG["ProtectConfig\nconfig.py"]
        EVENTS["EventHandler\nevents.py\nWS subscriptions + filtering"]
        MQTT["MQTTBridge\nmqtt.py\nHome Assistant MQTT"]
        AIPORT["AIPortManager\naiport.py\nONVIF AI detection"]
        ANALYTICS["EventAnalytics\nanalytics.py\nAggregation + correlation"]
        REPO["DeviceRepository\nrepository.py\nGeneric device cache"]
        HEALTH["protect/health.py\nHealth monitoring"]
        MODELS["protect/models.py\nProtectCamera, ProtectAIPort\nProtectDevice, etc."]
    end

    CLIENT -->|"wraps"| UIPROTECT["uiprotect.ProtectApiClient\n(external library)"]
    CLIENT -->|"exposes bootstrap to"| REPO
    CLIENT -->|"feeds events to"| EVENTS
    EVENTS -->|"filtered events to"| MQTT
    EVENTS -->|"filtered events to"| ANALYTICS
    AIPORT -->|"subscribes via"| EVENTS
    REPO -->|"typed by"| MODELS
    CFG -->|"configures"| CLIENT
```

### Connection state FSM

```mermaid
stateDiagram-v2
    [*] --> DISCONNECTED
    DISCONNECTED --> CONNECTING : connect() called
    CONNECTING --> CONNECTED : authentication + bootstrap OK
    CONNECTING --> ERROR : auth failure
    CONNECTED --> RECONNECTING : WebSocket disconnect
    RECONNECTING --> CONNECTED : reconnect OK
    RECONNECTING --> ERROR : max retries exceeded
    ERROR --> CONNECTING : explicit reconnect
    CONNECTED --> DISCONNECTED : close() called
```

### Event pipeline

```mermaid
graph LR
    WS["UniFi Protect\nWebSocket"]
    BOOTSTRAP["Bootstrap\ncomplete device inventory"]
    EH["EventHandler\nevent dispatching"]
    FILTER["EventFilter\nevent_types, device_ids\ncategories"]
    SUB["Subscriber callbacks\nregistered by consumers"]
    MQTT_B["MQTTBridge\npublish to broker"]
    HA["Home Assistant\nMQTT Discovery"]

    WS -->|"WSSubscriptionMessage"| EH
    BOOTSTRAP -->|"initial state"| EH
    EH -->|"ProtectEvent"| FILTER
    FILTER -->|"matching events"| SUB
    SUB -->|"via MQTTBridge"| MQTT_B
    MQTT_B -->|"homeassistant/ topics"| HA
```

### DeviceRepository pattern

`DeviceRepository[T]` is a generic, typed cache for any Protect device type. Each concrete device type gets its own typed repository instance, providing O(1) lookup by device ID and type-safe iteration:

```python
T = TypeVar('T', bound=ProtectDevice)

class DeviceRepository(Generic[T]):
    def add(self, device: T) -> None: ...
    def get(self, device_id: str) -> T | None: ...
    def all(self) -> list[T]: ...
    def filter(self, predicate: Callable[[T], bool]) -> list[T]: ...
```

### AI Port management

`AIPortManager` in `aiport.py` wraps the Protect AI Port devices, which are hardware modules that add UniFi smart detection (person, vehicle, animal, face, licence plate, smoke) to third-party ONVIF cameras. It tracks paired cameras, manages capability configuration, and subscribes to the event stream for real-time detection events.

---

## 9. Layer 7: Core Domain

### models.py (legacy domain objects)

The original domain objects used by the intelligence layer. Plain Python classes (not Pydantic) because they predate the Pydantic migration:

| Class | Role |
| --- | --- |
| `PortInfo` | Single switch port: index, name, media, speed, LLDP data, proposed name |
| `DeviceInfo` | Network device with list of `PortInfo`, LLDP neighbours |
| `PortHealthMetrics` | Error counters and utilisation stats for a port |
| `DeviceHealthMetrics` | Aggregated health for a device |
| `NetworkHealthStatus` | Network-wide health roll-up |
| `NetworkTopologyChange` | A detected change to the topology |
| `NetworkConfiguration` | Immutable snapshot of a site configuration |
| `NetworkAnalysisResult` | Output type for analysis runs |

### core/models/ (Pydantic typed models)

Newer Pydantic v2 models used by the analysis toolkit and MCP tools. These models are the standard for all new code:

```mermaid
classDiagram
    class Device {
        mac: str
        name: str
        model: str
        ip: str | None
        type: switch|ap|gateway|client
        uptime: int
        connected_to: str | None
        port_idx: int | None
        is_infrastructure: bool
        display_name: str
    }

    class Port {
        port_idx: int
        name: str
        media: str
        speed: int
        is_uplink: bool
        poe_enabled: bool
    }

    class VLANInfo {
        vlan_id: int
        name: str
        subnet: str | None
        gateway: str | None
        enabled: bool
    }

    class STPInfo {
        bridge_id: str
        priority: int
        root_bridge: bool
        port_states: dict
    }

    Device "1" --> "*" Port
```

### core/utils/

| Module | Purpose |
| --- | --- |
| `auth.py` | `Credentials` Pydantic model + `get_credentials()` fallback chain |
| `client.py` | `UniFiClient` async httpx client used by toolkit |
| `errors.py` | `ToolError` structured exception + `ErrorCodes` constants |
| `logging.py` | Loguru configuration helpers |

### exceptions.py

The exception hierarchy classifies all API errors into retryable and permanent categories, enabling the retry logic in `UnifiApiClient` to make correct decisions without inspecting HTTP status codes in every call site:

```mermaid
graph TD
    EX["Exception"]
    BASE["UniFiApiError"]
    RET["UniFiRetryableError\n(5xx, timeouts, connection)"]
    PERM["UniFiPermanentError\n(4xx client errors)"]

    BASE --> RET
    BASE --> PERM

    RET --> CON["UniFiConnectionError"]
    RET --> TO["UniFiTimeoutError"]
    RET --> RL["UniFiRateLimitError"]

    PERM --> AUTH["UniFiAuthenticationError\n+ auth_method, status_code"]
    PERM --> VAL["UniFiValidationError"]
    PERM --> PRIV["UniFiPermissionError"]

    EX --> BASE
```

---

## 10. Layer 8: SSH Integration

Two analysis tools require direct SSH access to the UDM gateway to execute commands that cannot be performed via the REST API. Both use `asyncssh` for non-blocking SSH sessions.

```mermaid
graph TD
    subgraph ssh_layer["SSH Integration Layer"]
        LM["latency_matrix.py\nrun_latency_matrix()"]
        BW["bandwidth_test.py\nrun_bandwidth_test()"]
        CREDS["Credentials.from_env()\n+ UNIFI_SSH_USERNAME\n+ UNIFI_SSH_PASSWORD"]
    end

    subgraph gateway["UDM Pro Max (SSH target)"]
        PING["ping -c N -W T <ip>"]
        IPERF["iperf3 -c <ip> -t D -P P -J"]
    end

    LM -->|"asyncssh.connect()"| PING
    BW -->|"asyncssh.connect()"| IPERF
    CREDS --> LM
    CREDS --> BW
```

**Why SSH?** The UniFi REST API provides no endpoint for active probing (ping, traceroute, iperf3). SSH to the gateway is the only way to measure real latency and throughput from the network's vantage point — analogous to running `show ip route` or `ping` from a router's CLI in traditional networking.

**Connection pattern**: Both tools use `asyncssh.connect()` with `known_hosts=None` (self-signed UDM certs) and `preferred_auth='keyboard-interactive,password'`. Credentials come from `UNIFI_SSH_USERNAME` / `UNIFI_SSH_PASSWORD` environment variables, falling back to the main controller password.

**Latency matrix** SSHs once, then runs `ping -c {count} -W {timeout} {ip}` for each target IP sequentially, parsing RTT stats from stdout. Returns a `LatencyMatrixReport` with per-target `LatencyResult` entries.

**Bandwidth test** SSHs once, runs `iperf3 -c {target} -t {duration} -P {parallel} -J` (JSON output mode), and parses the structured result. Supports `--reverse` for download testing and `--bidir` for bidirectional.

---

## 11. Layer 9: Scheduling and Automation

`scripts/unifi-cron.sh` provides cross-platform scheduled execution of audit tasks. It is a standalone shell script with no Python dependencies — it invokes `uv run unifi-mapper` subcommands.

```mermaid
graph TD
    subgraph scheduler["unifi-cron.sh"]
        INSTALL["install\nCreate scheduled tasks"]
        UNINSTALL["uninstall\nRemove scheduled tasks"]
        STATUS["status\nShow task status"]
        RUNALL["run-all\nManual trigger"]
    end

    subgraph platform["Platform Adapters"]
        LAUNCHD["macOS\nlaunchd plist files\n~/Library/LaunchAgents/"]
        CRONTAB["Linux\ncrontab entries\nmarked with # UNIFI-MANAGEMENT-CLI"]
    end

    subgraph tasks["Scheduled Tasks"]
        T1["link-error-snapshot\nevery 5 min"]
        T2["client-roaming-snapshot\nevery 5 min"]
        T3["config-drift-check\nevery hour"]
        T4["diagnose-all\nevery hour"]
        T5["radio-report\nevery hour"]
        T6["port-naming\nevery 30 min"]
    end

    INSTALL --> LAUNCHD
    INSTALL --> CRONTAB
    LAUNCHD --> tasks
    CRONTAB --> tasks
```

**Schedule summary**:

| Task | Interval | CLI command |
| --- | --- | --- |
| Link error snapshot | 5 min | `analyze link-errors --snapshot` |
| Client roaming snapshot | 5 min | `analyze roaming --snapshot` |
| Config drift check | 1 hour | `analyze config-drift` |
| Full diagnostics | 1 hour | `diagnose all` |
| Radio report | 1 hour | `radio report -o reports/channel-report.md` |
| Port naming | 30 min | `--verify-updates --connected-devices` |

The scheduler writes logs to `$PROJECT_DIR/logs/` with one log file per task. On macOS, each task is a launchd plist under `~/Library/LaunchAgents/com.unifi-management.{name}.plist`. On Linux, entries are appended to the user's crontab with a `# UNIFI-MANAGEMENT-CLI` marker for clean uninstall.

---

## 12. Design Patterns

### Adapter Pattern (toolkit_adapters.py)

The analysis toolkit is async-first. The legacy CLI path (older `cli.py` and `network_cli.py`) is synchronous. `ToolkitAdapter` wraps each async toolkit function in a synchronous variant, extracting data from the synchronous `UnifiApiClient` and building the same output structures:

```python
class ToolkitAdapter:
    def __init__(self, api_client):
        self.api_client = api_client

    def find_device_sync(self, query: str) -> List[Dict[str, Any]]:
        """Synchronous device search (adapts async discovery to sync client)."""
        devices_response = self.api_client.get_devices(self.api_client.site)
        ...
```

This allows the synchronous CLI to use the same tool logic as the async MCP server without requiring an event loop.

### Strategy Pattern

**Authentication strategy**: `UnifiApiClient` selects the authentication method at construction time based on which credentials are present. The `auth_method` attribute records the active strategy (`"token"` or `"username_password"`). The same attribute propagates into `UniFiAuthenticationError` for diagnostic context.

**Port update strategy**: `SmartPortMapper` consults `DeviceCapabilityDetector` before each device to select the appropriate update path (skip entirely, use minimal overrides, use full override). This replaces a brittle if-else chain with a data-driven capability database.

**Credential resolution strategy**: `get_credentials()` in `core/utils/auth.py` implements a priority-ordered fallback chain — environment variables, then macOS Keychain via `keyring`, then 1Password CLI:

```python
async def get_credentials() -> Credentials:
    # 1. Environment variables (UNIFI_URL, UNIFI_CONSOLE_API_TOKEN, etc.)
    try:
        return Credentials.from_env()
    except ToolError:
        pass

    # 2. macOS Keychain via keyring
    keychain_data = keyring.get_password('unifi-mcp', 'controller')
    if keychain_data:
        return Credentials.from_keychain(keychain_data)

    # 3. 1Password CLI
    process = await asyncio.create_subprocess_exec('op', 'item', 'get', ...)
    ...
```

### Repository Pattern (protect/repository.py)

`DeviceRepository[T]` provides a type-safe, in-memory store for Protect device objects. The generic type parameter enforces that cameras cannot be stored in a sensor repository and vice versa:

```python
class DeviceRepository(Generic[T]):
    def __init__(self, device_type: DeviceType) -> None:
        self._device_type = device_type
        self._devices: dict[str, T] = {}

    def get(self, device_id: str) -> T | None:
        return self._devices.get(device_id)

    def filter(self, predicate: Callable[[T], bool]) -> list[T]:
        return [d for d in self._devices.values() if predicate(d)]
```

### Lazy Loading / Proxy Pattern (mcp/registry.py)

`ToolProxy` defers importing a tool's implementation module until the first `execute()` call. This keeps MCP server startup fast even though 61 tools are registered -- only the YAML manifests are parsed at startup:

```python
class ToolProxy:
    def __init__(self, metadata: ToolMetadata) -> None:
        self._implementation: Callable[..., Any] | None = None
        self._lock = Lock()

    def _load_implementation(self) -> None:
        if self._implementation is not None:
            return
        with self._lock:
            if self._implementation is not None:
                return
            module = importlib.import_module(self.metadata.module)
            self._implementation = getattr(module, self.metadata.handler)
```

The double-checked locking (`if ... return` before and inside the lock) ensures thread safety while avoiding lock contention on the hot path once the module is loaded.

### Context Manager Pattern (protect/client.py, core/utils/client.py)

Both async API clients implement `__aenter__` / `__aexit__` for use in `async with` blocks. This guarantees that WebSocket connections and HTTP sessions are properly closed even when exceptions propagate:

```python
async with UniFiProtectClient(config) as client:
    cameras = client.cameras
    # WebSocket and HTTP session are open here
# Both are closed here, even if an exception occurred
```

### Code Mode Pattern (mcp/server.py + mcp/registry.py)

The MCP server implements a progressive-disclosure pattern designed for AI agents. Rather than exposing 53 individual tool definitions to the AI's context window, it exposes three public discovery meta-tools. Host code can then execute selected tools through `ToolRegistry` / `ToolProxy`:

```text
1. search_tools(category="analysis") -> list of matching tools
2. get_tool_info("detect_ip_conflicts") -> parameters and description
3. ToolRegistry.get_tool("detect_ip_conflicts").execute() -> result
```

This keeps the AI's tool list short and avoids overwhelming the model with schema for all 61 tools at once. The agent requests detail only for tools it intends to use.

---

## 13. Key Workflows (Sequence Diagrams)

### 13.1 Port Discovery and Naming Flow

```mermaid
sequenceDiagram
    participant CLI as cli.py / typer_cli.py
    participant SPM as SmartPortMapper
    participant DC as DeviceCapabilityDetector
    participant API as UnifiApiClient
    participant GTV as GroundTruthVerifier

    CLI->>API: login()
    API-->>CLI: authenticated

    CLI->>API: get_devices(site)
    API-->>CLI: devices_data[]

    CLI->>API: get_lldp_data(site)
    API-->>CLI: lldp_data{}

    CLI->>SPM: smart_update_ports(devices, lldp, verify=True)

    loop per device
        SPM->>DC: detect_capabilities(model, firmware)
        DC-->>SPM: DeviceCapability

        SPM->>DC: should_attempt_port_naming(model, firmware)
        DC-->>SPM: (bool, reason)

        alt device not supported
            SPM-->>CLI: skip device, record reason
        else device supported
            SPM->>API: get_device_details(site, device_id)
            API-->>SPM: port_table, port_overrides

            SPM->>SPM: build port name proposals from lldp_data

            alt dry_run=False
                SPM->>API: put_port_overrides(device_id, overrides)
                API-->>SPM: 200 OK

                alt verify_updates=True
                    SPM->>GTV: verify_port_updates_ground_truth(updates)
                    loop 5 reads with delay
                        GTV->>API: get_device_details(device_id)
                        Note over GTV,API: Cache-busting headers on each read
                        API-->>GTV: device details
                    end
                    GTV-->>SPM: {consistent, matches_expected, read_values}
                end
            end
        end
    end

    SPM-->>CLI: summary {attempted, successful, skipped, failed}
```

### 13.2 API Authentication Flow

```mermaid
sequenceDiagram
    participant CLIENT as UnifiApiClient
    participant CTRL as UniFi Controller

    CLIENT->>CTRL: GET /api/self (probe UniFi OS path)
    alt UniFi OS (UDM/UDR)
        CTRL-->>CLIENT: 200 OK
        Note over CLIENT: Set is_unifi_os=True, endpoint=/proxy/network/api
        alt api_token available
            CLIENT->>CTRL: GET /proxy/network/api/self\n  X-API-KEY: <token>
            CTRL-->>CLIENT: 200 OK
            Note over CLIENT: auth_method="token", is_authenticated=True
        else username+password
            CLIENT->>CTRL: POST /api/auth/login\n  {username, password}
            CTRL-->>CLIENT: 200 OK + Set-Cookie: unifises
            Note over CLIENT: auth_method="username_password", is_authenticated=True
        end
    else Legacy controller
        CTRL-->>CLIENT: 404 or connection error
        Note over CLIENT: Set endpoint=/api
        CLIENT->>CTRL: POST /api/login\n  {username, password}
        CTRL-->>CLIENT: 200 OK + Set-Cookie: unifises
        Note over CLIENT: is_authenticated=True
    end
```

### 13.3 MCP Tool Discovery and Execution Flow

```mermaid
sequenceDiagram
    participant AGENT as AI Agent (Claude)
    participant MCP as MCP Server
    participant REG as ToolRegistry
    participant HOST as Host code / test
    participant PROXY as ToolProxy
    participant TOOL as Tool Module

    AGENT->>MCP: search_tools(category="analysis")
    MCP->>REG: search(category="analysis", detail_level="summary")
    REG->>REG: _load_manifests() [first call only]
    REG-->>MCP: [{name, description}, ...]
    MCP-->>AGENT: tool list (names + descriptions only)

    AGENT->>MCP: get_tool_info("detect_ip_conflicts")
    MCP->>REG: get_metadata("detect_ip_conflicts")
    REG-->>MCP: ToolMetadata {parameters, tags, ...}
    MCP-->>AGENT: full schema with parameter definitions

    HOST->>REG: get_tool("detect_ip_conflicts")
    REG-->>HOST: ToolProxy

    HOST->>PROXY: execute()
    PROXY->>PROXY: _load_implementation() [lazy import on first call]
    PROXY->>TOOL: importlib.import_module("unifi_mapper.analysis.ip_conflicts")
    TOOL-->>PROXY: module loaded

    PROXY->>TOOL: detect_ip_conflicts()
    TOOL-->>PROXY: IPConflictReport
    PROXY-->>HOST: result
```

### 13.4 Protect Event Processing Flow

```mermaid
sequenceDiagram
    participant NVR as UniFi Protect NVR
    participant CLIENT as UniFiProtectClient
    participant EH as EventHandler
    participant FILTER as EventFilter
    participant MQTT as MQTTBridge
    participant HA as Home Assistant

    CLIENT->>NVR: WebSocket connect
    NVR-->>CLIENT: Bootstrap (full device inventory)
    Note over CLIENT: state = CONNECTED

    loop WebSocket event stream
        NVR->>CLIENT: WSSubscriptionMessage
        CLIENT->>EH: dispatch(message)
        EH->>EH: parse into ProtectEvent

        alt event matches filter
            EH->>FILTER: evaluate(event)
            FILTER-->>EH: match
            EH->>MQTT: on_event(ProtectEvent)
            MQTT->>HA: publish unifi/protect/camera/<id>/motion
        end

        alt device state change
            EH->>EH: update internal state
        end
    end

    alt WebSocket disconnect
        CLIENT->>CLIENT: state = RECONNECTING
        CLIENT->>NVR: reconnect with backoff
        NVR-->>CLIENT: new WebSocket + Bootstrap
        CLIENT->>CLIENT: state = CONNECTED
    end
```

### 13.5 Comprehensive Diagnostics Runner Flow

The `diagnose all` command runs 11 independent analysis checks sequentially, each following the canonical async pattern, and aggregates results into a pass/warn/fail summary:

```mermaid
sequenceDiagram
    participant CLI as typer_cli.py
    participant CHECK as Analysis Module
    participant UC as UniFiClient
    participant API as UniFi Controller

    CLI->>CLI: load_env_from_config()

    loop 11 checks (link quality, capacity, port profiles, MTU, SFP, radio, firmware, DHCP, PoE, client density, uplink)
        CLI->>CHECK: asyncio.run(check_fn())
        CHECK->>UC: async with UniFiClient()
        UC->>API: GET /stat/device, /stat/sta, etc.
        API-->>UC: JSON response
        UC-->>CHECK: parsed data
        CHECK->>CHECK: _analyze_*() pure logic
        CHECK-->>CLI: Pydantic report
        CLI->>CLI: _extract_status(report) → PASS|WARN|FAIL
    end

    CLI->>CLI: Rich Table summary
```

---

## 14. Module Dependency Graph

The following graph shows the primary import relationships between modules. Arrows point from importer to imported.

```mermaid
graph TD
    subgraph entry_points["Entry Points"]
        TCLI["typer_cli"]
        NCLI["network_cli"]
        ICLI["inventory_cli"]
        MCPS["mcp/server"]
    end

    subgraph scheduling["Scheduling"]
        CRON["unifi-cron.sh"]
    end

    subgraph cli_shared["Shared CLI"]
        CLI["cli"]
    end

    subgraph intelligence["Intelligence"]
        SPM["smart_port_mapper"]
        PM["port_mapper"]
        DC["device_capabilities"]
        GTV["ground_truth_verification"]
        ENT["enhanced_network_topology"]
    end

    subgraph api["API Integration"]
        AC["api_client"]
        EAC["enhanced_api_client"]
        TA["toolkit_adapters"]
        PC["protect/client"]
        UC["core/utils/client"]
        CFG["config"]
        AUTH["core/utils/auth"]
    end

    subgraph tools["Analysis Toolkit"]
        AN["analysis/*"]
        DG["diagnostics/*"]
        DS["discovery/*"]
        CN["connectivity/*"]
    end

    subgraph ssh_layer["SSH Integration"]
        ASYNCSSH["asyncssh"]
        LM["analysis/latency_matrix"]
        BW["analysis/bandwidth_test"]
    end

    subgraph network_cp["Network Control Plane"]
        NW["network/*"]
    end

    subgraph protect_sub["Protect Subsystem"]
        PE["protect/events"]
        PQ["protect/mqtt"]
        PAI["protect/aiport"]
        PAN["protect/analytics"]
        PRE["protect/repository"]
    end

    subgraph domain["Core Domain"]
        MD["models"]
        CM["core/models/*"]
        EX["exceptions"]
        ERR["core/utils/errors"]
    end

    CRON -->|"uv run"| TCLI
    TCLI --> CLI
    TCLI --> SPM
    TCLI --> PM
    NCLI --> CLI
    ICLI --> CLI
    MCPS --> REGISTRY["mcp/registry"]
    REGISTRY --> AN
    REGISTRY --> DG
    REGISTRY --> DS
    REGISTRY --> CN

    SPM --> DC
    SPM --> GTV
    SPM --> AC
    PM --> AC
    PM --> ENT
    GTV --> AC

    AC --> EX
    EAC --> EX
    EAC --> AC

    TA --> AC
    PC --> AUTH
    UC --> AUTH
    CFG --> CLI

    AN --> UC
    AN --> CM
    DG --> UC
    DG --> CM
    DS --> UC
    DS --> CM
    CN --> UC
    CN --> CM

    LM --> UC
    LM --> ASYNCSSH
    LM --> AUTH
    BW --> ASYNCSSH
    BW --> AUTH

    NW --> UC

    PE --> PC
    PQ --> PE
    PAI --> PE
    PAN --> PE
    PRE --> CM

    ENT --> MD
    SPM --> MD
    PM --> MD
```

---

## 15. External Interfaces

### 15.1 UniFi Network REST API

| Interface | Protocol | Auth | Notes |
| --- | --- | --- | --- |
| UniFi OS path | HTTPS REST | `X-API-KEY` token header | UDM, UDR, UDM SE — preferred |
| Legacy controller path | HTTPS REST | Session cookie (POST `/api/login`) | Self-hosted controller software |

Key endpoints consumed:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/proxy/network/api/s/{site}/stat/device` | GET | Device inventory with port tables |
| `/proxy/network/api/s/{site}/rest/device/{id}` | PUT | Port override writes |
| `/proxy/network/api/s/{site}/stat/sta` | GET | Wireless client list |
| `/proxy/network/api/s/{site}/rest/networkconf` | GET | Network/VLAN configuration |
| `/proxy/network/api/s/{site}/rest/firewallrule` | GET | Firewall rules |
| `/proxy/network/api/s/{site}/stat/health` | GET | Site health summary |

**Critical API behaviour note**: The UniFi API caches device state. Reads of `port_table` after a write to `port_overrides` may return stale data for an indeterminate period. The `GroundTruthVerifier` exists specifically to work around this behaviour.

**Write field distinction**: `port_table` is read-only (populated by the controller firmware). The writable field is `port_overrides` — a sparse array containing only ports with non-default configuration. This is a documented but non-obvious behaviour that affects all port configuration writes.

### 15.2 UniFi Protect WebSocket API

| Interface | Protocol | Library |
| --- | --- | --- |
| Protect events | WSS WebSocket | `uiprotect` library |
| Bootstrap data | HTTPS REST | `uiprotect` library |
| Camera streams | RTSP | Not managed by this platform |

Event types consumed: motion, smart detect zones, doorbell, sensor state, device online/offline, NVR system events.

### 15.3 ONVIF (IP Camera Protocol)

Used by `protect/aiport.py` to communicate with third-party cameras paired to UniFi AI Ports. Handled via the `onvif-zeep-async` library.

### 15.3a SSH (Gateway Management Plane)

Used by `analysis/latency_matrix.py` and `analysis/bandwidth_test.py` to execute commands on the UDM gateway. Handled via `asyncssh`.

| Interface | Protocol | Auth | Notes |
| --- | --- | --- | --- |
| UDM SSH | SSH (port 22) | Password (`UNIFI_SSH_USERNAME` / `UNIFI_SSH_PASSWORD`) | `known_hosts=None` for self-signed |

Commands executed: `ping` (latency matrix), `iperf3` (bandwidth test).

### 15.4 MQTT (Home Assistant Integration)

`protect/mqtt.py` publishes events to an MQTT broker using the Home Assistant MQTT Discovery convention. The bridge auto-generates discovery payloads so Home Assistant registers Protect devices without manual configuration.

| Topic pattern | Content |
| --- | --- |
| `homeassistant/<type>/<device_id>/config` | Discovery payload (auto-registers device in HA) |
| `unifi/protect/<device_id>/state` | Device state updates |
| `unifi/protect/<device_id>/event` | Event payloads (motion, detection, etc.) |

### 15.5 MCP Protocol

The MCP server implements the Model Context Protocol (MCP) 1.0 specification using the FastMCP SDK. AI clients connect via stdio (for local use) or SSE (for remote deployment). The server exports:

- 3 public discovery meta-tools (search, list, info)
- 61 registered automation tools in YAML manifests, executable through `ToolRegistry` / `ToolProxy` in host code

---

## 16. Configuration and Credential Management

### Configuration resolution order

```mermaid
flowchart TD
    ENV_CLI["--config CLI flag or UNIFI_CONFIG env var"]
    XDG_PROD["$XDG_CONFIG_HOME/unifi_management_cli/prod.env"]
    XDG_DEF["$XDG_CONFIG_HOME/unifi_management_cli/default.env"]
    HOME_PROD["~/.config/unifi_management_cli/prod.env"]
    HOME_DEF["~/.config/unifi_management_cli/default.env"]
    DOTENV[".env (current directory)"]
    ERROR["ValueError: UNIFI_URL required"]

    ENV_CLI -->|"exists"| LOAD["load into os.environ"]
    ENV_CLI -->|"not set"| XDG_PROD
    XDG_PROD -->|"exists"| LOAD
    XDG_PROD -->|"not found"| XDG_DEF
    XDG_DEF -->|"exists"| LOAD
    XDG_DEF -->|"not found"| HOME_PROD
    HOME_PROD -->|"exists"| LOAD
    HOME_PROD -->|"not found"| HOME_DEF
    HOME_DEF -->|"exists"| LOAD
    HOME_DEF -->|"not found"| DOTENV
    DOTENV -->|"exists"| LOAD
    DOTENV -->|"not found"| ERROR
```

### Credential fallback chain (MCP / toolkit)

For the async toolkit and MCP server, credentials are resolved at runtime via `get_credentials()`:

1. **Environment variables**: `UNIFI_URL` (or `UNIFI_HOST`), `UNIFI_CONSOLE_API_TOKEN` (or `UNIFI_API_TOKEN`), `UNIFI_USERNAME`, `UNIFI_PASSWORD`, `UNIFI_SITE`, `UNIFI_VERIFY_SSL`.
2. **macOS Keychain**: Stored as JSON under service name `unifi-mcp`, account `controller`, via the `keyring` library.
3. **1Password CLI**: Reads an item named `UniFi Controller` from the default 1Password vault using the `op` CLI.

If all three sources fail, a `ToolError` with `error_code=AUTHENTICATION_FAILED` is raised with a structured suggestion.

### UnifiConfig dataclass

`config.py` provides `UnifiConfig`, a `@dataclass` with `__post_init__` validation:

- URL must start with `http://` or `https://`.
- Either `api_token` or both `username` and `password` must be present.
- Numeric values are clamped to safe ranges: timeout 1-300s, retries 1-10, retry delay 0.1-10s.
- `from_env()` is the standard factory, loading from an env file then `os.environ`.

---

*End of architecture overview.*
