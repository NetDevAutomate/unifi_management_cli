# Advanced Diagnostics & Analysis Tools

This document covers the advanced network diagnostics, validation, and analysis tools available in the UniFi Network Mapper toolkit.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tools Reference](#tools-reference)
  - [MAC Table Analyzer](#mac-table-analyzer)
  - [Link Quality Monitor](#link-quality-monitor)
  - [Storm Detector](#storm-detector)
  - [Client Path Tracer](#client-path-tracer)
  - [Capacity Planner](#capacity-planner)
  - [QoS Validator](#qos-validator)
  - [LAG Monitor](#lag-monitor)
  - [Config Backup & Diff](#config-backup--diff)
  - [Firmware Security Advisor](#firmware-security-advisor)
- [Integration Patterns](#integration-patterns)
- [Troubleshooting Workflows](#troubleshooting-workflows)

---

## Overview

The advanced diagnostics suite provides comprehensive network analysis capabilities beyond basic topology mapping. These tools help network administrators:

- **Detect problems proactively** before they impact users
- **Validate configurations** against best practices
- **Track changes** over time with configuration backups
- **Plan capacity** to avoid resource exhaustion
- **Ensure security** with firmware vulnerability analysis

```mermaid
graph TB
    subgraph "UniFi Network Mapper Toolkit"
        subgraph "Core Tools"
            M[unifi-mapper]
            L[unifi-lookup]
        end

        subgraph "Diagnostics"
            MAC[MAC Analyzer]
            LQ[Link Quality]
            SD[Storm Detector]
            CT[Client Tracer]
        end

        subgraph "Validators"
            QOS[QoS Validator]
            LAG[LAG Monitor]
            CAP[Capacity Planner]
        end

        subgraph "Operations"
            BK[Config Backup]
            FW[Firmware Advisor]
        end
    end

    API[UniFi Controller API]

    MAC --> API
    LQ --> API
    SD --> API
    CT --> API
    QOS --> API
    LAG --> API
    CAP --> API
    BK --> API
    FW --> API
    M --> API
    L --> API
```

---

## Architecture

### Module Structure

```mermaid
graph LR
    subgraph "src/unifi_mapper"
        subgraph "analyzers/"
            MA[mac_analyzer.py]
            LQ[link_quality.py]
            SD[storm_detector.py]
            CP[capacity_planner.py]
        end

        subgraph "tracers/"
            CT[client_tracer.py]
        end

        subgraph "validators/"
            QV[qos_validator.py]
            LM[lag_monitor.py]
        end

        subgraph "backup/"
            CB[config_backup.py]
        end

        subgraph "advisors/"
            FA[firmware_advisor.py]
        end

        API[api_client.py]
    end

    MA --> API
    LQ --> API
    SD --> API
    CP --> API
    CT --> API
    QV --> API
    LM --> API
    CB --> API
    FA --> API
```

### Data Flow

```mermaid
sequenceDiagram
    participant CLI as CLI Script
    participant Tool as Analysis Tool
    participant API as UniFi API Client
    participant Controller as UniFi Controller

    CLI->>Tool: Initialize with API client
    CLI->>Tool: Call analyze()
    Tool->>API: Get devices
    API->>Controller: REST API call
    Controller-->>API: Device data
    API-->>Tool: Parsed response
    Tool->>Tool: Process & analyze
    Tool-->>CLI: Result dataclass
    CLI->>Tool: generate_report()
    Tool-->>CLI: Markdown report
    CLI->>CLI: Output to file/stdout
```

---

## Tools Reference

### MAC Table Analyzer

**CLI Command:** `unifi-mac-analyzer`

**Purpose:** Analyzes MAC address tables across switches to detect security issues and network problems.

#### Key Features

- **MAC Flapping Detection** - Identifies MAC addresses moving between ports (indicates loops or misconfiguration)
- **Unauthorized Device Detection** - Compares against allowed MAC list
- **Capacity Analysis** - Flags ports with excessive MAC addresses
- **Historical Tracking** - Tracks MAC movements over time

#### Architecture

```mermaid
flowchart TD
    subgraph "MAC Table Analyzer"
        Input[Device MAC Tables]

        subgraph "Analysis Engine"
            FD[Flapping Detector]
            UD[Unauthorized Detector]
            CA[Capacity Analyzer]
        end

        subgraph "Output"
            Events[Flapping Events]
            Alerts[Security Alerts]
            Report[Analysis Report]
        end
    end

    Input --> FD
    Input --> UD
    Input --> CA

    FD --> Events
    UD --> Alerts
    CA --> Report
    Events --> Report
    Alerts --> Report
```

#### Usage

```bash
# Basic analysis
unifi-mac-analyzer --env

# With allowed MAC list
unifi-mac-analyzer --env --allowed-macs /path/to/allowed.txt

# JSON output for integration
unifi-mac-analyzer --env --json --output mac_analysis.json
```

#### Detection Logic

```mermaid
flowchart LR
    MAC[MAC Address] --> Check{Seen before?}
    Check -->|No| Record[Record location]
    Check -->|Yes| Compare{Same port?}
    Compare -->|Yes| Update[Update timestamp]
    Compare -->|No| Time{Within threshold?}
    Time -->|Yes| Flap[Flag as flapping]
    Time -->|No| Move[Record movement]
```

---

### Link Quality Monitor

**CLI Command:** `unifi-link-quality`

**Purpose:** Monitors physical layer health including errors, SFP diagnostics, and link stability.

#### Key Features

- **CRC Error Tracking** - Detects cable/connector issues
- **Duplex Mismatch Detection** - Identifies mismatched port settings
- **SFP/SFP+ Diagnostics** - Temperature, power levels, DOM data
- **Link Stability Analysis** - Tracks flapping links

#### Architecture

```mermaid
flowchart TD
    subgraph "Link Quality Monitor"
        subgraph "Data Collection"
            PT[Port Tables]
            SFP[SFP DOM Data]
            Stats[Error Statistics]
        end

        subgraph "Analysis"
            EA[Error Analyzer]
            SA[SFP Analyzer]
            LA[Link Analyzer]
        end

        subgraph "Results"
            Metrics[Quality Metrics]
            Issues[Detected Issues]
            Recs[Recommendations]
        end
    end

    PT --> EA
    PT --> LA
    SFP --> SA
    Stats --> EA

    EA --> Metrics
    SA --> Metrics
    LA --> Metrics

    Metrics --> Issues
    Issues --> Recs
```

#### Severity Levels

| Level | Condition | Example |
|-------|-----------|---------|
| Critical | Service impacting | SFP temperature >85°C |
| Warning | Degraded performance | CRC errors >1000 |
| Info | Suboptimal | Half-duplex detected |

#### Usage

```bash
# Full link quality report
unifi-link-quality --env

# Output to file
unifi-link-quality --env --output link_report.md
```

---

### Storm Detector

**CLI Command:** `unifi-storm-detector`

**Purpose:** Detects broadcast and multicast storms that can degrade network performance.

#### Key Features

- **Real-time Storm Detection** - Identifies excessive broadcast/multicast traffic
- **Per-port Analysis** - Pinpoints storm source
- **Configurable Thresholds** - Adjust for your environment
- **Storm History** - Track patterns over time

#### Storm Detection Flow

```mermaid
flowchart TD
    subgraph "Storm Detector"
        Traffic[Traffic Statistics]

        subgraph "Analysis"
            BC[Broadcast Analysis]
            MC[Multicast Analysis]
            TH[Threshold Check]
        end

        subgraph "Actions"
            Alert[Generate Alert]
            Log[Log Event]
            Report[Storm Report]
        end
    end

    Traffic --> BC
    Traffic --> MC
    BC --> TH
    MC --> TH

    TH -->|Exceeded| Alert
    TH -->|Exceeded| Log
    Alert --> Report
    Log --> Report
```

#### Default Thresholds

| Traffic Type | Warning (pps) | Critical (pps) |
|--------------|---------------|----------------|
| Broadcast | 1,000 | 5,000 |
| Multicast | 5,000 | 25,000 |

#### Usage

```bash
# Default thresholds
unifi-storm-detector --env

# Custom thresholds
unifi-storm-detector --env --broadcast-threshold 500 --multicast-threshold 2500
```

---

### Client Path Tracer

**CLI Command:** `unifi-client-trace`

**Purpose:** Traces the path of a client through the switch fabric to identify connectivity issues.

#### Key Features

- **End-to-End Path Tracing** - From client to gateway
- **VLAN Verification** - Ensures proper tagging throughout path
- **Hop Analysis** - Details each switch hop
- **Issue Detection** - Identifies path problems

#### Path Trace Visualization

```mermaid
flowchart LR
    subgraph "Client Path Trace"
        Client[Client Device]

        subgraph "Switch Fabric"
            SW1[Access Switch]
            SW2[Distribution Switch]
            SW3[Core Switch]
        end

        GW[Gateway/Router]
    end

    Client -->|"Port 5\nVLAN 100"| SW1
    SW1 -->|"Port 24\nTrunk"| SW2
    SW2 -->|"Port 48\nTrunk"| SW3
    SW3 -->|"Port 1\nTrunk"| GW
```

#### Usage

```bash
# Trace by MAC address
unifi-client-trace --env --mac aa:bb:cc:dd:ee:ff

# Trace by IP
unifi-client-trace --env --ip 192.168.1.100

# Trace by hostname
unifi-client-trace --env --hostname "johns-laptop"

# With destination
unifi-client-trace --env --mac aa:bb:cc:dd:ee:ff --destination 10.0.0.1
```

---

### Capacity Planner

**CLI Command:** `unifi-capacity-planner`

**Purpose:** Analyzes port utilization, PoE budget, and growth trends for capacity planning.

#### Key Features

- **Port Utilization Tracking** - Current and trend analysis
- **PoE Budget Monitoring** - Power consumption vs capacity
- **Growth Forecasting** - Predicts exhaustion dates
- **Upgrade Recommendations** - Based on trends

#### Capacity Analysis Flow

```mermaid
flowchart TD
    subgraph "Capacity Planner"
        subgraph "Data Collection"
            Ports[Port Status]
            PoE[PoE Data]
            History[Historical Data]
        end

        subgraph "Analysis"
            PU[Port Utilization]
            PB[PoE Budget]
            TF[Trend Forecast]
        end

        subgraph "Output"
            Current[Current Status]
            Forecast[Capacity Forecast]
            Recs[Recommendations]
        end
    end

    Ports --> PU
    PoE --> PB
    History --> TF

    PU --> Current
    PB --> Current
    TF --> Forecast

    Current --> Recs
    Forecast --> Recs
```

#### Utilization Thresholds

```mermaid
pie title Port Utilization Status
    "Available" : 30
    "In Use" : 50
    "Warning (>70%)" : 15
    "Critical (>90%)" : 5
```

#### Usage

```bash
# Default analysis
unifi-capacity-planner --env

# Custom thresholds
unifi-capacity-planner --env --warning-threshold 60 --critical-threshold 80
```

---

### QoS Validator

**CLI Command:** `unifi-qos-validator`

**Purpose:** Validates Quality of Service configuration for consistent network behavior.

#### Key Features

- **DSCP Trust Verification** - Ensures proper QoS marking preservation
- **Voice VLAN Validation** - Checks voice traffic configuration
- **Queue Consistency** - Verifies uniform QoS across devices
- **Rate Limit Analysis** - Identifies bandwidth constraints

#### QoS Validation Points

```mermaid
flowchart TD
    subgraph "QoS Validator"
        subgraph "Checks"
            DSCP[DSCP Trust Check]
            Voice[Voice VLAN Check]
            Queue[Queue Config Check]
            Rate[Rate Limit Check]
        end

        subgraph "Findings"
            Critical[Critical Issues]
            High[High Priority]
            Medium[Medium Priority]
            Low[Low Priority]
        end
    end

    DSCP --> Critical
    DSCP --> Medium
    Voice --> High
    Voice --> Medium
    Queue --> Medium
    Rate --> High
    Rate --> Low
```

#### Common Issues Detected

| Issue | Severity | Impact |
|-------|----------|--------|
| DSCP not trusted on uplink | Medium | QoS markings stripped |
| Voice VLAN without trust | High | Poor call quality |
| Rate limit on uplink | High | Bandwidth bottleneck |
| Inconsistent queue config | Medium | Unpredictable behavior |

#### Usage

```bash
# Standard validation
unifi-qos-validator --env

# Strict mode (fail on warnings)
unifi-qos-validator --env --strict
```

---

### LAG Monitor

**CLI Command:** `unifi-lag-monitor`

**Purpose:** Monitors Link Aggregation Groups for health and performance.

#### Key Features

- **LACP State Monitoring** - Verifies partner relationships
- **Load Balance Analysis** - Detects traffic imbalance
- **Member Health** - Tracks individual port status
- **Bandwidth Efficiency** - Active vs total capacity

#### LAG Health States

```mermaid
stateDiagram-v2
    [*] --> Healthy: All members active
    Healthy --> Degraded: Member(s) down
    Healthy --> Degraded: Load imbalance
    Degraded --> Critical: <50% members active
    Critical --> Inactive: No active members
    Degraded --> Healthy: Issue resolved
    Critical --> Degraded: Partial recovery
```

#### Load Balance Scoring

```mermaid
flowchart LR
    subgraph "Load Balance Score"
        Calc[Calculate per-member load]
        Avg[Compute average]
        Var[Calculate variance]
        Score[Score 0-100]
    end

    Calc --> Avg
    Avg --> Var
    Var --> Score

    Score -->|"≥90"| Excellent
    Score -->|"70-89"| Good
    Score -->|"50-69"| Warning
    Score -->|"<50"| Critical
```

#### Usage

```bash
# Full LAG health report
unifi-lag-monitor --env

# JSON output
unifi-lag-monitor --env --json
```

---

### Config Backup & Diff

**CLI Command:** `unifi-config-backup`

**Purpose:** Creates configuration snapshots and tracks changes over time.

#### Key Features

- **Point-in-Time Snapshots** - Full configuration backup
- **Change Detection** - Detailed diff between configs
- **Change Classification** - Severity-based categorization
- **Backup Management** - List, compare, delete backups

#### Backup Workflow

```mermaid
sequenceDiagram
    participant Admin
    participant CLI as Config Backup CLI
    participant Tool as ConfigBackup
    participant API as UniFi API
    participant Disk as Local Storage

    Admin->>CLI: backup -d "Before maintenance"
    CLI->>Tool: create_backup()
    Tool->>API: Get full config
    API-->>Tool: Devices, Networks, Profiles
    Tool->>Tool: Calculate checksum
    Tool->>Disk: Save JSON + metadata
    Tool-->>CLI: BackupMetadata
    CLI-->>Admin: Backup ID + summary

    Note over Admin,Disk: Later...

    Admin->>CLI: diff backup_123
    CLI->>Tool: compare(backup_123, current)
    Tool->>Disk: Load baseline
    Tool->>API: Get current config
    Tool->>Tool: Generate diff
    Tool-->>CLI: ConfigDiff
    CLI-->>Admin: Change report
```

#### Change Severity Levels

| Severity | Example Changes |
|----------|-----------------|
| Critical | Device removed, security setting changed |
| Warning | STP priority changed, port disabled |
| Info | Firmware updated, description changed |

#### Usage

```bash
# Create backup
unifi-config-backup --env backup -d "Before maintenance window"

# List backups
unifi-config-backup --env list

# Compare backup to current
unifi-config-backup --env diff backup_20241228_120000

# Compare two backups
unifi-config-backup --env diff backup_20241228_120000 -c backup_20241228_140000

# Delete old backup
unifi-config-backup --env delete backup_20241228_120000
```

---

### Firmware Security Advisor

**CLI Command:** `unifi-firmware-advisor`

**Purpose:** Analyzes firmware versions and identifies security vulnerabilities.

#### Key Features

- **Version Tracking** - Current vs latest firmware
- **CVE Assessment** - Check against known vulnerabilities
- **Upgrade Priority** - Prioritized update recommendations
- **Family Consistency** - Ensures uniform versions

#### Security Assessment Flow

```mermaid
flowchart TD
    subgraph "Firmware Advisor"
        subgraph "Data Collection"
            Dev[Device Inventory]
            Ver[Current Versions]
            KB[Knowledge Base]
        end

        subgraph "Analysis"
            VC[Version Compare]
            CVE[CVE Check]
            FC[Family Consistency]
        end

        subgraph "Output"
            Score[Security Score]
            Priority[Update Priority]
            Recs[Recommendations]
        end
    end

    Dev --> VC
    Ver --> VC
    KB --> VC
    KB --> CVE
    Ver --> CVE
    Dev --> FC
    Ver --> FC

    VC --> Score
    CVE --> Score
    CVE --> Priority
    FC --> Priority

    Score --> Recs
    Priority --> Recs
```

#### Security Score Calculation

```mermaid
pie title Security Score Impact
    "Critical vulns (-20 each)" : 20
    "Security updates needed (-10 each)" : 15
    "Updates available (-5 each)" : 10
    "EOL devices (-15 each)" : 15
    "Inconsistent families (-5 each)" : 5
    "Base score" : 35
```

#### Firmware Status States

| Status | Description | Priority |
|--------|-------------|----------|
| Current | Running latest stable | None |
| Update Available | Newer version exists | Low |
| Security Update | Security patches needed | High |
| Critical | Known critical CVEs | Critical |
| EOL | End of life | High |

#### Usage

```bash
# Full security report
unifi-firmware-advisor --env

# With minimum score requirement
unifi-firmware-advisor --env --min-score 70

# JSON output for CI/CD
unifi-firmware-advisor --env --json --output firmware_status.json
```

---

## Integration Patterns

### CI/CD Pipeline Integration

```mermaid
flowchart LR
    subgraph "CI/CD Pipeline"
        Trigger[Scheduled Trigger]

        subgraph "Health Checks"
            FW[Firmware Check]
            QOS[QoS Validation]
            LAG[LAG Health]
        end

        subgraph "Actions"
            Pass[Pass]
            Fail[Fail + Alert]
        end
    end

    Trigger --> FW
    Trigger --> QOS
    Trigger --> LAG

    FW -->|"Score ≥ 70"| Pass
    FW -->|"Score < 70"| Fail
    QOS -->|"Passed"| Pass
    QOS -->|"Failed"| Fail
    LAG -->|"No critical"| Pass
    LAG -->|"Critical"| Fail
```

### Example CI Script

```bash
#!/bin/bash
set -e

# Run all validators
unifi-firmware-advisor --env --min-score 70 --json > firmware.json
unifi-qos-validator --env --strict --json > qos.json
unifi-lag-monitor --env --json > lag.json

# Check for issues
if grep -q '"critical_count": [1-9]' lag.json; then
    echo "CRITICAL: LAG issues detected"
    exit 1
fi

echo "All checks passed"
```

---

## Troubleshooting Workflows

### Network Performance Issue

```mermaid
flowchart TD
    Start[Performance Complaint]

    Start --> Storm{Storm detected?}
    Storm -->|Yes| StormAction[Identify source port]
    Storm -->|No| Link{Link quality OK?}

    Link -->|No| LinkAction[Check cables/SFPs]
    Link -->|Yes| QoS{QoS correct?}

    QoS -->|No| QoSAction[Fix QoS config]
    QoS -->|Yes| LAG{LAG balanced?}

    LAG -->|No| LAGAction[Check LAG members]
    LAG -->|Yes| Capacity{Capacity OK?}

    Capacity -->|No| CapAction[Plan upgrade]
    Capacity -->|Yes| Other[Investigate other causes]
```

### Client Connectivity Issue

```mermaid
flowchart TD
    Start[Client can't connect]

    Start --> Trace[Run client trace]
    Trace --> Found{Client found?}

    Found -->|No| MAC[Check MAC analyzer]
    Found -->|Yes| Path{Path complete?}

    MAC --> Flap{MAC flapping?}
    Flap -->|Yes| Loop[Investigate loop]
    Flap -->|No| Auth[Check authentication]

    Path -->|No| Hop[Check failed hop]
    Path -->|Yes| VLAN{VLAN correct?}

    VLAN -->|No| VLANFix[Fix VLAN config]
    VLAN -->|Yes| Other[Check firewall/routing]
```

---

## Quick Reference

| Tool | CLI Command | Primary Use |
|------|-------------|-------------|
| MAC Analyzer | `unifi-mac-analyzer` | Loop/security detection |
| Link Quality | `unifi-link-quality` | Physical layer health |
| Storm Detector | `unifi-storm-detector` | Broadcast storm detection |
| Client Tracer | `unifi-client-trace` | Path troubleshooting |
| Capacity Planner | `unifi-capacity-planner` | Growth planning |
| QoS Validator | `unifi-qos-validator` | QoS configuration audit |
| LAG Monitor | `unifi-lag-monitor` | Link aggregation health |
| Config Backup | `unifi-config-backup` | Change management |
| Firmware Advisor | `unifi-firmware-advisor` | Security posture |

All tools support:
- `--env` - Load from .env file
- `--config <file>` - Custom config file
- `--json` - JSON output format
- `--output <file>` - Write to file
- `--debug` - Verbose logging
