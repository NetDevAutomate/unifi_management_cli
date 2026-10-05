# C4 Architecture: UniFi Management CLI

> **See also**: [Architecture Overview](architecture-overview.md) | [Codebase Map](codemap.md) | [Use Cases](../guides/use-cases-and-howto.md) | [Troubleshooting](../operations/troubleshooting-and-runbook.md)

## Table of Contents

1. [Overview](#overview)
2. [Level 1: System Context](#level-1-system-context)
3. [Level 2: Container Diagram](#level-2-container-diagram)
4. [Level 3: Component Diagrams](#level-3-component-diagrams)
   - [CLI Layer Components](#31-cli-layer-components)
   - [API Integration Components](#32-api-integration-components)
   - [Analysis and Diagnostic Components](#33-analysis-and-diagnostic-components)
   - [UniFi Protect Components](#34-unifi-protect-components)
   - [MCP Server Components](#35-mcp-server-components)
5. [Level 4: Code Diagrams](#level-4-code-diagrams)
   - [API Client Class Structure](#41-api-client-class-structure)
   - [Protect Client Class Structure](#42-protect-client-class-structure)
   - [Data Model Hierarchy](#43-data-model-hierarchy)
   - [Exception Hierarchy](#44-exception-hierarchy)
6. [Provider and Platform Architecture](#provider-and-platform-architecture)
7. [Dynamic Runtime Flows](#dynamic-runtime-flows)
8. [Key Design Decisions](#key-design-decisions)

---

## Overview

The UniFi Management CLI is an enterprise-grade Python automation platform for Ubiquiti UniFi networks. It provides four distinct installed entry points--three CLI tools and one MCP server--all built on a shared library of API clients, domain models, and analysis engines. The platform spans two separate UniFi product lines (Network and Protect) and integrates with Home Assistant via MQTT and with AI assistants via the Model Context Protocol.

Provider/platform-specific detail lives in:

- [UniFi Network Provider Architecture](providers/unifi-network.md)
- [UniFi Protect and MQTT Provider Architecture](providers/unifi-protect-mqtt.md)
- [AXIS Provisioning Provider Architecture](providers/axis-provisioning.md)
- [MCP and Automation Interface Architecture](providers/mcp-automation.md)

This document follows the C4 model (Simon Brown) with all four levels of abstraction: System Context, Container, Component, and Code.

---

## Level 1: System Context

The system context shows the UniFi Management CLI in relation to the humans and external systems it interacts with. At this level, internal structure is irrelevant — the focus is on boundaries and relationships.

### Mermaid Diagram

```mermaid
C4Context
    title System Context - UniFi Management CLI

    Person(admin, "Network Administrator", "Manages UniFi network infrastructure, cameras, and security devices")
    Person(ai_user, "AI-Assisted User", "Uses Claude or other MCP-compatible AI assistants for network troubleshooting")

    System(unifi_mgmt, "UniFi Management CLI", "Enterprise UniFi automation platform. Provides CLI tools and an MCP server for network management, topology visualisation, diagnostics, Protect integration, and automation.")

    System_Ext(unifi_network, "UniFi Network Controller", "Ubiquiti UniFi OS or legacy controller. Manages switches, access points, and gateways via REST API.")
    System_Ext(unifi_protect, "UniFi Protect Controller", "Ubiquiti video security platform. Manages cameras, sensors, doorbells, and AI Ports via REST and WebSocket.")
    System_Ext(home_assistant, "Home Assistant", "Home automation platform. Receives UniFi Protect events via MQTT for automation rules.")
    System_Ext(ai_assistant, "AI Assistant (Claude / MCP Client)", "Large language model or MCP-compatible client. Uses the MCP server to discover network management tools.")

    Rel(admin, unifi_mgmt, "Runs CLI commands", "terminal / shell")
    Rel(ai_user, ai_assistant, "Issues natural language requests", "chat")
    Rel(ai_assistant, unifi_mgmt, "Discovers and runs read-only tools", "MCP / JSON-RPC over stdio")
    Rel(unifi_mgmt, unifi_network, "Reads topology, stats, and config. CLI commands write port names, STP priorities, radio settings and firmware upgrades; the MCP server never writes.", "HTTPS REST API")
    Rel(unifi_mgmt, unifi_protect, "Reads device inventory and events. Subscribes to real-time updates.", "HTTPS REST + WebSocket")
    Rel(unifi_mgmt, home_assistant, "Publishes camera events and device states with auto-discovery", "MQTT")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Context
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Context.puml

Person(admin, "Network Administrator", "Manages UniFi network infrastructure, cameras, and security devices")
Person(ai_user, "AI-Assisted User", "Uses Claude or MCP-compatible AI assistants for network troubleshooting")

System(unifi_mgmt, "UniFi Management CLI", "Enterprise UniFi automation platform providing CLI tools and MCP server for network management, topology visualisation, diagnostics, Protect integration, and automation.")

System_Ext(unifi_network, "UniFi Network Controller", "Ubiquiti UniFi OS or legacy controller. Manages switches, APs, and gateways via REST API.")
System_Ext(unifi_protect, "UniFi Protect Controller", "Ubiquiti video security platform. Manages cameras, sensors, doorbells, and AI Ports.")
System_Ext(home_assistant, "Home Assistant", "Home automation platform receiving Protect events via MQTT.")
System_Ext(ai_assistant, "AI Assistant (Claude / MCP Client)", "LLM or MCP-compatible client invoking network management tools.")

Rel(admin, unifi_mgmt, "Runs CLI commands", "terminal / shell")
Rel(ai_user, ai_assistant, "Issues natural language requests", "chat")
Rel(ai_assistant, unifi_mgmt, "Discovers and runs read-only tools", "MCP / JSON-RPC over stdio")
Rel(unifi_mgmt, unifi_network, "Reads; CLI commands write, the MCP server never does", "HTTPS REST")
Rel(unifi_mgmt, unifi_protect, "Reads devices and events, subscribes to updates", "HTTPS REST + WebSocket")
Rel(unifi_mgmt, home_assistant, "Publishes events with MQTT auto-discovery", "MQTT")
@enduml
```

### Context Notes

The platform serves two distinct user personas with different interaction models:

- The **Network Administrator** invokes CLI tools directly. They choose the appropriate tool (`unifi-mapper`, `unifi-network-toolkit`, or `unifi-inventory`) depending on whether they need interactive output, scripting compatibility, or inventory reports.

- The **AI-Assisted User** interacts indirectly through an MCP-compatible client such as Claude Desktop. The AI assistant uses `unifi-mcp` for progressive tool discovery: the default discovery surface lists four meta-tools (`search_tools`, `list_categories`, `get_tool_info`, `execute_tool`), and the direct surface also lists each read-only tool by name. Every call runs through `ToolRunner`; the three tools that would change the controller are refused, and those changes go through the CLI.

The dual-controller architecture (Network + Protect) reflects Ubiquiti's product split: network infrastructure and video security run on separate controllers with different APIs, authentication models, and communication protocols.

---

## Level 2: Container Diagram

At the container level, the UniFi Management CLI resolves into five containers: four Python entry-point commands and the shared library they all import. Each container has a distinct technology profile and responsibility boundary.

### Mermaid Diagram

```mermaid
C4Container
    title Container Diagram - UniFi Management CLI

    Person(admin, "Network Administrator")
    Person_Ext(ai_assistant, "AI Assistant (MCP Client)")

    System_Ext(unifi_network, "UniFi Network Controller", "HTTPS REST API")
    System_Ext(unifi_protect, "UniFi Protect Controller", "HTTPS REST + WebSocket")
    System_Ext(home_assistant, "Home Assistant", "MQTT")

    System_Boundary(platform, "UniFi Management CLI") {
        Container(unifi_mapper_cli, "unifi-mapper", "Python / Typer / Rich", "Primary interactive CLI. Commands: discover, diagram, verify, capabilities and the find, analyze, diagnose, ports, controller, backup, stp, radio and inventory groups. discover previews unless --apply.")
        Container(network_toolkit_cli, "unifi-network-toolkit", "Python / argparse", "Script-friendly CLI. Subcommands: discover, analyze, find, diagnose, install-completions. Its discover writes port names unless --dry-run.")
        Container(inventory_cli, "unifi-inventory", "Python / Typer", "The four inventory commands (list, check-updates, firmware-skew, update-firmware) as their own program.")
        Container(mcp_server, "unifi-mcp", "Python / FastMCP", "MCP server. Runs over stdio. Backed by YAML manifests for 87 registered tools, run read-only through ToolRunner.")
        Container(shared_lib, "unifi_mapper library", "Python 3.12 package", "Shared library providing API clients, domain models, analysis engines, diagnostic tools, discovery utilities, connectivity analysis, Protect integration, topology visualisation, and report generation.")
    }

    Rel(admin, unifi_mapper_cli, "Runs commands", "shell")
    Rel(admin, network_toolkit_cli, "Runs commands", "shell")
    Rel(admin, inventory_cli, "Runs commands", "shell")
    Rel(ai_assistant, mcp_server, "Discovers and runs read-only tools", "MCP / JSON-RPC stdio")
    Rel(unifi_mapper_cli, shared_lib, "Imports and calls")
    Rel(network_toolkit_cli, shared_lib, "Imports and calls")
    Rel(inventory_cli, shared_lib, "Imports and calls")
    Rel(mcp_server, shared_lib, "Imports registry and tool wrappers")
    Rel(shared_lib, unifi_network, "REST calls with session auth and retry", "HTTPS")
    Rel(shared_lib, unifi_protect, "Async REST + WebSocket subscription", "HTTPS / WSS")
    Rel(shared_lib, home_assistant, "MQTT publish with auto-discovery", "MQTT")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Container
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Container.puml

Person(admin, "Network Administrator")
Person_Ext(ai_assistant, "AI Assistant (MCP Client)")

System_Ext(unifi_network, "UniFi Network Controller", "HTTPS REST API")
System_Ext(unifi_protect, "UniFi Protect Controller", "HTTPS REST + WebSocket")
System_Ext(home_assistant, "Home Assistant", "MQTT")

System_Boundary(platform, "UniFi Management CLI") {
    Container(unifi_mapper_cli, "unifi-mapper", "Python / Typer / Rich", "Primary interactive CLI with Rich terminal UI")
    Container(network_toolkit_cli, "unifi-network-toolkit", "Python / argparse", "Script-friendly CLI for automation")
    Container(inventory_cli, "unifi-inventory", "Python / Typer", "The four inventory commands as their own program")
    Container(mcp_server, "unifi-mcp", "Python / FastMCP", "MCP server backed by 87 YAML-registered tools, run read-only")
    Container(shared_lib, "unifi_mapper library", "Python 3.12 package", "Shared library: API clients, models, analysis, diagnostics, Protect, topology")
}

Rel(admin, unifi_mapper_cli, "Runs commands", "shell")
Rel(admin, network_toolkit_cli, "Runs commands", "shell")
Rel(admin, inventory_cli, "Runs commands", "shell")
Rel(ai_assistant, mcp_server, "Discovers and runs read-only tools", "MCP / JSON-RPC stdio")
Rel(unifi_mapper_cli, shared_lib, "Imports and calls")
Rel(network_toolkit_cli, shared_lib, "Imports and calls")
Rel(inventory_cli, shared_lib, "Imports and calls")
Rel(mcp_server, shared_lib, "Imports and calls")
Rel(shared_lib, unifi_network, "REST calls with retry logic", "HTTPS")
Rel(shared_lib, unifi_protect, "Async REST + WebSocket", "HTTPS / WSS")
Rel(shared_lib, home_assistant, "MQTT publish with auto-discovery", "MQTT")
@enduml
```

### Container Notes

The **four entry points (three CLIs and the MCP server) are shells** over the shared library. They handle argument parsing, output formatting, and process lifecycle, and the domain logic lives in the library. The `pyproject.toml` entry-point declarations map each command straight to a module's `main` or `app`.

The **shared library** is the architectural centre of gravity. All domain logic, API interactions, and integration code live here. This makes the platform easy to extend: a new CLI tool, automation wrapper, or future web API can be added without touching existing containers.

The `unifi-mapper` and `unifi-network-toolkit` CLIs offer overlapping functionality with different UX targets. `unifi-mapper` uses Typer + Rich for an interactive terminal experience; `unifi-network-toolkit` uses argparse for scripting compatibility. This is a deliberate duplication to serve both audiences without compromise.

---

## Level 3: Component Diagrams

### 3.1 CLI Layer Components

The CLI containers delegate to specific modules within the shared library. This diagram shows the internal components of the CLI layer and their dependencies on the library core.

```mermaid
C4Component
    title Component Diagram - CLI Layer

    Container_Boundary(cli_layer, "CLI Entry Points") {
        Component(typer_cli, "typer_cli.py", "Typer + Rich", "unifi-mapper entry point: discover, diagram, verify, capabilities, version, install-completions and the find, analyze, diagnose, ports, controller, backup, stp, radio and inventory groups. Global state for config path, debug flag and root shortcuts.")
        Component(network_cli, "network_cli.py", "argparse", "unifi-network-toolkit entry point. Subcommands: discover, analyze, find, diagnose, install-completions. Optimised for scripting.")
        Component(inventory_cli_comp, "inventory_cli.py", "Typer", "inventory_app: mounted as unifi-mapper inventory and run as unifi-inventory (list, check-updates, firmware-skew, update-firmware).")
        Component(completions, "completions.py", "Python", "Bundled bash and zsh completion installer; Typer installs other shells.")
    }

    Container_Boundary(core_lib, "Shared Library - Core") {
        Component(cli_helpers, "cli.py", "Python", "Shared CLI utilities: config path resolution, env file loading.")
        Component(config_comp, "config.py", "Python dataclass", "UnifiConfig dataclass. XDG Base Directory support. Env file loading. Input validation and clamping.")
        Component(api_client_comp, "api_client.py", "requests", "UnifiApiClient. Session management, auth negotiation, retry with exponential backoff.")
        Component(run_methods, "run_methods.py", "Python", "High-level orchestration functions called by CLI subcommands.")
        Component(report_gen, "report_generator.py", "Python / Markdown", "Markdown and HTML report generation from analysis results.")
    }

    Rel(typer_cli, cli_helpers, "Loads config")
    Rel(typer_cli, run_methods, "Delegates subcommand execution")
    Rel(network_cli, cli_helpers, "Loads config")
    Rel(network_cli, run_methods, "Delegates subcommand execution")
    Rel(inventory_cli_comp, cli_helpers, "Loads config")
    Rel(inventory_cli_comp, api_client_comp, "Reads devices; update-firmware sends upgrade commands")
    Rel(run_methods, api_client_comp, "Creates and uses")
    Rel(run_methods, report_gen, "Generates reports")
    Rel(typer_cli, completions, "Registers completions")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_CLI
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(cli_layer, "CLI Entry Points") {
    Component(typer_cli, "typer_cli.py", "Typer + Rich", "unifi-mapper: discover, diagram, verify, find, analyze, diagnose, ports, controller, backup, stp, radio, inventory")
    Component(network_cli, "network_cli.py", "argparse", "unifi-network-toolkit: discover, analyze, find, diagnose")
    Component(inventory_cli_comp, "inventory_cli.py", "Typer", "inventory_app: unifi-inventory, also mounted as the inventory group of unifi-mapper")
    Component(completions, "completions.py", "Python", "bash and zsh completion installer")
}

Container_Boundary(core_lib, "Shared Library - Core") {
    Component(cli_helpers, "cli.py", "Python", "Shared CLI utilities and config path resolution")
    Component(config_comp, "config.py", "Python dataclass", "UnifiConfig: validation, XDG, env loading")
    Component(api_client_comp, "api_client.py", "requests", "UnifiApiClient: session, auth, retry")
    Component(run_methods, "run_methods.py", "Python", "High-level orchestration for CLI subcommands")
    Component(report_gen, "report_generator.py", "Python / Markdown", "Markdown and HTML report generation")
}

Rel(typer_cli, cli_helpers, "Loads config")
Rel(typer_cli, run_methods, "Delegates")
Rel(network_cli, cli_helpers, "Loads config")
Rel(network_cli, run_methods, "Delegates")
Rel(inventory_cli_comp, cli_helpers, "Loads config")
Rel(inventory_cli_comp, api_client_comp, "Reads devices")
Rel(run_methods, api_client_comp, "Creates and uses")
Rel(run_methods, report_gen, "Generates reports")
@enduml
```

---

### 3.2 API Integration Components

The API integration layer abstracts the two separate UniFi controller APIs behind clean client interfaces.

```mermaid
C4Component
    title Component Diagram - API Integration Layer

    Container_Boundary(api_layer, "Shared Library - API Integration") {
        Component(api_client_c, "api_client.py / UnifiApiClient", "requests + Session", "Synchronous REST client for UniFi Network Controller. Dual auth: API token or username/password. Supports UniFi OS and legacy controller URL schemas. Retry logic with exponential backoff (it clamps its own arguments to 1-10 retries and a 0.1-10s delay, and callers leave the defaults of 3 and 1.0s). Keeps short hashes of the credentials for verification.")
        Component(enhanced_api, "enhanced_api_client.py / EnhancedUnifiApiClient", "requests", "A separate synchronous client (it does not subclass UnifiApiClient) for the toolkit: port_overrides updates followed by force-provision, per-port verification, and meta.rc checks on 200 responses.")
        Component(config_c, "config.py / UnifiConfig", "Python dataclass", "Validated configuration. Clamps timeout (1-300s), retries (1-10), and delay (0.1-10s). Requires api_token OR username+password. No caller passes its retry values on to a client, so they have no effect (issue 042).")
        Component(exceptions_c, "exceptions.py", "Python exception hierarchy", "Structured exception tree. Retryable vs Permanent split determines whether retry logic activates. Includes UniFiAuthenticationError, UniFiConnectionError, UniFiTimeoutError, UniFiRateLimitError, UniFiPermissionError, UniFiValidationError.")
        Component(ground_truth, "ground_truth_verification.py / GroundTruthVerifier", "Python", "Multi-read consistency checking to work around UniFi API response caching. Verifies applied changes actually took effect.")
        Component(toolkit_adapters_c, "toolkit_adapters.py / ToolkitAdapter", "Python adapter pattern", "Synchronous versions of three tools (find device, link quality, network health) for unifi-network-toolkit, over its EnhancedUnifiApiClient.")
        Component(async_client_c, "core/utils/client.py / UniFiClient", "httpx", "Async controller client for the async analysis, diagnostics, discovery and connectivity tools. Under the MCP server every async controller tool, and each CLI analysis or SSH command, borrows one shared client behind ReadOnlyAsyncTransport; the seven port-diagnostics tools run the sync UnifiApiClient behind ReadOnlySession instead.")
        Component(network_client_c, "network/client.py / UniFiNetworkClient", "httpx", "Async Network Integration API client (UNIFI_NETWORK_* settings). The MCP network tools open one per call behind the GET-only transport.")
        Component(readonly_c, "core/utils/readonly.py", "Python", "Read-only guards: ReadOnlySession for the sync client, ReadOnlyAsyncTransport for the httpx clients. A write raises ReadOnlyViolation before any I/O; allowed requests go to the opt-in request audit: a file, or a callable sink (the MCP call log's buffer).")
        Component(redact_c, "core/utils/redact.py", "Python", "Strips secret fields from port-diagnostic output and masks secret values in every MCP result and error, and in CLI error text.")
    }

    System_Ext(unifi_network_c, "UniFi Network Controller", "HTTPS REST API")

    Rel(api_client_c, unifi_network_c, "GET/POST/PUT requests", "HTTPS")
    Rel(enhanced_api, unifi_network_c, "REST calls with meta.rc checks", "HTTPS")
    Rel(api_client_c, exceptions_c, "Raises on error")
    Rel(api_client_c, config_c, "Configured by")
    Rel(ground_truth, api_client_c, "Uses for device lookups only")
    Rel(toolkit_adapters_c, enhanced_api, "Wraps")
    Rel(async_client_c, unifi_network_c, "Classic controller API", "HTTPS")
    Rel(network_client_c, unifi_network_c, "Integration API", "HTTPS")
    Rel(async_client_c, readonly_c, "Guarded by (MCP)")
    Rel(network_client_c, readonly_c, "Guarded by (MCP, GET only)")
    Rel(api_client_c, readonly_c, "Guarded by (port diagnostics)")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_API
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(api_layer, "Shared Library - API Integration") {
    Component(api_client_c, "UnifiApiClient", "requests", "Synchronous REST client with dual auth, retry, and credential sanitisation")
    Component(enhanced_api, "EnhancedUnifiApiClient", "requests", "Separate sync client: overrides + force-provision, meta.rc checks")
    Component(config_c, "UnifiConfig", "dataclass", "Validated configuration with input clamping")
    Component(exceptions_c, "Exception hierarchy", "Python", "Retryable vs Permanent error split")
    Component(ground_truth, "GroundTruthVerifier", "Python", "Multi-read consistency checking for API cache workaround")
    Component(toolkit_adapters_c, "ToolkitAdapter", "Python adapter", "Sync versions of three tools for the toolkit")
    Component(async_client_c, "UniFiClient", "httpx", "Async controller client; shared and read-only under MCP")
    Component(network_client_c, "UniFiNetworkClient", "httpx", "Async Integration API client")
    Component(readonly_c, "core/utils/readonly.py", "Python", "Read-only guards and request audit")
    Component(redact_c, "core/utils/redact.py", "Python", "Secret stripping and masking")
}

System_Ext(unifi_network_c, "UniFi Network Controller", "HTTPS REST")

Rel(api_client_c, unifi_network_c, "REST calls", "HTTPS")
Rel(enhanced_api, unifi_network_c, "REST calls", "HTTPS")
Rel(api_client_c, exceptions_c, "Raises on error")
Rel(ground_truth, api_client_c, "Uses for lookups")
Rel(toolkit_adapters_c, enhanced_api, "Wraps")
Rel(async_client_c, unifi_network_c, "Classic API", "HTTPS")
Rel(network_client_c, unifi_network_c, "Integration API", "HTTPS")
Rel(async_client_c, readonly_c, "Guarded by")
Rel(network_client_c, readonly_c, "Guarded by")
@enduml
```

---

### 3.3 Analysis and Diagnostic Components

The intelligence layer contains the toolkit functions exposed to CLI workflows and the 87 YAML-registered MCP tools. Tools receive a client/config object, query the UniFi controller surface they belong to, and return structured results.

```mermaid
C4Component
    title Component Diagram - Analysis, Diagnostics, Discovery, Connectivity

    Container_Boundary(intelligence, "Shared Library - Intelligence Layer") {

        Component(port_mapper_c, "port_mapper.py / UnifiPortMapper", "Python", "Desired-state port naming with LLDP/CDP and client discovery. Applies durable switch-port names through port_overrides.")
        Component(smart_port_mapper_c, "smart_port_mapper.py / SmartPortMapper", "Python", "Device-aware port mapping. Uses device capability profiles to interpret port data correctly per model.")
        Component(device_caps, "device_capabilities.py", "Python", "Model-specific capability detection. Determines port count, SFP slots, PoE capabilities, and uplink ports by hardware model.")
        Component(naming_rules, "run_methods.py / _choose_port_name", "Python", "Port-name decision rules: LLDP name, client name, useful active current name, or Port x default for disconnected ports.")
        Component(topology_c, "enhanced_network_topology.py / NetworkTopology", "Python / graphviz", "Topology graph generation. Outputs: PNG, SVG, HTML interactive (mermaid and dot write a placeholder, issue 044). Wraps graphviz for static formats.")
        Component(port_diag_c, "port_inspect.py / port_diagnostics.py / port_history.py", "Python", "Read-only port inspection, all-ports view, profile diff, client placement, event history, counter rates and the evidence bundle, behind the read-only guard.")
        Component(link_settings_c, "analysis/link_settings.py", "Python", "The one rule for a port's effective profile and link settings (override, then port table, then profile), shared by the port diagnostics and the profile analyses.")

        Component(analysis_pkg, "analysis/ (49 registered MCP tools, 54 modules)", "Python", "Capacity, firmware, IP conflicts, LAG, link quality and link speeds, MAC table, MTU, QoS, PoE and power budgets, port-profile usage, radio, SFP, STP, traffic matrix, uplinks, VLAN, freshness and 10G readiness analysis; AP health sampling (ap_health, CLI only); per-VLAN traffic: the sampler (vlan_traffic, SSH, CLI only) and the store with its two read-only tools (vlan_traffic_store).")
        Component(diagnostics_pkg, "diagnostics/ (11 registered MCP tools, 10 modules)", "Python", "connectivity_analysis, network_health, performance_analysis, security_audit, inspect_port, port_diagnostics_tools, observability, wan_health, wan_history, client_connectivity (CLI only, SSH); backup/verify registers verify_config_backup here too. port_diagnostics_tools also provides get_client_history (discovery) and the observability tools get_device_events, get_recent_events and get_port_counter_rates; observability provides get_device_stats, get_ap_retry_rates, get_config_object and find_recent_config_changes.")
        Component(discovery_pkg, "discovery/ (5 registered MCP tools, 4 modules)", "Python", "client_trace, find_device, find_ip, find_mac; get_client_history lives in diagnostics/")
        Component(connectivity_pkg, "connectivity/ (4 registered MCP tools)", "Python", "firewall_check, path_analysis, traceroute, inter_vlan; gateway_probe (SSH, CLI only)")
        Component(network_pkg, "network/ (6 registered MCP tools)", "Python", "Control plane: firewall zones/policies, ACL rules, DNS policies, clients, and networks")
    }

    Container_Boundary(api_int, "API Integration") {
        Component(api_ref, "UniFiClient / UnifiApiClient / UniFiNetworkClient", "httpx / requests", "")
    }

    Rel(analysis_pkg, api_ref, "Queries device data")
    Rel(diagnostics_pkg, api_ref, "Queries health and stats")
    Rel(discovery_pkg, api_ref, "Queries device and client tables")
    Rel(connectivity_pkg, api_ref, "Queries firewall rules and routing")
    Rel(network_pkg, api_ref, "Reads network config (GET only under MCP)")
    Rel(port_mapper_c, api_ref, "Queries ports, clients, LLDP data. Writes port_overrides unless its caller previews (unifi-mapper discover writes only with --apply)")
    Rel(port_diag_c, api_ref, "Reads through the read-only guard")
    Rel(port_diag_c, link_settings_c, "Resolves effective settings")
    Rel(naming_rules, port_mapper_c, "Feeds desired port names")
    Rel(smart_port_mapper_c, port_mapper_c, "Uses its API client")
    Rel(smart_port_mapper_c, device_caps, "Uses capability profiles")
    Rel(topology_c, port_mapper_c, "Consumes port map")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_Intelligence
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(intelligence, "Shared Library - Intelligence Layer") {
    Component(port_mapper_c, "UnifiPortMapper", "Python", "Desired-state port naming through port_overrides")
    Component(smart_port_mapper_c, "SmartPortMapper", "Python", "Device-aware port mapping")
    Component(device_caps, "DeviceCapabilities", "Python", "Model-specific capability profiles")
    Component(naming_rules, "run_methods.py / _choose_port_name", "Python", "LLDP, client, current, or Port x naming rules")
    Component(topology_c, "NetworkTopology", "Python / graphviz", "Topology graph: PNG, SVG, HTML")
    Component(port_diag_c, "Port diagnostics", "Python", "Read-only port inspection and evidence bundles")
    Component(link_settings_c, "analysis/link_settings.py", "Python", "Effective profile and link settings rule")
    Component(analysis_pkg, "analysis/ (49 registered MCP tools)", "Python", "Capacity, firmware, IP conflicts, LAG, link quality and speeds, MAC, MTU, QoS, PoE, radio, SFP, STP, traffic, uplinks, VLAN, 10G readiness")
    Component(diagnostics_pkg, "diagnostics/ (11 registered MCP tools)", "Python", "Health, performance, security, connectivity, port inspection and evidence, WAN health and speedtest history, offline backup verification; also client history and the observability tools")
    Component(discovery_pkg, "discovery/ (5 registered MCP tools)", "Python", "Find device, find IP, find MAC, client trace; client history comes from diagnostics/")
    Component(connectivity_pkg, "connectivity/ (4 registered MCP tools)", "Python", "Firewall check, path analysis, inter-VLAN routing, traceroute")
    Component(network_pkg, "network/ (6 registered MCP tools)", "Python", "Firewall zones/policies, ACL rules, DNS policies, clients, networks")
}

Container_Boundary(api_int, "API Integration") {
    Component(api_ref, "UniFiClient / UnifiApiClient / UniFiNetworkClient", "httpx / requests", "")
}

Rel(analysis_pkg, api_ref, "Queries")
Rel(diagnostics_pkg, api_ref, "Queries")
Rel(discovery_pkg, api_ref, "Queries")
Rel(connectivity_pkg, api_ref, "Queries")
Rel(network_pkg, api_ref, "Reads")
Rel(port_mapper_c, api_ref, "Writes port_overrides unless previewing")
Rel(port_diag_c, api_ref, "Reads (guarded)")
Rel(port_diag_c, link_settings_c, "Uses")
Rel(naming_rules, port_mapper_c, "Feeds desired names")
Rel(smart_port_mapper_c, device_caps, "Uses")
Rel(topology_c, port_mapper_c, "Consumes")
@enduml
```

---

### 3.4 UniFi Protect Components

The Protect subsystem is architecturally isolated from the Network subsystem. It uses an async client, a separate configuration model, and a WebSocket event pipeline.

```mermaid
C4Component
    title Component Diagram - UniFi Protect Integration

    Container_Boundary(protect_sub, "Shared Library - Protect Subsystem") {
        Component(protect_client_c, "client.py / UniFiProtectClient", "Python asyncio + uiprotect", "Async wrapper around uiprotect ProtectApiClient. Manages connection lifecycle via ConnectionState state machine (DISCONNECTED / CONNECTING / CONNECTED / RECONNECTING / ERROR). Implements async context manager pattern. Provides typed device access properties: bootstrap, nvr, cameras, ai_ports, sensors, lights, chimes and doorlocks (the get_doorbells tool picks the cameras that have a chime). With read_only=True it runs over ReadOnlyProtectApiClient, as every MCP protect tool does.")
        Component(protect_config_c, "config.py / ProtectConfig", "Pydantic BaseModel", "Validated Protect configuration. SecretStr for password. from_env() class method with PROTECT_ prefix. to_client_kwargs() serialiser for uiprotect.")
        Component(protect_models_c, "models.py", "Pydantic", "Protect device models on a BaseDevice base: ProtectCamera, ProtectNVR, ProtectSensor, ProtectLight, ProtectChime, ProtectDoorlock and ProtectAIPort.")
        Component(events_c, "events.py / EventHandler", "Python asyncio", "Real-time WebSocket event processing. Typed ProtectEvent, ProtectEventType, ProtectEventCategory enums. EventFilter for subscription scoping. Unsubscribe function pattern.")
        Component(analytics_c, "analytics.py / EventAnalytics", "Python", "Event correlation and aggregation. Smart detection tracking by type (PERSON, VEHICLE, ANIMAL). Motion statistics, device health scoring from event patterns.")
        Component(aiport_c, "aiport.py / AIPortManager", "Python", "AI Port management for 3rd party ONVIF cameras. Handles smart detection capabilities on non-native cameras.")
        Component(health_c, "health.py / DeviceHealthMonitor", "Python asyncio", "Proactive device health monitoring. HealthTransition enum (DEGRADED, IMPROVED, RECOVERED). Configurable polling with thresholds. Health history tracking.")
        Component(mqtt_c, "mqtt.py / MQTTBridge", "Python asyncio + aiomqtt", "Home Assistant MQTT bridge. MQTTConfig Pydantic model. Publishes events with HA auto-discovery payload format. Configurable topic prefix and QoS.")
        Component(repository_c, "repository.py / DeviceRepository", "Python", "Typed device repositories and ProtectDeviceCache: a cache of Protect devices, refreshed from a connected UniFiProtectClient's bootstrap.")
    }

    System_Ext(protect_ctrl, "UniFi Protect Controller", "HTTPS REST + WebSocket")
    System_Ext(ha, "Home Assistant", "MQTT")

    Rel(protect_client_c, protect_config_c, "Configured by")
    Rel(protect_client_c, protect_ctrl, "REST bootstrap, WebSocket subscription", "HTTPS / WSS")
    Rel(events_c, protect_client_c, "Subscribes to WS messages")
    Rel(analytics_c, events_c, "Subscribes to filtered events")
    Rel(health_c, events_c, "Subscribes to device state events")
    Rel(mqtt_c, events_c, "Subscribes to all event categories")
    Rel(mqtt_c, ha, "Publishes events and auto-discovery", "MQTT")
    Rel(repository_c, protect_client_c, "Reads bootstrap data")
    Rel(aiport_c, protect_client_c, "Reads AI Port devices")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_Protect
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(protect_sub, "Shared Library - Protect Subsystem") {
    Component(protect_client_c, "UniFiProtectClient", "asyncio + uiprotect", "Async wrapper with ConnectionState machine and typed device properties")
    Component(protect_config_c, "ProtectConfig", "Pydantic", "Validated config with SecretStr and from_env()")
    Component(protect_models_c, "Protect Models", "Pydantic", "Camera, NVR, sensor, light, chime, doorlock and AI Port models")
    Component(events_c, "EventHandler", "asyncio", "WebSocket event processing with typed enums and subscription filtering")
    Component(analytics_c, "EventAnalytics", "Python", "Event correlation, smart detection stats, motion aggregation")
    Component(aiport_c, "AIPortManager", "Python", "AI Port management for 3rd party ONVIF cameras")
    Component(health_c, "DeviceHealthMonitor", "asyncio", "Proactive health monitoring with transition detection")
    Component(mqtt_c, "MQTTBridge", "asyncio + aiomqtt", "HA MQTT bridge with auto-discovery")
    Component(repository_c, "DeviceRepository", "Python", "Device cache refreshed from the client's bootstrap")
}

System_Ext(protect_ctrl, "UniFi Protect Controller")
System_Ext(ha, "Home Assistant")

Rel(protect_client_c, protect_ctrl, "REST + WebSocket")
Rel(events_c, protect_client_c, "Subscribes")
Rel(analytics_c, events_c, "Subscribes")
Rel(health_c, events_c, "Subscribes")
Rel(mqtt_c, events_c, "Subscribes")
Rel(mqtt_c, ha, "Publishes", "MQTT")
@enduml
```

---

### 3.5 MCP Server Components

The MCP server separates tool discovery from tool loading: an AI assistant explores the catalogue through the registry's metadata, and a handler is imported only when its tool is first described or run. Every call, on either surface, goes through one runner.

```mermaid
C4Component
    title Component Diagram - MCP Server

    Container_Boundary(mcp_sub, "MCP Server Container") {
        Component(mcp_server_c, "server.py / FastMCP app", "FastMCP", "Entry point (main: --version, --help, --surface, --config, --check). Registers the meta-tools search_tools, list_categories, get_tool_info and execute_tool, the resources unifi://catalog and unifi://config/status, and the prompts troubleshoot_port_link and plan_stp_change. The direct surface also lists every non-mutating, non-pipeline tool.")
        Component(lifespan_c, "server.py / lifespan", "Python", "Resolves the config, installs one SharedControllerClient (a UniFiClient behind ReadOnlyAsyncTransport that logs in on first use) that every async controller tool borrows, flushes the MCP call log on exit, sends the guards' request lines into it with UNIFI_MCP_REQUEST_AUDIT=on (or to a separate file for a path), and points sys.stdout at stderr so a stray print can't corrupt JSON-RPC.")
        Component(config_c, "config.py", "Python", "Working-directory-independent config discovery, per-family credential loading (controller, network_api, protect), the bounded Keychain and 1Password fallback, and the UNIFI_MCP_* settings.")
        Component(registry_c, "registry.py / ToolRegistry", "Python", "Loads and validates the YAML manifests on first access (thread-safe). Searches by query, category and tag; returns ToolMetadata. ToolProxy keeps a lazy handler per tool for ToolRegistry.execute.")
        Component(catalog_c, "catalog.py / ToolCatalog", "Python", "Builds each SDK Tool on first use: imports the handler and calls Tool.from_function, so the signature is the input schema and a typed return the output schema; adds the title and annotations.")
        Component(runner_c, "runner.py / ToolRunner", "Python", "Runs every call: refuse mutating tools, rewrite aliases, validate, gate the credential family, run under the concurrency cap and optional deadline, mask secrets, package the envelope with isError on failure, then write one line to the MCP call log (mcp/call_audit.py: the tool, its parameter names only, the duration and the outcome) in a shielded worker thread.")
        Component(tool_metadata_c, "registry.py / ToolMetadata", "Python dataclass", "Per-tool metadata: name, module, handler, title, description, category, priority, tags, parameters, credentials, mutates, pipeline, writes_local, idempotent, open_world, mcp, aliases.")

        Component(manifests_c, "manifests/ (7 YAML files)", "YAML", "Tool manifests by category: analysis.yaml (49 tools), connectivity.yaml (4), diagnostics.yaml (11), discovery.yaml (5), network.yaml (6), observability.yaml (7), protect.yaml (5).")

        Component(network_tools_c, "tools/network.py", "Python", "Network Integration API tools. Each call opens a UniFiNetworkClient behind the GET-only ReadOnlyAsyncTransport.")
        Component(protect_tools_c, "tools/protect.py", "Python", "Protect tools. Each call opens a UniFiProtectClient over ReadOnlyProtectApiClient.")
    }

    Container_Boundary(shared_c, "Shared Library") {
        Component(shared_ref, "Analysis / Diagnostics / Discovery / Connectivity / Network / Protect modules", "Python", "")
    }

    Rel(mcp_server_c, registry_c, "Searches and lists tools")
    Rel(mcp_server_c, runner_c, "Runs execute_tool and direct tools")
    Rel(mcp_server_c, lifespan_c, "Starts")
    Rel(lifespan_c, config_c, "Resolves config")
    Rel(registry_c, manifests_c, "Loads YAML on first access")
    Rel(registry_c, tool_metadata_c, "Holds one per tool")
    Rel(runner_c, catalog_c, "Gets the built tool")
    Rel(runner_c, config_c, "Gates credential families")
    Rel(catalog_c, registry_c, "Reads metadata")
    Rel(catalog_c, network_tools_c, "Lazily imports")
    Rel(catalog_c, protect_tools_c, "Lazily imports")
    Rel(catalog_c, shared_ref, "Lazily imports handlers")
    Rel(network_tools_c, shared_ref, "Calls the network managers")
    Rel(protect_tools_c, shared_ref, "Calls the Protect subsystem")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_MCP
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(mcp_sub, "MCP Server") {
    Component(mcp_server_c, "FastMCP app", "FastMCP", "Meta-tools, resources, prompts; direct surface")
    Component(lifespan_c, "lifespan", "Python", "Shared read-only controller client")
    Component(config_c, "config.py", "Python", "Config discovery, credential families, settings")
    Component(registry_c, "ToolRegistry", "Python", "YAML manifest loading and validation, search")
    Component(catalog_c, "ToolCatalog", "Python", "Builds SDK tools from handlers on first use")
    Component(runner_c, "ToolRunner", "Python", "Validate, gate, run, mask, package every call")
    Component(tool_metadata_c, "ToolMetadata", "Python dataclass", "Per-tool manifest fields")
    Component(manifests_c, "manifests/ (7 YAML files)", "YAML", "Tool definitions for 87 analysis, connectivity, diagnostics, discovery, network, observability and protect tools")
    Component(network_tools_c, "tools/network.py", "Python", "Integration API tools, GET-only client per call")
    Component(protect_tools_c, "tools/protect.py", "Python", "Protect tools over ReadOnlyProtectApiClient")
}

Container_Boundary(shared_c, "Shared Library") {
    Component(shared_ref, "All domain modules", "Python", "")
}

Rel(mcp_server_c, registry_c, "Searches")
Rel(mcp_server_c, runner_c, "Runs tools")
Rel(mcp_server_c, lifespan_c, "Starts")
Rel(lifespan_c, config_c, "Resolves config")
Rel(registry_c, manifests_c, "Loads YAML")
Rel(registry_c, tool_metadata_c, "Holds")
Rel(runner_c, catalog_c, "Gets tools")
Rel(runner_c, config_c, "Gates credentials")
Rel(catalog_c, network_tools_c, "Lazily imports")
Rel(catalog_c, protect_tools_c, "Lazily imports")
Rel(catalog_c, shared_ref, "Lazily imports")
Rel(network_tools_c, shared_ref, "Delegates")
Rel(protect_tools_c, shared_ref, "Delegates")
@enduml
```

---

## Level 4: Code Diagrams

### 4.1 API Client Class Structure

```mermaid
classDiagram
    class UnifiApiClient {
        +base_url: str
        +site: str
        +verify_ssl: bool
        +timeout: int
        +max_retries: int
        +retry_delay: float
        +session: requests.Session
        +is_authenticated: bool
        +auth_method: str
        +successful_endpoint: Optional[str]
        -_username: Optional[str]
        -_password: Optional[str]
        -_api_token: Optional[str]
        -_username_hash: Optional[str]
        -_password_hash: Optional[str]
        -_token_hash: Optional[str]
        +__init__(base_url, site, verify_ssl, username, password, api_token, timeout, max_retries, retry_delay)
        +login() bool
        +logout() bool
        +get_sites() list
        +get_devices(site_id) dict
        +get_clients(site_id) dict
        +get_device_details(site_id, device_id) dict
        +get_lldp_info(site_id, device_id) dict
        +update_device_port_table(device_id, port_table) bool
        +verify_port_update(device_id, port_idx, expected_name, max_retries) bool
        -_retry_request(func, *args, **kwargs) Any
        -_perform_login() bool
        -_update_port_overrides(device_id, device_details, port_table) bool
    }

    class EnhancedUnifiApiClient {
        +base_url: str
        +site: str
        +session: requests.Session
        +is_unifi_os: bool
        +__init__(base_url, site, verify_ssl, username, password, api_token, timeout, max_retries, retry_delay)
        +login() bool
        +get_devices(site_id) dict
        +get_device_details(device_id) dict
        +update_device_port_overrides(device_id, port_updates, auto_provision) bool
        +force_provision(device_mac) bool
        +verify_port_update_enhanced(device_id, port_updates, max_attempts, wait_per_attempt) dict
        +batch_update_with_verification(device_id, port_updates, verify_updates, auto_provision) tuple
    }

    class UnifiConfig {
        +base_url: str
        +site: str
        +api_token: Optional[str]
        +username: Optional[str]
        +password: Optional[str]
        +verify_ssl: bool
        +timeout: int
        +max_retries: int
        +retry_delay: float
        +default_format: str
        +default_output_dir: Optional[str]
        +default_diagram_dir: Optional[str]
        +__post_init__() None
    }

    class ToolkitAdapter {
        +api_client: EnhancedUnifiApiClient
        +__init__(api_client)
        +find_device_sync(query) list
        +analyze_link_quality_sync(device_id) dict
        +network_health_check_sync() dict
    }

    ToolkitAdapter --> EnhancedUnifiApiClient : wraps
    UnifiApiClient --> UnifiConfig : configured by
```

### PlantUML Equivalent

```plantuml
@startuml Code_APIClient
class UnifiApiClient {
    +base_url: str
    +site: str
    +session: Session
    +is_authenticated: bool
    +auth_method: str
    -_api_token: Optional[str]
    -_username: Optional[str]
    -_password: Optional[str]
    +login() bool
    +logout() bool
    +get_devices(site_id) dict
    +get_clients(site_id) dict
    +update_device_port_table(device_id, port_table) bool
    -_retry_request(func, *args, **kwargs) Any
    -_update_port_overrides(device_id, device_details, port_table) bool
}

class EnhancedUnifiApiClient {
    +update_device_port_overrides(device_id, port_updates, auto_provision) bool
    +force_provision(device_mac) bool
    +verify_port_update_enhanced(device_id, port_updates) dict
    +batch_update_with_verification(device_id, port_updates) tuple
}

class UnifiConfig {
    +base_url: str
    +site: str
    +api_token: Optional[str]
    +timeout: int
    +max_retries: int
    +retry_delay: float
    +__post_init__() None
}

class ToolkitAdapter {
    +api_client: EnhancedUnifiApiClient
    +find_device_sync(query) list
    +analyze_link_quality_sync(device_id) dict
    +network_health_check_sync() dict
}

ToolkitAdapter --> EnhancedUnifiApiClient
UnifiApiClient --> UnifiConfig
@enduml
```

---

### 4.2 Protect Client Class Structure

```mermaid
classDiagram
    class ConnectionState {
        <<enumeration>>
        DISCONNECTED
        CONNECTING
        CONNECTED
        RECONNECTING
        ERROR
    }

    class UniFiProtectClient {
        -_config: ProtectConfig
        -_client: Optional[ProtectApiClient]
        -_state: ConnectionState
        -_bootstrap: Optional[Bootstrap]
        -_ws_unsub: Optional[Callable]
        -_reconnect_task: Optional[Task]
        +config: ProtectConfig
        +state: ConnectionState
        +is_connected: bool
        +bootstrap: Optional[Bootstrap]
        +nvr: Optional[NVR]
        +cameras: dict[str, Camera]
        +ai_ports: dict[str, AiPort]
        +sensors: dict
        +lights: dict
        +chimes: dict
        +doorlocks: dict
        +__init__(config: ProtectConfig) None
        +__aenter__() UniFiProtectClient
        +__aexit__(exc_type, exc_val, exc_tb) None
        +connect() bool
        +disconnect() None
        +refresh() None
        +get_camera(camera_id) Camera
        +get_camera_by_name(name) Camera
        +get_ai_port(ai_port_id) AiPort
        +get_cameras_by_ai_port(ai_port_id) list
        +get_third_party_cameras() list
    }

    class ProtectConfig {
        +host: str
        +port: int
        +username: str
        +password: SecretStr
        +verify_ssl: bool
        +ws_timeout: int
        +cache_dir: Optional[Path]
        +store_sessions: bool
        +minimum_score: int
        +ignore_unadopted: bool
        +debug: bool
        +from_env(env_file, prefix) ProtectConfig$
        +to_client_kwargs() dict
        +validate_host(v) str$
        +validate_cache_dir(v) Path$
        +validate_authentication() ProtectConfig
    }

    class EventHandler {
        +client: UniFiProtectClient
        +subscription_count: int
        +subscribe(callback, event_filter) UnsubscribeFunc
        +clear_subscriptions() None
        -_handle_ws_message(msg) None
        -_dispatch_event(subscription, event) None
    }

    class EventAnalytics {
        +client: UniFiProtectClient
        +event_handler: EventHandler
        +start() None
        +stop() None
        +get_motion_stats(window) EventAggregation
        +get_smart_detect_stats(window) SmartDetectStats
        +get_device_health(device_id) DeviceHealth
        +subscribe_correlations(callback) UnsubscribeFunc
    }

    class DeviceHealthMonitor {
        +client: UniFiProtectClient
        +thresholds: HealthThresholds
        +subscribe_health_changes(callback) UnsubscribeFunc
        +start() Coroutine
        +stop() None
        +get_fleet_summary() dict
        -_periodic_health_check() Coroutine
        -_determine_transition(old_status, new_status) HealthTransition
    }

    class MQTTBridge {
        +config: MQTTConfig
        +is_connected: bool
        +start() Coroutine
        +stop() Coroutine
        +publish_device_state(device_id, state_type, value) Coroutine
        -_publish_message(message) Coroutine
        -_publish_discovery() Coroutine
    }

    UniFiProtectClient --> ConnectionState : tracks state via
    UniFiProtectClient --> ProtectConfig : configured by
    EventHandler --> UniFiProtectClient : subscribes to
    EventAnalytics --> EventHandler : subscribes via
    DeviceHealthMonitor --> EventHandler : subscribes via
    MQTTBridge --> EventHandler : subscribes via
    MQTTBridge --> UniFiProtectClient : holds reference
```

### PlantUML Equivalent

```plantuml
@startuml Code_ProtectClient
enum ConnectionState {
    DISCONNECTED
    CONNECTING
    CONNECTED
    RECONNECTING
    ERROR
}

class UniFiProtectClient {
    -_config: ProtectConfig
    -_client: ProtectApiClient
    -_state: ConnectionState
    -_bootstrap: Bootstrap
    +cameras: dict
    +ai_ports: dict
    +connect() bool
    +disconnect() None
    +refresh() None
}

class ProtectConfig {
    +host: str
    +port: int
    +username: str
    +password: SecretStr
    +from_env() ProtectConfig
    +to_client_kwargs() dict
}

class EventHandler {
    +subscribe(callback, event_filter) UnsubscribeFunc
    -_dispatch_event(subscription, event) None
}

class EventAnalytics {
    +get_motion_stats(window) EventAggregation
    +get_smart_detect_stats(window) SmartDetectStats
}

class DeviceHealthMonitor {
    +start() Coroutine
    +subscribe_health_changes(cb) Callable
}

class MQTTBridge {
    +start() Coroutine
    -_publish_message(message) Coroutine
    -_publish_discovery() Coroutine
}

UniFiProtectClient --> ConnectionState
UniFiProtectClient --> ProtectConfig
EventHandler --> UniFiProtectClient
EventAnalytics --> EventHandler
DeviceHealthMonitor --> EventHandler
MQTTBridge --> EventHandler
@enduml
```

---

### 4.3 Data Model Hierarchy

```mermaid
classDiagram
    class NetworkHealthStatus {
        <<enumeration>>
        EXCELLENT
        GOOD
        WARNING
        CRITICAL
        UNKNOWN
    }

    class PortInfo {
        +id: str
        +name: str
        +idx: int
        +media: str
        +is_uplink: bool
        +up: bool
        +enabled: bool
        +speed: int
        +full_duplex: bool
        +has_lldp_info: bool
        +lldp_info: dict
        +connected_device_name: Optional[str]
        +connected_port_name: Optional[str]
        +poe: bool
        +modified: bool
        +proposed_name: str
        +get_display_name() str
        +get_lldp_display_name() str
        +update_lldp_info(lldp_info) None
    }

    class DeviceInfo {
        +id: str
        +name: str
        +model: str
        +ip: str
        +mac: str
        +ports: list[PortInfo]
        +device_type: str
        +lldp_info: dict
        +get_device_type() str
        +get_color() str
    }

    class PortHealthMetrics {
        +port_idx: int
        +device_id: str
        +timestamp: datetime
        +rx_bytes: int
        +tx_bytes: int
        +rx_errors: int
        +tx_errors: int
        +utilization_percent: float
        +latency_ms: float
        +jitter_ms: float
        +packet_loss_percent: float
        +link_flap_count: int
        +uptime_seconds: int
        +utilization_history: list
        +calculate_health_score() float
        +get_health_status() NetworkHealthStatus
        +add_utilization_sample(util) None
        +get_peak_utilization() float
        +get_average_utilization() float
    }

    class DeviceHealthMetrics {
        +device_id: str
        +timestamp: datetime
        +cpu_usage_percent: float
        +memory_usage_percent: float
        +temperature_celsius: float
        +uptime_seconds: int
        +total_ports: int
        +active_ports: int
        +error_ports: int
        +port_metrics: dict[int, PortHealthMetrics]
        +firmware_version: str
        +active_alerts: list
        +add_port_metrics(port_metrics) None
        +calculate_overall_health_score() float
        +get_health_status() NetworkHealthStatus
        +get_critical_ports() list[int]
        +get_warning_ports() list[int]
    }

    class NetworkTopologyChange {
        +timestamp: datetime
        +change_type: str
        +device_id: str
        +details: dict
        +severity: str
        -_calculate_severity() str
    }

    class Device {
        +mac: str
        +name: str
        +model: str
        +ip: Optional[str]
        +type: Literal
        +uptime: int
        +connected_to: Optional[str]
        +port_idx: Optional[int]
        +site_id: Optional[str]
        +cpu_percent: Optional[float]
        +memory_percent: Optional[float]
        +is_infrastructure: bool
        +display_name: str
    }

    DeviceInfo "1" --> "many" PortInfo : contains
    DeviceHealthMetrics "1" --> "many" PortHealthMetrics : aggregates
    PortHealthMetrics --> NetworkHealthStatus : reports
    DeviceHealthMetrics --> NetworkHealthStatus : reports
    NetworkTopologyChange --> DeviceInfo : references
```

### PlantUML Equivalent

```plantuml
@startuml Code_DataModels
enum NetworkHealthStatus {
    EXCELLENT
    GOOD
    WARNING
    CRITICAL
    UNKNOWN
}

class PortInfo {
    +id: str
    +name: str
    +idx: int
    +speed: int
    +is_uplink: bool
    +poe: bool
    +lldp_info: dict
    +get_display_name() str
    +update_lldp_info(info) None
}

class DeviceInfo {
    +id: str
    +name: str
    +model: str
    +ip: str
    +mac: str
    +ports: list[PortInfo]
    +device_type: str
    +get_device_type() str
    +get_color() str
}

class PortHealthMetrics {
    +port_idx: int
    +utilization_percent: float
    +rx_errors: int
    +tx_errors: int
    +link_flap_count: int
    +calculate_health_score() float
    +get_health_status() NetworkHealthStatus
}

class DeviceHealthMetrics {
    +device_id: str
    +cpu_usage_percent: float
    +memory_usage_percent: float
    +temperature_celsius: float
    +port_metrics: dict
    +calculate_overall_health_score() float
    +get_health_status() NetworkHealthStatus
}

DeviceInfo "1" --> "*" PortInfo
DeviceHealthMetrics "1" --> "*" PortHealthMetrics
PortHealthMetrics --> NetworkHealthStatus
DeviceHealthMetrics --> NetworkHealthStatus
@enduml
```

---

### 4.4 Exception Hierarchy

```mermaid
classDiagram
    class Exception {
        <<Python built-in>>
    }

    class UniFiApiError {
        <<base>>
        Base exception for all UniFi API errors.
        Catch this to handle any UniFi error.
    }

    class UniFiRetryableError {
        <<abstract>>
        Errors where retry logic should activate.
        5xx responses, timeouts, connection failures.
    }

    class UniFiPermanentError {
        <<abstract>>
        Errors that must not be retried.
        4xx client errors — retrying won't help.
    }

    class UniFiConnectionError {
        Network connectivity failures.
        Connection refused, DNS resolution failure.
    }

    class UniFiTimeoutError {
        Request timed out.
        Controller unreachable within configured timeout.
    }

    class UniFiRateLimitError {
        HTTP 429 Too Many Requests.
        Back off and retry after delay.
    }

    class UniFiAuthenticationError {
        +auth_method: str
        +status_code: int
        HTTP 401 or 403.
        Token invalid or credentials rejected.
    }

    class UniFiPermissionError {
        Insufficient API privileges for operation.
        User account lacks required role.
    }

    class UniFiValidationError {
        Invalid input parameters.
        Bad site_id, device_id format, etc.
    }

    Exception <|-- UniFiApiError
    UniFiApiError <|-- UniFiRetryableError
    UniFiApiError <|-- UniFiPermanentError
    UniFiRetryableError <|-- UniFiConnectionError
    UniFiRetryableError <|-- UniFiTimeoutError
    UniFiRetryableError <|-- UniFiRateLimitError
    UniFiPermanentError <|-- UniFiAuthenticationError
    UniFiPermanentError <|-- UniFiPermissionError
    UniFiPermanentError <|-- UniFiValidationError
```

### PlantUML Equivalent

```plantuml
@startuml Code_Exceptions
class Exception <<Python built-in>>

class UniFiApiError <<base>>
class UniFiRetryableError <<abstract>>
class UniFiPermanentError <<abstract>>

class UniFiConnectionError
class UniFiTimeoutError
class UniFiRateLimitError

class UniFiAuthenticationError {
    +auth_method: str
    +status_code: int
}
class UniFiPermissionError
class UniFiValidationError

Exception <|-- UniFiApiError
UniFiApiError <|-- UniFiRetryableError
UniFiApiError <|-- UniFiPermanentError
UniFiRetryableError <|-- UniFiConnectionError
UniFiRetryableError <|-- UniFiTimeoutError
UniFiRetryableError <|-- UniFiRateLimitError
UniFiPermanentError <|-- UniFiAuthenticationError
UniFiPermanentError <|-- UniFiPermissionError
UniFiPermanentError <|-- UniFiValidationError
@enduml
```

---

## Provider and Platform Architecture

The C4 diagrams above show the system as a whole. Provider-specific behavior is documented separately so the main C4 view stays readable while preserving the details that matter during implementation and operations.

| Provider/interface | Architecture document | Implementation scope |
| --- | --- | --- |
| UniFi Network | [providers/unifi-network.md](providers/unifi-network.md) | Synchronous legacy REST client, async integrations API client, port mapping, analysis, discovery, connectivity, and network control wrappers. |
| UniFi Protect + MQTT | [providers/unifi-protect-mqtt.md](providers/unifi-protect-mqtt.md) | Async Protect client, WebSocket events, device repository, health/analytics, AI Port support, and Home Assistant MQTT discovery/state publishing. |
| AXIS provisioning | [providers/axis-provisioning.md](providers/axis-provisioning.md) | Scripted AXIS camera/device desired-state reconciliation through VAPIX, JSON API, ONVIF helpers, and MQTT target configuration. |
| MCP and automation | [providers/mcp-automation.md](providers/mcp-automation.md) | FastMCP stdio server, the discovery and direct surfaces, YAML manifests, lazy tool building (`ToolCatalog`), read-only execution (`ToolRunner` and the guards), and automation entry points. |

```mermaid
C4Container
    title Provider and Automation Boundaries - UniFi Management CLI

    Person(admin, "Network Administrator", "Runs CLI workflows")
    Person_Ext(agent, "AI Assistant", "Discovers automation tools")

    System_Ext(network_controller, "UniFi Network Controller", "Network REST APIs")
    System_Ext(protect_controller, "UniFi Protect Controller", "Protect REST + WebSocket")
    System_Ext(mqtt_broker, "MQTT Broker / Home Assistant", "MQTT discovery and state topics")

    System_Boundary(package, "unifi_mapper package") {
        Container(cli, "CLI entry points", "Typer / argparse", "Human-operated terminal workflows")
        Container(network_provider, "Network provider modules", "requests + httpx", "Topology, port naming, diagnostics, discovery, and Network control plane")
        Container(protect_provider, "Protect provider modules", "asyncio + uiprotect", "Protect inventory, events, AI Port, analytics, health, and MQTT bridge")
        Container(mcp_provider, "MCP automation interface", "FastMCP + YAML manifests", "Progressive tool discovery, lazy tool building and read-only execution through ToolRunner")
    }

    Rel(admin, cli, "Runs commands", "shell")
    Rel(agent, mcp_provider, "Discovers and runs read-only tools", "MCP stdio")
    Rel(cli, network_provider, "Calls workflows")
    Rel(cli, protect_provider, "Calls Protect workflows")
    Rel(mcp_provider, network_provider, "References registered tool wrappers")
    Rel(mcp_provider, protect_provider, "References Protect tool wrappers")
    Rel(network_provider, network_controller, "Reads; CLI commands write, the MCP server never does", "HTTPS REST")
    Rel(protect_provider, protect_controller, "Bootstraps and subscribes", "HTTPS / WSS")
    Rel(protect_provider, mqtt_broker, "Publishes discovery and state", "MQTT")
```

## Dynamic Runtime Flows

### Port discovery and desired-state port naming

The `discover` workflow now treats switch-port labels as desired state. For every router/switch port it chooses exactly one durable name:

1. LLDP/CDP device name when the controller provides a useful non-MAC neighbour name.
2. Active wired client name when LLDP only exposes a MAC address or no useful neighbour name.
3. Existing current name only when the port is active and the discovered client label is weak.
4. `Port x` when no device is connected, where `x` is the UniFi port index.

A plain `discover` previews: it chooses the names and writes the report and the diagram, but sends nothing to the controller. Only `discover --apply` writes. Writes are sent to `port_overrides`, not `port_table`. `port_table` is controller/device state; `port_overrides` is the writable configuration the UniFi UI persists.

```mermaid
C4Dynamic
    title Dynamic Diagram - Discover Desired-State Port Naming

    Person(admin, "Network administrator", "Runs discovery and expects switch-port labels to match connected devices")
    Container(cli, "unifi-mapper discover", "Typer CLI", "Loads config and starts the discovery workflow")
    Container_Boundary(shared_library, "unifi_mapper shared library") {
        Component(run_methods, "run_methods.py", "Python", "Builds desired names for every router and switch port")
        Component(naming, "_choose_port_name", "Python", "Chooses LLDP name, client name, active current name, or Port x")
        Component(mapper, "UnifiPortMapper", "Python", "With --apply only: batches per-device port name updates and provisions devices")
        Component(api, "UnifiApiClient", "requests", "Reads controller state and writes durable port_overrides")
    }
    System_Ext(controller, "UniFi Network Controller", "Stores device state and switch-port configuration")
    ContainerDb(report, "Reports and diagrams", "Markdown / Graphviz", "Generated topology artefacts (png, svg or html)")

    Rel(admin, cli, "1. Runs command", "shell")
    Rel(cli, run_methods, "2. Delegates discovery", "Python call")
    Rel(run_methods, api, "3. Reads devices, port_table, clients, LLDP", "HTTPS REST")
    Rel(api, controller, "4. GET /stat/device and /stat/sta", "HTTPS")
    Rel(run_methods, naming, "5. Selects desired name per port", "Python call")
    Rel(run_methods, mapper, "6. With --apply, sends per-device desired updates", "Python call")
    Rel(mapper, api, "7. With --apply, persists merged port_overrides", "PUT /rest/device by id")
    Rel(api, controller, "8. With --apply, writes port_overrides and force-provision", "HTTPS REST")
    Rel(run_methods, report, "9. Emits report and topology diagram", "file output")
```

### Protect event to Home Assistant MQTT

```mermaid
sequenceDiagram
    autonumber
    participant Protect as UniFi Protect Controller
    participant Client as UniFiProtectClient
    participant Events as EventHandler
    participant Bridge as MQTTBridge
    participant Broker as MQTT Broker
    participant HA as Home Assistant

    Client->>Protect: authenticate and load bootstrap
    Client->>Protect: subscribe to WebSocket updates
    Protect-->>Client: WSSubscriptionMessage
    Client->>Events: normalise event/action/model
    Events->>Bridge: dispatch matching ProtectEvent
    Bridge->>Broker: publish state topic
    Bridge->>Broker: publish discovery topic
    Broker-->>HA: device/entity state and metadata
```

### MCP discovery and lazy tool resolution

```mermaid
sequenceDiagram
    autonumber
    actor User as AI-assisted user
    participant Assistant as MCP client / assistant
    participant Server as unifi-mcp FastMCP server
    participant Registry as ToolRegistry
    participant Manifest as YAML manifests
    participant Runner as ToolRunner
    participant Catalog as ToolCatalog
    participant Tool as Tool implementation module

    User->>Assistant: "Find the STP tools"
    Assistant->>Server: search_tools(query="stp")
    Server->>Registry: search(query, category, tags)
    Registry->>Manifest: load manifests on first access
    Manifest-->>Registry: 87 tool metadata records
    Registry-->>Server: matching summaries
    Server-->>Assistant: tool names and descriptions
    Assistant->>Server: get_tool_info("discover_stp_topology")
    Server->>Catalog: find(tool_name)
    Catalog->>Tool: import the handler on first use
    Catalog-->>Server: input and output schemas, title, annotations
    Server-->>Assistant: full tool spec
    Assistant->>Server: execute_tool("discover_stp_topology", {})
    Server->>Runner: run(name, params)
    Note over Runner: refuse mutating tools, validate, gate the credential family
    Runner->>Tool: call the handler (read-only guarded client)
    Tool-->>Runner: STPTopology
    Runner-->>Server: masked envelope
    Server-->>Assistant: ok envelope with the result
```

## Key Design Decisions

### Synchronous Network API, Asynchronous Protect API

The original port-naming path (`UnifiApiClient`, `EnhancedUnifiApiClient`) and the read-only port diagnostics use `requests` (synchronous). The analysis, diagnostics, discovery and connectivity tools and the MCP server use the async `httpx` clients (`UniFiClient` for the classic controller API, `UniFiNetworkClient` for the Integration API), and the Protect client (`UniFiProtectClient`) uses `asyncio` and the `uiprotect` library, because Protect needs a persistent WebSocket subscription for real-time events. The sync port-diagnostics tools run under the MCP server too, each behind the sync read-only guard. The `ToolkitAdapter` class gives `unifi-network-toolkit` synchronous versions of three tools over its sync client; the MCP server doesn't use it.

### Retryable vs Permanent Exception Split

The exception hierarchy divides all errors into `UniFiRetryableError` and `UniFiPermanentError` before further specialisation. The retry loop in `UnifiApiClient._retry_request()` follows the same split: it retries timeouts, connection errors and 5xx, 408 and 429 responses with exponential backoff, while a 401 or 403 (`UniFiAuthenticationError`) or another 4xx (`UniFiPermissionError`) raises at once. When the attempts run out, a timeout raises `UniFiTimeoutError` and a connection failure `UniFiConnectionError`; an HTTP error that kept failing raises the base `UniFiApiError`. This prevents pointless retries on authentication failures (wrong password will always fail) while correctly retrying transient network issues.

### Credential Handling in the API Client

`UnifiApiClient` keeps a short SHA-256 hash of each credential next to the raw value (`_hash_for_verification()`), so a credential can be checked without exposing it, and logs the controller URL through `_sanitize_for_logging()`. Masking secrets in MCP results and errors, and in CLI error text, is the job of `core/utils/redact.py`.

### Code Mode Pattern in the MCP Server

The MCP server exposes `search_tools`, `list_categories`, `get_tool_info` and `execute_tool` as first-class tools rather than relying on the MCP tool listing protocol alone. This is the Code Mode pattern: AI assistants are expected to call `search_tools(query="stp")` and `get_tool_info("discover_stp_topology")` before `execute_tool("discover_stp_topology", {})`. This reduces hallucination of tool names and allows the assistant to inspect the full catalogue of 87 registered tools without receiving all tool definitions upfront. Hosts that defer tool schemas can use the direct surface (`UNIFI_MCP_TOOL_SURFACE=direct`) instead.

### YAML Manifests as the Tool Contract

Tool definitions live in YAML manifests rather than Python decorators. This separates the tool contract (what a tool is called, what it does, what parameters it accepts, which credential family it needs, whether it mutates) from the implementation (how it does it). The `ToolRegistry` loads and validates manifests lazily; `ToolCatalog` defers the actual `importlib.import_module()` call until a tool is first described or run (`ToolProxy` does the same for `ToolRegistry.execute`). The practical result is fast MCP server startup even with a large tool catalogue.

### Ground Truth Verification

`GroundTruthVerifier` exists because the UniFi API has known response caching behaviour where a `PUT` to update port names may return success, but a subsequent `GET` returns the old values for several seconds. Rather than relying on the API to confirm its own writes, the verifier performs multi-read consistency checks to detect when the controller has actually applied a change. This is documented as a workaround for API behaviour that is outside the project's control.

### Topology Wrapper Module

`network_topology.py` is a one-line re-export of `enhanced_network_topology.py`. This pattern preserves backward compatibility for any callers using the original import path (`from unifi_mapper.network_topology import NetworkTopology`) while consolidating the actual implementation in the enhanced module. New code imports from `enhanced_network_topology` directly.
