# C4 Architecture: UniFi Management CLI

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
6. [Key Design Decisions](#key-design-decisions)

---

## Overview

The UniFi Management CLI is an enterprise-grade Python automation platform for Ubiquiti UniFi networks. It provides four distinct entry points—three CLI tools and one MCP server—all built on a shared library of API clients, domain models, and analysis engines. The platform spans two separate UniFi product lines (Network and Protect) and integrates with Home Assistant via MQTT and with AI assistants via the Model Context Protocol.

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

    System(unifi_mgmt, "UniFi Management CLI", "Enterprise UniFi automation platform. Provides CLI tools and an MCP server for network management, topology visualisation, diagnostics, and Protect integration.")

    System_Ext(unifi_network, "UniFi Network Controller", "Ubiquiti UniFi OS or legacy controller. Manages switches, access points, and gateways via REST API.")
    System_Ext(unifi_protect, "UniFi Protect Controller", "Ubiquiti video security platform. Manages cameras, sensors, doorbells, and AI Ports via REST and WebSocket.")
    System_Ext(home_assistant, "Home Assistant", "Home automation platform. Receives UniFi Protect events via MQTT for automation rules.")
    System_Ext(ai_assistant, "AI Assistant (Claude / MCP Client)", "Large language model or MCP-compatible client. Uses the MCP server to discover and invoke network management tools.")

    Rel(admin, unifi_mgmt, "Runs CLI commands", "terminal / shell")
    Rel(ai_user, ai_assistant, "Issues natural language requests", "chat")
    Rel(ai_assistant, unifi_mgmt, "Invokes tools", "MCP / JSON-RPC over stdio")
    Rel(unifi_mgmt, unifi_network, "Reads topology, stats, and config. Writes port names, STP priorities.", "HTTPS REST API")
    Rel(unifi_mgmt, unifi_protect, "Reads device inventory and events. Subscribes to real-time updates.", "HTTPS REST + WebSocket")
    Rel(unifi_mgmt, home_assistant, "Publishes camera events and device states with auto-discovery", "MQTT")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Context
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Context.puml

Person(admin, "Network Administrator", "Manages UniFi network infrastructure, cameras, and security devices")
Person(ai_user, "AI-Assisted User", "Uses Claude or MCP-compatible AI assistants for network troubleshooting")

System(unifi_mgmt, "UniFi Management CLI", "Enterprise UniFi automation platform providing CLI tools and MCP server for network management, topology visualisation, diagnostics, and Protect integration.")

System_Ext(unifi_network, "UniFi Network Controller", "Ubiquiti UniFi OS or legacy controller. Manages switches, APs, and gateways via REST API.")
System_Ext(unifi_protect, "UniFi Protect Controller", "Ubiquiti video security platform. Manages cameras, sensors, doorbells, and AI Ports.")
System_Ext(home_assistant, "Home Assistant", "Home automation platform receiving Protect events via MQTT.")
System_Ext(ai_assistant, "AI Assistant (Claude / MCP Client)", "LLM or MCP-compatible client invoking network management tools.")

Rel(admin, unifi_mgmt, "Runs CLI commands", "terminal / shell")
Rel(ai_user, ai_assistant, "Issues natural language requests", "chat")
Rel(ai_assistant, unifi_mgmt, "Invokes tools", "MCP / JSON-RPC over stdio")
Rel(unifi_mgmt, unifi_network, "Reads and writes network configuration", "HTTPS REST")
Rel(unifi_mgmt, unifi_protect, "Reads devices and events, subscribes to updates", "HTTPS REST + WebSocket")
Rel(unifi_mgmt, home_assistant, "Publishes events with MQTT auto-discovery", "MQTT")
@enduml
```

### Context Notes

The platform serves two distinct user personas with different interaction models:

- The **Network Administrator** invokes CLI tools directly. They choose the appropriate tool (`unifi-mapper`, `unifi-network-toolkit`, or `unifi-inventory`) depending on whether they need interactive output, scripting compatibility, or inventory reports.

- The **AI-Assisted User** interacts indirectly through an MCP-compatible client such as Claude Desktop. The AI assistant uses `unifi-mcp` as a tool provider, enabling natural-language network troubleshooting without the user needing to know specific command syntax.

The dual-controller architecture (Network + Protect) reflects Ubiquiti's product split: network infrastructure and video security run on separate controllers with different APIs, authentication models, and communication protocols.

---

## Level 2: Container Diagram

At the container level, the UniFi Management CLI resolves into five runnable units — four Python entry-point commands and one shared library that they all import. Each container has a distinct technology profile and responsibility boundary.

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
        Container(unifi_mapper_cli, "unifi-mapper", "Python / Typer / Rich", "Primary interactive CLI. Subcommands: discover, find, analyze, diagnose, stp, inventory, verify. Rich terminal UI with tables and progress.")
        Container(network_toolkit_cli, "unifi-network-toolkit", "Python / argparse", "Script-friendly CLI. Subcommands: discover, analyze, find, diagnose. Designed for piping and automation.")
        Container(inventory_cli, "unifi-inventory", "Python / argparse", "Dedicated inventory report generator. Exports device and client inventory in structured formats.")
        Container(mcp_server, "unifi-mcp", "Python / FastMCP", "MCP server exposing 36+ tools via Model Context Protocol. Runs over stdio. Supports tool discovery, lazy loading, and YAML-manifest-driven tool registration.")
        Container(shared_lib, "unifi_mapper library", "Python 3.12 package", "Shared library providing API clients, domain models, analysis engines, diagnostic tools, discovery utilities, connectivity analysis, Protect integration, topology visualisation, and report generation.")
    }

    Rel(admin, unifi_mapper_cli, "Runs commands", "shell")
    Rel(admin, network_toolkit_cli, "Runs commands", "shell")
    Rel(admin, inventory_cli, "Runs commands", "shell")
    Rel(ai_assistant, mcp_server, "Invokes tools", "MCP / JSON-RPC stdio")
    Rel(unifi_mapper_cli, shared_lib, "Imports and calls")
    Rel(network_toolkit_cli, shared_lib, "Imports and calls")
    Rel(inventory_cli, shared_lib, "Imports and calls")
    Rel(mcp_server, shared_lib, "Imports and calls")
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
    Container(inventory_cli, "unifi-inventory", "Python / argparse", "Inventory report generator")
    Container(mcp_server, "unifi-mcp", "Python / FastMCP", "MCP server exposing 36+ tools over stdio")
    Container(shared_lib, "unifi_mapper library", "Python 3.12 package", "Shared library: API clients, models, analysis, diagnostics, Protect, topology")
}

Rel(admin, unifi_mapper_cli, "Runs commands", "shell")
Rel(admin, network_toolkit_cli, "Runs commands", "shell")
Rel(admin, inventory_cli, "Runs commands", "shell")
Rel(ai_assistant, mcp_server, "Invokes tools", "MCP / JSON-RPC stdio")
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

The **four CLI entry points are thin shells** over the shared library. They handle argument parsing, output formatting, and process lifecycle. No business logic lives in the entry points — this is enforced by the `pyproject.toml` entry-point declarations, which map directly to CLI module `main` or `app` functions.

The **shared library** is the architectural centre of gravity. All domain logic, API interactions, and integration code live here. This makes the platform easy to extend: a new CLI tool or a different front-end (e.g., a web API) can be added without touching existing containers.

The `unifi-mapper` and `unifi-network-toolkit` CLIs offer overlapping functionality with different UX targets. `unifi-mapper` uses Typer + Rich for an interactive terminal experience; `unifi-network-toolkit` uses argparse for scripting compatibility. This is a deliberate duplication to serve both audiences without compromise.

---

## Level 3: Component Diagrams

### 3.1 CLI Layer Components

The CLI containers delegate to specific modules within the shared library. This diagram shows the internal components of the CLI layer and their dependencies on the library core.

```mermaid
C4Component
    title Component Diagram - CLI Layer

    Container_Boundary(cli_layer, "CLI Entry Points") {
        Component(typer_cli, "typer_cli.py", "Typer + Rich", "unifi-mapper entry point. Defines subcommands: discover, find, analyze, diagnose, stp, inventory, verify. Global state for config path and debug flag.")
        Component(network_cli, "network_cli.py", "argparse", "unifi-network-toolkit entry point. Subcommands: discover, analyze, find, diagnose. Optimised for scripting.")
        Component(inventory_cli_comp, "inventory_cli.py", "argparse", "unifi-inventory entry point. Produces structured inventory reports.")
        Component(completions, "completions.py", "Python", "Shell completion support for CLI argument completion across bash/zsh/fish.")
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
    Rel(inventory_cli_comp, config_comp, "Reads config")
    Rel(inventory_cli_comp, api_client_comp, "Queries devices and clients")
    Rel(run_methods, api_client_comp, "Creates and uses")
    Rel(run_methods, report_gen, "Generates reports")
    Rel(typer_cli, completions, "Registers completions")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_CLI
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(cli_layer, "CLI Entry Points") {
    Component(typer_cli, "typer_cli.py", "Typer + Rich", "unifi-mapper: discover, find, analyze, diagnose, stp, inventory, verify")
    Component(network_cli, "network_cli.py", "argparse", "unifi-network-toolkit: discover, analyze, find, diagnose")
    Component(inventory_cli_comp, "inventory_cli.py", "argparse", "unifi-inventory: structured inventory reports")
    Component(completions, "completions.py", "Python", "Shell completion support")
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
        Component(api_client_c, "api_client.py / UnifiApiClient", "requests + Session", "Synchronous REST client for UniFi Network Controller. Dual auth: API token or username/password. Supports UniFi OS and legacy controller URL schemas. Retry logic with exponential backoff (capped 1-10 retries, 0.1-10s delay). Sanitises credentials from logs.")
        Component(enhanced_api, "enhanced_api_client.py / EnhancedUnifiApiClient", "requests + httpx", "Extended API client adding async capability (httpx), automatic provisioning flows, and additional endpoint coverage.")
        Component(config_c, "config.py / UnifiConfig", "Python dataclass", "Validated configuration. Clamps timeout (1-300s), retries (1-10), and delay (0.1-10s). Requires api_token OR username+password.")
        Component(exceptions_c, "exceptions.py", "Python exception hierarchy", "Structured exception tree. Retryable vs Permanent split determines whether retry logic activates. Includes UniFiAuthenticationError, UniFiConnectionError, UniFiTimeoutError, UniFiRateLimitError, UniFiPermissionError, UniFiValidationError.")
        Component(ground_truth, "ground_truth_verification.py / GroundTruthVerifier", "Python", "Multi-read consistency checking to work around UniFi API response caching. Verifies applied changes actually took effect.")
        Component(toolkit_adapters_c, "toolkit_adapters.py / ToolkitAdapter", "Python adapter pattern", "Bridges the synchronous UnifiApiClient to the async analysis tool interfaces. Provides synchronous wrapper methods for each tool category.")
    }

    System_Ext(unifi_network_c, "UniFi Network Controller", "HTTPS REST API")

    Rel(api_client_c, unifi_network_c, "GET/POST/PUT requests", "HTTPS")
    Rel(enhanced_api, api_client_c, "Extends")
    Rel(enhanced_api, unifi_network_c, "Additional REST calls", "HTTPS")
    Rel(api_client_c, exceptions_c, "Raises on error")
    Rel(api_client_c, config_c, "Configured by")
    Rel(ground_truth, api_client_c, "Uses for device lookups only")
    Rel(toolkit_adapters_c, api_client_c, "Wraps")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_API
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(api_layer, "Shared Library - API Integration") {
    Component(api_client_c, "UnifiApiClient", "requests", "Synchronous REST client with dual auth, retry, and credential sanitisation")
    Component(enhanced_api, "EnhancedUnifiApiClient", "requests + httpx", "Extended client with async capability and provisioning flows")
    Component(config_c, "UnifiConfig", "dataclass", "Validated configuration with input clamping")
    Component(exceptions_c, "Exception hierarchy", "Python", "Retryable vs Permanent error split")
    Component(ground_truth, "GroundTruthVerifier", "Python", "Multi-read consistency checking for API cache workaround")
    Component(toolkit_adapters_c, "ToolkitAdapter", "Python adapter", "Sync wrappers bridging API client to analysis tools")
}

System_Ext(unifi_network_c, "UniFi Network Controller", "HTTPS REST")

Rel(api_client_c, unifi_network_c, "REST calls", "HTTPS")
Rel(enhanced_api, api_client_c, "Extends")
Rel(api_client_c, exceptions_c, "Raises on error")
Rel(ground_truth, api_client_c, "Uses for lookups")
Rel(toolkit_adapters_c, api_client_c, "Wraps")
@enduml
```

---

### 3.3 Analysis and Diagnostic Components

The intelligence layer contains the 36+ tools organised into four functional packages. All tools receive an API client instance and return structured results.

```mermaid
C4Component
    title Component Diagram - Analysis, Diagnostics, Discovery, Connectivity

    Container_Boundary(intelligence, "Shared Library - Intelligence Layer") {

        Component(port_mapper_c, "port_mapper.py / PortMapper", "Python", "Port mapping with LLDP/CDP discovery. Builds port-to-device connection maps.")
        Component(smart_port_mapper_c, "smart_port_mapper.py / SmartPortMapper", "Python", "Device-aware port mapping. Uses device capability profiles to interpret port data correctly per model.")
        Component(device_caps, "device_capabilities.py", "Python", "Model-specific capability detection. Determines port count, SFP slots, PoE capabilities, and uplink ports by hardware model.")
        Component(topology_c, "enhanced_network_topology.py / NetworkTopology", "Python / graphviz", "Topology graph generation. Outputs: PNG, SVG, HTML interactive, Mermaid. Wraps graphviz for static formats.")

        Component(analysis_pkg, "analysis/ (10 modules)", "Python", "capacity_planning, firmware_advisor, ip_conflicts, lag_monitoring, link_quality, mac_analyzer, qos_validation, storm_detection, stp_optimizer, vlan_diagnostics")
        Component(diagnostics_pkg, "diagnostics/ (4 modules)", "Python", "connectivity_analysis, network_health, performance_analysis, security_audit")
        Component(discovery_pkg, "discovery/ (4 modules)", "Python", "client_trace, find_device, find_ip, find_mac")
        Component(connectivity_pkg, "connectivity/ (3 modules)", "Python", "firewall_check, path_analysis, traceroute")
        Component(network_pkg, "network/ (10 modules)", "Python", "Control plane: acl, client, clients, config, dns, dpi, firewall, networks, sites, statistics, traffic_matching")
    }

    Container_Boundary(api_int, "API Integration") {
        Component(api_ref, "UnifiApiClient / EnhancedUnifiApiClient", "requests", "")
    }

    Rel(analysis_pkg, api_ref, "Queries device data")
    Rel(diagnostics_pkg, api_ref, "Queries health and stats")
    Rel(discovery_pkg, api_ref, "Queries device and client tables")
    Rel(connectivity_pkg, api_ref, "Queries firewall rules and routing")
    Rel(network_pkg, api_ref, "Reads and writes network config")
    Rel(port_mapper_c, api_ref, "Queries ports and LLDP data")
    Rel(smart_port_mapper_c, port_mapper_c, "Extends")
    Rel(smart_port_mapper_c, device_caps, "Uses capability profiles")
    Rel(topology_c, port_mapper_c, "Consumes port map")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_Intelligence
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(intelligence, "Shared Library - Intelligence Layer") {
    Component(port_mapper_c, "PortMapper", "Python", "LLDP/CDP port mapping")
    Component(smart_port_mapper_c, "SmartPortMapper", "Python", "Device-aware port mapping")
    Component(device_caps, "DeviceCapabilities", "Python", "Model-specific capability profiles")
    Component(topology_c, "NetworkTopology", "Python / graphviz", "Topology graph: PNG, SVG, HTML, Mermaid")
    Component(analysis_pkg, "analysis/ (10 modules)", "Python", "IP conflicts, STP, VLAN, QoS, capacity, firmware, LAG, link quality, MAC, storm detection")
    Component(diagnostics_pkg, "diagnostics/ (4 modules)", "Python", "Health, performance, security, connectivity")
    Component(discovery_pkg, "discovery/ (4 modules)", "Python", "Find device, find IP, find MAC, client trace")
    Component(connectivity_pkg, "connectivity/ (3 modules)", "Python", "Firewall check, path analysis, traceroute")
    Component(network_pkg, "network/ (10 modules)", "Python", "ACL, DNS, DPI, firewall, networks, sites, statistics")
}

Container_Boundary(api_int, "API Integration") {
    Component(api_ref, "UnifiApiClient", "requests", "")
}

Rel(analysis_pkg, api_ref, "Queries")
Rel(diagnostics_pkg, api_ref, "Queries")
Rel(discovery_pkg, api_ref, "Queries")
Rel(connectivity_pkg, api_ref, "Queries")
Rel(network_pkg, api_ref, "Reads and writes")
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
        Component(protect_client_c, "client.py / UniFiProtectClient", "Python asyncio + uiprotect", "Async wrapper around uiprotect ProtectApiClient. Manages connection lifecycle via ConnectionState state machine (DISCONNECTED / CONNECTING / CONNECTED / RECONNECTING / ERROR). Implements async context manager pattern. Provides typed device access properties: cameras, ai_ports, sensors, lights, doorbells.")
        Component(protect_config_c, "config.py / ProtectConfig", "Pydantic BaseModel", "Validated Protect configuration. SecretStr for password. from_env() class method with PROTECT_ prefix. to_client_kwargs() serialiser for uiprotect.")
        Component(protect_models_c, "models.py", "Python dataclasses", "Protect domain models: camera state, NVR info, sensor state, event records.")
        Component(events_c, "events.py / EventHandler", "Python asyncio", "Real-time WebSocket event processing. Typed ProtectEvent, ProtectEventType, ProtectEventCategory enums. EventFilter for subscription scoping. Unsubscribe function pattern.")
        Component(analytics_c, "analytics.py / EventAnalytics", "Python", "Event correlation and aggregation. Smart detection tracking by type (PERSON, VEHICLE, ANIMAL). Motion statistics, device health scoring from event patterns.")
        Component(aiport_c, "aiport.py", "Python", "AI Port management for 3rd party ONVIF cameras. Handles smart detection capabilities on non-native cameras.")
        Component(health_c, "health.py / DeviceHealthMonitor", "Python asyncio", "Proactive device health monitoring. HealthTransition enum (DEGRADED, IMPROVED, RECOVERED). Configurable polling with thresholds. Health history tracking.")
        Component(mqtt_c, "mqtt.py / MQTTBridge", "Python asyncio + aiomqtt", "Home Assistant MQTT bridge. MQTTConfig Pydantic model. Publishes events with HA auto-discovery payload format. Configurable topic prefix and QoS.")
        Component(repository_c, "repository.py", "Python", "Data access layer over ProtectApiClient. Decouples domain logic from uiprotect library internals.")
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
    Component(protect_models_c, "Protect Models", "Python dataclasses", "Camera, NVR, sensor, event domain models")
    Component(events_c, "EventHandler", "asyncio", "WebSocket event processing with typed enums and subscription filtering")
    Component(analytics_c, "EventAnalytics", "Python", "Event correlation, smart detection stats, motion aggregation")
    Component(aiport_c, "AiPort Manager", "Python", "AI Port management for 3rd party ONVIF cameras")
    Component(health_c, "DeviceHealthMonitor", "asyncio", "Proactive health monitoring with transition detection")
    Component(mqtt_c, "MQTTBridge", "asyncio + aiomqtt", "HA MQTT bridge with auto-discovery")
    Component(repository_c, "Repository", "Python", "Data access layer over uiprotect client")
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

The MCP server uses a Code Mode architecture pattern: tool discovery is separated from tool execution, enabling AI assistants to efficiently explore the tool catalogue before committing to specific calls.

```mermaid
C4Component
    title Component Diagram - MCP Server

    Container_Boundary(mcp_sub, "MCP Server Container") {
        Component(mcp_server_c, "server.py / FastMCP app", "FastMCP", "FastMCP server named 'unifi-management'. Exposes three meta-tools: search_tools, list_categories, get_tool_info. Acts as the coordination layer — AI assistants call these first to discover available tools, then invoke specific tools by name.")
        Component(registry_c, "registry.py / ToolRegistry", "Python", "Dynamic tool discovery from YAML manifests. Singleton with thread-safe lazy loading via ToolProxy. Supports search by query string, category, and tag list. Returns summary or full detail levels.")
        Component(tool_proxy_c, "registry.py / ToolProxy", "Python", "Lazy-loading proxy per tool. Defers importlib.import_module() until first execution. Thread-safe via Lock. Reduces startup time and memory when only a subset of tools is used.")
        Component(tool_metadata_c, "registry.py / ToolMetadata", "Python dataclass", "Per-tool metadata: name, module path, handler name, description, category, priority (P1/P2/P3), tags list, parameter schema.")

        Component(manifests_c, "manifests/ (6 YAML files)", "YAML", "Tool manifests by category: analysis.yaml (13 tools), diagnostics.yaml (4 tools), discovery.yaml (4 tools), connectivity.yaml (3 tools), network.yaml, protect.yaml (5 tools). Each entry declares module, handler, description, priority, and tags.")

        Component(network_tools_c, "tools/network.py", "Python", "Tool handler implementations for network category tools. Wraps shared library calls, serialises results to JSON-safe dicts.")
        Component(protect_tools_c, "tools/protect.py", "Python", "Tool handler implementations for Protect category tools. Initialises async Protect client, awaits results, returns structured data.")
    }

    Container_Boundary(shared_c, "Shared Library") {
        Component(shared_ref, "Analysis / Diagnostics / Discovery / Connectivity / Network / Protect modules", "Python", "")
    }

    Rel(mcp_server_c, registry_c, "Queries for tool search and listing")
    Rel(mcp_server_c, tool_proxy_c, "Executes tools via proxy")
    Rel(registry_c, manifests_c, "Loads YAML on first access")
    Rel(registry_c, tool_proxy_c, "Creates one proxy per tool")
    Rel(tool_proxy_c, tool_metadata_c, "Holds metadata")
    Rel(tool_proxy_c, network_tools_c, "Lazily imports and calls")
    Rel(tool_proxy_c, protect_tools_c, "Lazily imports and calls")
    Rel(network_tools_c, shared_ref, "Calls analysis, diagnostics, discovery, connectivity modules")
    Rel(protect_tools_c, shared_ref, "Calls Protect subsystem")
```

### PlantUML Equivalent

```plantuml
@startuml C4_Component_MCP
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Component.puml

Container_Boundary(mcp_sub, "MCP Server") {
    Component(mcp_server_c, "FastMCP app", "FastMCP", "Exposes search_tools, list_categories, get_tool_info meta-tools")
    Component(registry_c, "ToolRegistry", "Python", "Singleton: YAML manifest loading, search by query/category/tag")
    Component(tool_proxy_c, "ToolProxy", "Python", "Lazy-loading proxy with thread-safe importlib deferred load")
    Component(tool_metadata_c, "ToolMetadata", "Python dataclass", "name, module, handler, description, category, priority, tags")
    Component(manifests_c, "manifests/ (6 YAML files)", "YAML", "Tool definitions for analysis, diagnostics, discovery, connectivity, network, protect")
    Component(network_tools_c, "tools/network.py", "Python", "Network tool handler implementations")
    Component(protect_tools_c, "tools/protect.py", "Python", "Protect tool handler implementations")
}

Container_Boundary(shared_c, "Shared Library") {
    Component(shared_ref, "All domain modules", "Python", "")
}

Rel(mcp_server_c, registry_c, "Queries")
Rel(registry_c, manifests_c, "Loads YAML")
Rel(registry_c, tool_proxy_c, "Creates")
Rel(tool_proxy_c, network_tools_c, "Lazily calls")
Rel(tool_proxy_c, protect_tools_c, "Lazily calls")
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
        +logout() None
        +get_devices(site) dict
        +get_clients(site) dict
        +get_device_stats(device_id) dict
        +put_device(device_id, data) dict
        -_request(method, endpoint, data) dict
        -_retry_request(method, endpoint, data) dict
        -_authenticate_token() bool
        -_authenticate_user_pass() bool
    }

    class EnhancedUnifiApiClient {
        +base_url: str
        +site: str
        +session: requests.Session
        +__init__(base_url, site, verify_ssl, username, password, api_token, timeout, max_retries, retry_delay)
        +get_port_overrides(device_id) list
        +set_port_overrides(device_id, overrides) dict
        +provision_device(device_id) dict
        +async_get_devices() Coroutine
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
        +api_client: UnifiApiClient
        +__init__(api_client)
        +find_device_sync(query) list
        +find_ip_sync(ip_address) dict
        +find_mac_sync(mac_address) dict
        +analyze_network_sync() dict
        +health_check_sync() dict
    }

    EnhancedUnifiApiClient --|> UnifiApiClient : extends
    ToolkitAdapter --> UnifiApiClient : wraps
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
    +logout() None
    +get_devices(site) dict
    +get_clients(site) dict
    -_request(method, endpoint, data) dict
    -_retry_request(method, endpoint, data) dict
    -_authenticate_token() bool
    -_authenticate_user_pass() bool
}

class EnhancedUnifiApiClient {
    +get_port_overrides(device_id) list
    +set_port_overrides(device_id, overrides) dict
    +provision_device(device_id) dict
    +async_get_devices() Coroutine
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
    +api_client: UnifiApiClient
    +find_device_sync(query) list
    +find_ip_sync(ip) dict
    +find_mac_sync(mac) dict
}

EnhancedUnifiApiClient --|> UnifiApiClient
ToolkitAdapter --> UnifiApiClient
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
        +doorbells: dict
        +__init__(config: ProtectConfig) None
        +__aenter__() UniFiProtectClient
        +__aexit__(exc_type, exc_val, exc_tb) None
        +connect() None
        +disconnect() None
        -_handle_disconnect() None
        -_reconnect_loop() None
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
        -_client: UniFiProtectClient
        -_subscriptions: list
        +subscribe(callback, filter) Callable
        +unsubscribe(token) None
        -_dispatch(message) None
    }

    class EventAnalytics {
        -_client: UniFiProtectClient
        -_handler: EventHandler
        -_event_buffer: deque
        +start() None
        +stop() None
        +get_motion_stats() MotionStats
        +get_smart_detect_counts() dict
        +get_device_health() DeviceHealth
    }

    class DeviceHealthMonitor {
        -_client: UniFiProtectClient
        -_handler: EventHandler
        -_health_cache: dict
        -_poll_interval: int
        +subscribe_health_changes(callback) Callable
        +start() Coroutine
        +stop() None
        -_poll_devices() Coroutine
        -_detect_transitions() None
    }

    class MQTTBridge {
        -_protect_client: UniFiProtectClient
        -_config: MQTTConfig
        -_handler: EventHandler
        +start() Coroutine
        +stop() Coroutine
        -_publish_event(event) Coroutine
        -_publish_discovery(device) Coroutine
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
    +connect() None
    +disconnect() None
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
    +subscribe(callback, filter) Callable
    -_dispatch(message) None
}

class EventAnalytics {
    +get_motion_stats() MotionStats
    +get_smart_detect_counts() dict
}

class DeviceHealthMonitor {
    +start() Coroutine
    +subscribe_health_changes(cb) Callable
}

class MQTTBridge {
    +start() Coroutine
    -_publish_event(event) Coroutine
    -_publish_discovery(device) Coroutine
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

## Key Design Decisions

### Synchronous Network API, Asynchronous Protect API

The Network API client (`UnifiApiClient`, `EnhancedUnifiApiClient`) uses `requests` (synchronous). The Protect client (`UniFiProtectClient`) uses `asyncio` and the `uiprotect` library. This split reflects the fundamental difference between the two product lines: the Network API is a request-response REST API that maps naturally to synchronous code; the Protect API requires a persistent WebSocket subscription for real-time event delivery, which demands an async runtime. The `ToolkitAdapter` class exists specifically to bridge these two models when the MCP server needs to call both from a single async context.

### Retryable vs Permanent Exception Split

The exception hierarchy divides all errors into `UniFiRetryableError` and `UniFiPermanentError` before further specialisation. This binary distinction is load-bearing: the retry loop in `UnifiApiClient._retry_request()` catches `UniFiRetryableError` and applies exponential backoff, while `UniFiPermanentError` propagates immediately. This prevents pointless retries on authentication failures (wrong password will always fail) while correctly retrying transient network issues.

### Credential Sanitisation in the API Client

`UnifiApiClient` stores SHA-256 hashes of credentials alongside the raw values, and all logging methods call `_sanitize_for_logging()` before writing. This is an active defence against credential leakage into log files, which is a real operational risk in always-on network automation scripts.

### Code Mode Pattern in the MCP Server

The MCP server exposes `search_tools`, `list_categories`, and `get_tool_info` as first-class tools rather than relying on the MCP tool listing protocol alone. This is the Code Mode pattern: AI assistants are expected to call `search_tools(query="stp")` to discover relevant tools before invoking `discover_stp_topology()`. This reduces hallucination of tool names and allows the assistant to select the most appropriate tool from the full catalogue of 36+ options without receiving all tool definitions upfront.

### YAML Manifests as the Tool Contract

Tool definitions live in YAML manifests rather than Python decorators. This separates the tool contract (what a tool is called, what it does, what parameters it accepts) from the implementation (how it does it). The `ToolRegistry` loads manifests lazily; `ToolProxy` defers the actual `importlib.import_module()` call until the tool is first executed. The practical result is fast MCP server startup even with a large tool catalogue.

### Ground Truth Verification

`GroundTruthVerifier` exists because the UniFi API has known response caching behaviour where a `PUT` to update port names may return success, but a subsequent `GET` returns the old values for several seconds. Rather than relying on the API to confirm its own writes, the verifier performs multi-read consistency checks to detect when the controller has actually applied a change. This is documented as a workaround for API behaviour that is outside the project's control.

### Topology Wrapper Module

`network_topology.py` is a one-line re-export of `enhanced_network_topology.py`. This pattern preserves backward compatibility for any callers using the original import path (`from unifi_mapper.network_topology import NetworkTopology`) while consolidating the actual implementation in the enhanced module. New code imports from `enhanced_network_topology` directly.
