# Feature Specification: UniFi Network MCP Server

**Feature Branch**: `001-unifi-mcp-server`
**Created**: 2024-12-28
**Status**: Draft
**Input**: User description: "MCP server for UniFi network troubleshooting accessible to non-experts"

## Overview

An MCP server that transforms UniFi network troubleshooting from expert-only to accessible-for-anyone. Users describe problems in natural language; the AI agent uses prescriptive tools to diagnose issues, trace network paths, analyze firewall rules, and provide guided solutions with visual diagrams.

**Target Users**:
- **Primary**: Home/small business network administrators unfamiliar with networking
- **Secondary**: Network professionals wanting faster troubleshooting

**Target Controller**: UDM Pro Max 4.4.6 (local hardware)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - VLAN Connectivity Verification (Priority: P1) 🎯 MVP

As a network administrator unfamiliar with VLANs, I want to check if VLAN X can communicate with VLAN Y, so that I can verify my firewall rules are correct.

**Why this priority**: VLAN-to-VLAN connectivity issues are the most common troubleshooting scenario, especially critical for CCTV VLAN isolation problems.

**Independent Test**: Can be fully tested by specifying two VLANs and receiving a clear ALLOW/DENY verdict with path visualization.

**Acceptance Scenarios**:

1. **Given** two VLANs exist on the network, **When** user requests connectivity check between them by name or ID, **Then** system shows routing path, firewall rules affecting the path, and clear ALLOW/DENY verdict with explanation
2. **Given** VLANs have firewall rules between them, **When** user checks connectivity, **Then** system displays a Mermaid diagram showing the path and rule application points
3. **Given** VLAN names contain spaces or special characters, **When** user specifies VLAN by name, **Then** system correctly identifies and analyzes the VLAN

---

### User Story 2 - Device-to-Device Connectivity Trace (Priority: P1) 🎯 MVP

As a user troubleshooting why device A can't reach device B, I want to trace the network path and identify blockers, so that I can fix the connectivity issue.

**Why this priority**: Direct device connectivity issues are the primary troubleshooting use case; this is the core value proposition of the MCP server.

**Independent Test**: Can be fully tested by specifying two endpoints and receiving complete L2/L3 path with firewall analysis.

**Acceptance Scenarios**:

1. **Given** two devices on the network, **When** user requests traceroute by IP, MAC, hostname, or switch port, **Then** system shows complete L2 path (switches, ports, VLANs) and L3 path (routing, inter-VLAN)
2. **Given** devices are on different VLANs, **When** traceroute crosses VLAN boundary, **Then** system explicitly shows VLAN crossing points and applies firewall_check at each boundary
3. **Given** user specifies "internet" as destination, **When** traceroute runs, **Then** system traces path to gateway and shows egress path
4. **Given** multiple paths exist between endpoints, **When** traceroute runs, **Then** system shows all paths with ETR-style visualization
5. **Given** a device is offline, **When** user traces to it, **Then** system advises "Destination device is not currently connected. Last seen: [timestamp]"

---

### User Story 3 - Port Duplex Validation (Priority: P2)

As a network administrator, I want to verify all ports are running Full Duplex, so that I can identify misconfigured ports causing performance issues.

**Why this priority**: Half duplex mismatches cause subtle performance problems; validation ensures network health.

**Independent Test**: Can be fully tested by running duplex scan and receiving list of any Half Duplex ports with fix recommendations.

**Acceptance Scenarios**:

1. **Given** switches with active ports, **When** user requests duplex validation, **Then** system scans all active ports across all switches and flags any Half Duplex connections
2. **Given** a Half Duplex port is found, **When** displaying results, **Then** system shows switch name, port number, connected device, and recommends fix (auto-negotiate vs hard set)

---

### User Story 4 - Port Naming Audit (Priority: P2)

As a network administrator wanting organized infrastructure, I want to see all ports with naming status (trunk vs access, what's connected), so that I can identify unnamed or incorrectly named ports.

**Why this priority**: Proper port naming is essential for maintainability and rapid troubleshooting.

**Independent Test**: Can be fully tested by running audit and receiving complete port inventory with naming issues flagged.

**Acceptance Scenarios**:

1. **Given** switches with configured ports, **When** user requests port naming audit, **Then** system lists all ports with current names, trunk/access status, and connected device
2. **Given** ports without names exist, **When** audit runs, **Then** system flags unnamed ports with suggested names based on connected device
3. **Given** port name doesn't match connected device, **When** audit runs, **Then** system flags the mismatch

---

### User Story 5 - Configuration Change Tracking (Priority: P2)

As a network administrator troubleshooting a new issue, I want to see what changed in the last N days, so that I can correlate changes with the current problem.

**Why this priority**: Configuration changes are often the root cause of new issues; tracking enables rapid correlation.

**Independent Test**: Can be fully tested by specifying time range and receiving structured diff of all changes.

**Acceptance Scenarios**:

1. **Given** configuration backups exist, **When** user requests changes for last N days/hours, **Then** system shows structured diff categorized by type (VLAN, firewall, port, profile)
2. **Given** multiple changes occurred, **When** displaying diff, **Then** system highlights potentially impactful changes with timeline view
3. **Given** no backups available for requested period, **When** user requests diff, **Then** system advises on backup availability and suggests alternative time range

---

### User Story 6 - Best Practices Validation (Priority: P3)

As a network administrator wanting a healthy network, I want to validate my configuration against best practices, so that I can identify and fix issues proactively.

**Why this priority**: Proactive validation prevents issues before they occur; lower priority as it's preventive rather than reactive.

**Independent Test**: Can be fully tested by running validation and receiving pass/fail results for each best practice check.

**Acceptance Scenarios**:

1. **Given** network configuration exists, **When** user requests best practice validation, **Then** system checks profile usage, naming conventions, firewall rules, and VLAN configuration
2. **Given** issues are found, **When** displaying results, **Then** system shows clear pass/fail for each check with specific recommendations
3. **Given** profiles are inconsistently applied, **When** validation runs, **Then** system identifies missing profiles and suggests standardization

---

### User Story 7 - Firewall Visualization (Priority: P2)

As a user confused by firewall rules, I want to see a clear view of inter-VLAN connectivity rules, so that I can understand what traffic is allowed/denied.

**Why this priority**: Firewall rules are complex; visualization makes them accessible to non-experts.

**Independent Test**: Can be fully tested by requesting firewall view and receiving matrix/diagram of VLAN connectivity.

**Acceptance Scenarios**:

1. **Given** firewall rules exist, **When** user requests visualization, **Then** system shows matrix view with source VLAN vs destination VLAN showing ALLOW/DENY
2. **Given** user wants rule details, **When** drilling down on a cell, **Then** system shows matching rules, hit counts (if available), and rule order/priority
3. **Given** user prefers diagrams, **When** requesting Mermaid format, **Then** system generates visual diagram of inter-VLAN connectivity

---

### User Story 8 - System Load Monitoring (Priority: P3)

As a user experiencing slow network performance, I want to see system load across all UniFi devices, so that I can identify overloaded devices.

**Why this priority**: System load is a diagnostic tool for performance issues; lower priority as it's situational.

**Independent Test**: Can be fully tested by requesting system load and receiving CPU/memory/uptime for all devices.

**Acceptance Scenarios**:

1. **Given** UniFi devices are online, **When** user requests system load, **Then** system shows CPU, memory, uptime for each device
2. **Given** a device has high load, **When** displaying results, **Then** system flags it with warning and suggests investigation
3. **Given** user wants real-time view, **When** using TUI option, **Then** system provides live-updating dashboard

---

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Device offline | "Destination device is not currently connected. Last seen: [timestamp]" |
| Unknown MAC/IP | "Address not found in network. Is this an Internet address or external network (VPN)?" with Y/N prompt |
| Multi-path routing | Show all paths with ETR-style visualization |
| Inter-VLAN routing | Explicitly show VLAN boundary crossings with firewall check at each boundary |
| Controller unreachable | Clear error with connection troubleshooting steps and credential verification guide |
| Slow response (>30s) | Show system_load tool results and suggest checking device health |
| Non-RFC1918 IP | Ask if destination is Internet or VPN endpoint |

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide traceroute between any two endpoints including IP, MAC, hostname, switch port, gateway, and "internet"
- **FR-002**: System MUST display L2 path (switches, ports, VLANs) and L3 path (routing, inter-VLAN) for all traces
- **FR-003**: System MUST identify and display firewall rules affecting network paths with ALLOW/DENY verdicts
- **FR-004**: System MUST generate Mermaid diagrams for network paths and firewall visualizations
- **FR-005**: System MUST support verbosity toggle (Guided mode for non-experts, Expert mode for professionals)
- **FR-006**: System MUST validate port duplex settings and flag Half Duplex connections
- **FR-007**: System MUST audit port naming and identify unnamed or misnamed ports
- **FR-008**: System MUST compare configuration backups to show changes over specified time periods
- **FR-009**: System MUST validate configuration against best practices with pass/fail verdicts
- **FR-010**: System MUST display system load (CPU, memory, uptime) for all UniFi devices
- **FR-011**: System MUST connect to UniFi controller using credential chain (Environment → Keychain → 1Password CLI)
- **FR-012**: System MUST provide prescriptive guidance in tool outputs (suggested next steps, related tools)

### Key Entities

- **Device**: Network device with MAC, name, model, IP, type (switch/ap/gateway/client), uptime, connection
- **Port**: Switch port with index, name, enabled status, speed, duplex, PoE mode, VLAN, trunk status, connected device
- **NetworkPath**: Traced path with source, destination, hops, total latency, firewall verdict, blocking rules
- **FirewallRule**: Rule with ID, name, action (allow/deny), source, destination, port, protocol, hit count, order
- **VLAN**: Virtual LAN with ID, name, subnet, DHCP settings, associated ports
- **PathHop**: Single hop with device, interface, VLAN, latency, firewall status

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Non-expert users can complete VLAN connectivity verification in under 2 minutes using natural language
- **SC-002**: Traceroute between any two endpoints completes in under 10 seconds with full path visualization
- **SC-003**: Users receive actionable ALLOW/DENY verdicts with explanations for 100% of firewall-related queries
- **SC-004**: System identifies 100% of Half Duplex port misconfigurations across all switches
- **SC-005**: Configuration change tracking covers 100% of changes within specified time range (when backups available)
- **SC-006**: Best practice validation provides pass/fail verdict for each check with specific remediation steps
- **SC-007**: Non-expert users report understanding network issues without prior networking knowledge (validated by workflow completion)
- **SC-008**: All tool outputs include suggested next steps, achieving self-guided troubleshooting

## Assumptions

1. UniFi controller API (UDM Pro Max 4.4.6) provides all necessary data via REST endpoints
2. Configuration backups are accessible via API for change tracking feature
3. Controller supports device-to-device ping/traceroute commands
4. Session tokens can be cached and reused across tool invocations
5. Read-only operations do not require additional confirmation
6. Mermaid diagram syntax is compatible with common markdown renderers
