# UniFi Network Topology Visualization Toolkit

🚀 **UV Project**: Modern Python tooling with fast dependency management and global installation support.

A comprehensive toolkit for visualizing and managing UniFi network topologies, including automatic port mapping, network diagram generation, and device management.

## Purpose

This toolkit helps UniFi network administrators visualize their network topology, automatically map and name ports based on connected devices, and generate comprehensive reports. It leverages LLDP/CDP information to build accurate network maps and supports multiple visualization formats including interactive HTML diagrams.

## Installation

### Method 1: Global UV Tool Installation (Recommended)

Install once, run from anywhere with different config files:

```bash
# Install globally with UV
uv tool install .

# Or from git
uv tool install git+https://github.com/NetDevAutomate/unifi-network-mapper

# Run from anywhere
unifi-mapper --help
unifi-mapper --config ~/.unifi/prod.env --format png
```

### Method 2: Local Development

```bash
# Create UV virtual environment
uv venv

# Install project
uv pip install -e .

# Install dev dependencies
uv pip install --group dev

# Run with uv
uv run unifi-mapper --config .env
```

### Method 3: Traditional (Legacy)

```bash
python unifi_network_mapper.py --env
```

## Usage

### Global Tool (After uv tool install)

```bash
# Basic usage with config file
unifi-mapper --config ~/.unifi/production.env

# Generate PNG diagram
unifi-mapper --config ~/.unifi/prod.env --format png

# Multiple configs for different networks
unifi-mapper --config ~/.unifi/office.env --output ~/reports/office.md
unifi-mapper --config ~/.unifi/homelab.env --output ~/reports/homelab.md

# Run from any directory - outputs relative to current location
cd ~/Documents/network-reports
unifi-mapper --config ~/.unifi/prod.env  # Creates ./reports and ./diagrams here
```

## Key Features

- **Complete Device Discovery**: Automatically identifies all UniFi devices (routers, switches, APs)
- **Intelligent Port Mapping**: Names ports based on connected devices
- **Multiple Visualization Formats**: PNG, SVG, DOT, Mermaid, and interactive HTML
- **Interactive Diagrams**: Drag-and-drop interface with zoom, pan, and custom layout saving
- **Flexible Authentication**: Supports both API token and username/password
- **Dry Run Mode**: Test port naming changes without applying them
- **IP Conflict Detection**: Identifies duplicate IP addresses in your network

## Code Structure

### Main Components

- **unifi_network_mapper.py**: Main entry point and command-line interface
- **src/unifi_mapper/**: Core modules for API communication, topology generation, and port mapping
- **src/scripts/**: Command-line utilities for specific tasks

### Core Modules

- **api_client.py**: Handles communication with the UniFi Controller API
- **models.py**: Data models for devices and ports
- **enhanced_network_topology.py**: Network topology visualization with advanced features
- **run_methods.py**: Helper methods for running the port mapper
- **port_mapper.py**: Port mapping and naming logic
- **report_generator.py**: Generates detailed reports
- **device_definitions.py**: Device model definitions and port configurations

## Enhanced Architecture Diagram

### Core System Architecture

```mermaid
classDiagram
    class UnifiNetworkMapper {
        +main()
        +load_env_file()
        +configure_logging()
        +handle_self_signed_certs()
    }

    class UnifiApiClient {
        -base_url: str
        -site: str
        -session: requests.Session
        -is_unifi_os: bool
        -max_retries: int
        -retry_delay: float
        -auth_method: str
        +login()
        +logout()
        +_retry_request()
        +get_devices()
        +get_device_ports()
        +get_lldp_info()
        +get_clients()
        +update_port_name()
        +update_device_port_table()
        +verify_port_update()
        +debug_device_config()
        +clear_credentials()
    }

    class DeviceInfo {
        +id: str
        +name: str
        +model: str
        +mac: str
        +ip: str
        +device_type: str
        +ports: List[PortInfo]
        +lldp_info: Dict
        +get_device_type()
        +get_color()
    }

    class PortInfo {
        +idx: int
        +name: str
        +media: str
        +is_uplink: bool
        +up: bool
        +enabled: bool
        +speed: int
        +full_duplex: bool
        +has_lldp_info: bool
        +lldp_info: Dict
        +connected_device_name: str
        +connected_port_name: str
        +poe: bool
        +get_display_name()
        +get_lldp_display_name()
        +update_lldp_info()
    }

    class NetworkAnalyzer {
        -api_client: UnifiApiClient
        -configuration_history: List[NetworkConfiguration]
        -baseline_config: NetworkConfiguration
        +perform_comprehensive_analysis()
        +_analyze_device_health()
        +_analyze_port_health()
        +_detect_topology_changes()
        +_identify_performance_bottlenecks()
        +_analyze_security_posture()
        +_generate_recommendations()
    }

    class NetworkHealthMetrics {
        <<Abstract>>
    }

    class DeviceHealthMetrics {
        +device_id: str
        +cpu_usage_percent: float
        +memory_usage_percent: float
        +temperature_celsius: float
        +uptime_seconds: int
        +port_metrics: Dict[int, PortHealthMetrics]
        +active_alerts: List
        +calculate_overall_health_score()
        +get_health_status()
        +get_critical_ports()
        +get_warning_ports()
    }

    class PortHealthMetrics {
        +port_idx: int
        +device_id: str
        +rx_bytes: int
        +tx_bytes: int
        +utilization_percent: float
        +link_flap_count: int
        +calculate_health_score()
        +get_health_status()
        +add_utilization_sample()
    }

    class NetworkConfiguration {
        +timestamp: datetime
        +devices: Dict[str, Dict]
        +topology_connections: List[Tuple]
        +add_device_config()
        +add_connection()
        +compare_with()
    }

    class NetworkAnalysisResult {
        +timestamp: datetime
        +device_health: Dict[str, DeviceHealthMetrics]
        +topology_changes: List[NetworkTopologyChange]
        +performance_bottlenecks: List[Dict]
        +security_issues: List[Dict]
        +recommendations: List[Dict]
        +overall_health_score: float
        +calculate_summary_stats()
        +get_critical_issues()
    }

    class NetworkTopology {
        -devices: Dict[str, DeviceInfo]
        -connections: List[Dict]
        -analyzer: NetworkAnalyzer
        +add_device()
        +add_connection()
        +is_unifi_device()
        +is_switch()
        +is_router()
        +is_ap()
        +infer_missing_connections()
        +generate_html_diagram()
        +generate_png_diagram()
        +generate_svg_diagram()
        +generate_dot_diagram()
        +generate_mermaid_diagram()
        +analyze_network_health()
    }

    class UnifiPortMapper {
        -api_client: UnifiApiClient
        -analyzer: NetworkAnalyzer
        -site: str
        -dry_run: bool
        +map_ports()
        +generate_report()
        +generate_diagram()
        +perform_health_check()
    }

    class ReportGenerator {
        +generate_port_mapping_report()
        +generate_device_table()
        +generate_port_table()
        +generate_health_report()
        +generate_security_report()
    }

    class RunMethods {
        +run_port_mapper()
        +infer_device_connections()
        +run_network_analysis()
        +generate_comprehensive_report()
    }

    %% Exception Classes
    class UniFiApiError {
        <<Exception>>
    }

    class UniFiAuthenticationError {
        <<Exception>>
    }

    class UniFiConnectionError {
        <<Exception>>
    }

    class UniFiTimeoutError {
        <<Exception>>
    }

    class UniFiPermissionError {
        <<Exception>>
    }

    class UniFiValidationError {
        <<Exception>>
    }

    %% Relationships
    UnifiNetworkMapper --> UnifiPortMapper: creates
    UnifiNetworkMapper --> RunMethods: calls
    UnifiPortMapper --> UnifiApiClient: uses
    UnifiPortMapper --> NetworkAnalyzer: uses
    RunMethods --> NetworkTopology: creates
    RunMethods --> ReportGenerator: uses
    RunMethods --> NetworkAnalyzer: uses
    NetworkTopology --> DeviceInfo: contains
    NetworkTopology --> NetworkAnalyzer: uses
    DeviceInfo --> PortInfo: contains
    NetworkAnalyzer --> NetworkConfiguration: manages
    NetworkAnalyzer --> NetworkAnalysisResult: produces
    NetworkAnalysisResult --> DeviceHealthMetrics: contains
    NetworkAnalysisResult --> PortHealthMetrics: contains
    DeviceHealthMetrics --> PortHealthMetrics: contains
    NetworkHealthMetrics <|-- DeviceHealthMetrics
    NetworkHealthMetrics <|-- PortHealthMetrics

    %% Exception Hierarchy
    UniFiApiError <|-- UniFiAuthenticationError
    UniFiApiError <|-- UniFiConnectionError
    UniFiApiError <|-- UniFiTimeoutError
    UniFiApiError <|-- UniFiPermissionError
    UniFiApiError <|-- UniFiValidationError

    UnifiApiClient ..> UniFiApiError: throws
```

### Security Architecture

```mermaid
flowchart TD
    subgraph "Authentication Layer"
        A1[API Token Auth]
        A2[Username/Password Auth]
        A3[Session Management]
    end

    subgraph "Security Controls"
        S1[Input Validation]
        S2[Credential Sanitization]
        S3[SSL/TLS Verification]
        S4[Secure Memory Management]
    end

    subgraph "Error Handling"
        E1[Retry Mechanism]
        E2[Exponential Backoff]
        E3[Custom Exceptions]
        E4[Sanitized Logging]
    end

    subgraph "Network Communication"
        N1[Self-signed Cert Support]
        N2[Connection Timeout]
        N3[Request Sanitization]
        N4[Response Validation]
    end

    A1 --> S1
    A2 --> S1
    A3 --> S4
    S1 --> E1
    S2 --> E4
    S3 --> N1
    E1 --> E2
    E2 --> E3
    N1 --> N2
    N2 --> N3
    N3 --> N4

    style S1 fill:#ffebee
    style S2 fill:#ffebee
    style S3 fill:#ffebee
    style S4 fill:#ffebee
```

## Enhanced Process Flow with Network Analysis

```mermaid
flowchart TD
    A[Start] --> B[Parse Arguments]
    B --> C[Initialize API Client with Security Controls]
    C --> D[Authenticate with Retry Logic]
    D --> E[Fetch Devices with Validation]
    E --> F[Fetch Ports and LLDP/CDP Info]
    F --> G[Fetch Clients]
    G --> H[Build Network Topology]
    H --> I[Perform Network Health Analysis]
    I --> J[Detect Topology Changes]
    J --> K[Identify Performance Bottlenecks]
    K --> L[Analyze Security Posture]
    L --> M[Generate Recommendations]
    M --> N[Infer Missing Connections]
    N --> O[Generate Interactive Diagram]
    O --> P[Generate Comprehensive Report]
    P --> Q[Save Analysis Results]
    Q --> R[End]

    subgraph "Security Layer"
        C1[Input Validation]
        C2[Credential Sanitization]
        C3[SSL Certificate Handling]
        C4[Secure Memory Management]
    end

    subgraph "Authentication & Connection"
        C --> C1
        D --> C2
        C3 --> D
        C4 --> D
    end

    subgraph "Data Collection with Error Handling"
        E
        F
        G
    end

    subgraph "Advanced Network Analysis"
        I
        J
        K
        L
        M
    end

    subgraph "Enhanced Topology Generation"
        H
        N
    end

    subgraph "Rich Output Generation"
        O
        P
        Q
    end

    style I fill:#e1f5fe
    style J fill:#e8f5e8
    style K fill:#fff3e0
    style L fill:#ffebee
    style M fill:#f3e5f5
```

### Network Health Monitoring Workflow

```mermaid
flowchart LR
    subgraph "Device Health Analysis"
        DH1[CPU Usage Monitoring]
        DH2[Memory Usage Tracking]
        DH3[Temperature Monitoring]
        DH4[Uptime Analysis]
        DH5[Alert Collection]
    end

    subgraph "Port Health Analysis"
        PH1[Traffic Statistics]
        PH2[Utilization Calculation]
        PH3[Error Rate Analysis]
        PH4[Link Stability Check]
        PH5[Performance Metrics]
    end

    subgraph "Topology Change Detection"
        TC1[Configuration Snapshots]
        TC2[Historical Comparison]
        TC3[Device Addition/Removal]
        TC4[Connection Changes]
        TC5[Drift Analysis]
    end

    subgraph "Security Analysis"
        SA1[Firmware Version Check]
        SA2[Uptime Security Review]
        SA3[Device Availability]
        SA4[Configuration Security]
        SA5[Vulnerability Assessment]
    end

    subgraph "Performance Bottleneck Detection"
        PB1[High CPU/Memory Usage]
        PB2[Port Utilization Issues]
        PB3[Temperature Warnings]
        PB4[Error Rate Thresholds]
        PB5[Capacity Planning]
    end

    subgraph "Health Scoring & Recommendations"
        HS1[Device Health Scores]
        HS2[Port Health Scores]
        HS3[Overall Network Score]
        HS4[Prioritized Recommendations]
        HS5[Action Items]
    end

    DH1 --> HS1
    DH2 --> HS1
    DH3 --> PB3
    DH4 --> SA2
    DH5 --> HS1

    PH1 --> PH2
    PH2 --> PB2
    PH3 --> PB4
    PH4 --> HS2
    PH5 --> HS2

    TC1 --> TC2
    TC2 --> TC3
    TC3 --> TC4
    TC4 --> TC5

    SA1 --> SA5
    SA2 --> SA5
    SA3 --> SA5
    SA4 --> SA5

    PB1 --> HS4
    PB2 --> HS4
    PB3 --> HS4
    PB4 --> HS4
    PB5 --> HS5

    HS1 --> HS3
    HS2 --> HS3
    HS3 --> HS4
    HS4 --> HS5

    style HS3 fill:#c8e6c9
    style HS4 fill:#ffecb3
    style HS5 fill:#ffcdd2
```

## Usage Examples

### Basic Usage

```bash
# Using environment variables from .env file
python unifi_network_mapper.py --env

# Using command line arguments
python unifi_network_mapper.py --url https://192.168.1.1 --token your_api_token
```

### Advanced Options

```bash
# Generate interactive HTML diagram
python unifi_network_mapper.py --env --format html --diagram diagrams/network.html

# Include all connected devices (not just UniFi devices)
python unifi_network_mapper.py --env --format html --diagram diagrams/all_devices.html --connected-devices

# Dry run mode (doesn't apply changes)
python unifi_network_mapper.py --env --dry-run

# Enable comprehensive network health analysis
python unifi_network_mapper.py --env --analyze-health --save-analysis

# Generate security-focused report
python unifi_network_mapper.py --env --security-analysis --output-format json
```

### Network Health Analysis

The toolkit now includes comprehensive network health monitoring and analysis capabilities:

```bash
# Perform network health check with detailed metrics
python unifi_network_mapper.py --env --health-check

# Generate performance bottleneck report
python unifi_network_mapper.py --env --performance-analysis

# Track configuration changes over time
python unifi_network_mapper.py --env --config-drift-analysis

# Security posture assessment
python unifi_network_mapper.py --env --security-audit
```

The network analyzer provides:

- **Device Health Monitoring**: CPU, memory, and temperature tracking
- **Port Performance Analysis**: Utilization, error rates, and link stability
- **Topology Change Detection**: Automatic detection of network changes
- **Security Assessment**: Firmware version checks and vulnerability analysis
- **Performance Bottleneck Identification**: Resource utilization and capacity planning
- **Configuration Drift Analysis**: Historical comparison and stability scoring

### Client Lookup Tool

The toolkit includes a client lookup tool that allows you to search for clients by name, MAC address, or IP address:

```bash
# Using the wrapper script (recommended)
./tools/unifi_lookup "macbook" --env

# Search for clients using environment variables from .env file
python src/scripts/unifi_lookup.py "macbook" --env

# Search using command line arguments
python src/scripts/unifi_lookup.py "192.168.1" --url https://unifi.local:8443 --token your_api_token

# Enable debug logging
python src/scripts/unifi_lookup.py "printer" --env --debug

# Enable SSL verification (disabled by default)
python src/scripts/unifi_lookup.py "printer" --env --verify-ssl
```

### IP Conflict Detector

The toolkit includes an IP conflict detector that identifies duplicate IP addresses in your network:

```bash
# Using the wrapper script (recommended)
./tools/unifi_ip_conflict --env

# Using environment variables from .env file
python src/scripts/unifi_ip_conflict_detector.py --env

# Using command line arguments
python src/scripts/unifi_ip_conflict_detector.py --url https://unifi.local:8443 --token your_api_token

# Include historical clients (may include stale data)
python src/scripts/unifi_ip_conflict_detector.py --env --include-historical

# Enable debug logging
python src/scripts/unifi_ip_conflict_detector.py --env --debug
```

The IP conflict detector displays detailed information about conflicting devices including:
- IP Address
- Device Names
- MAC Addresses (prominently displayed)
- Connection Points (which switch/port or AP)
- Interface Details (port number for wired connections)
- Connection Status (wired, wireless, guest, offline)

The tool provides three different views:
1. A hierarchical tree view showing conflicts grouped by IP address
2. A summary table with IP addresses, device counts, MAC addresses, and names
3. A detailed table with connection information for easy troubleshooting

### Configuration Validator & Auto-Fix

The toolkit includes powerful configuration validation and auto-fix capabilities that detect and remediate common UniFi misconfigurations:

```bash
# Validate configuration against best practices
uv run unifi-config-validator -c ~/.config/unifi/prod.env

# Check only trunk/VLAN routing issues
uv run unifi-config-validator -c ~/.config/unifi/prod.env --check trunk

# Show only critical and high severity issues
uv run unifi-config-validator -c ~/.config/unifi/prod.env -s critical,high

# Generate markdown report
uv run unifi-config-validator -c ~/.config/unifi/prod.env -o report.md
```

**Auto-Fix VLAN Blocking Issues:**

```bash
# ALWAYS dry-run first to preview changes
uv run unifi-config-autofix -c ~/.config/unifi/prod.env --dry-run

# Fix all VLAN blocking issues
uv run unifi-config-autofix -c ~/.config/unifi/prod.env --fix-all

# Fix specific device only
uv run unifi-config-autofix -c ~/.config/unifi/prod.env --fix-all -d "Dream Machine Pro"

# Generate rollback script for safety
uv run unifi-config-autofix -c ~/.config/unifi/prod.env --fix-all --rollback-script rollback.sh
```

**Validators Included:**

| Validator | Description |
|-----------|-------------|
| **TrunkPortValidator** | Detects `forward: native` and `tagged_vlan_mgmt: block_all` that silently drop VLAN traffic |
| **STPValidator** | Checks for non-deterministic STP root bridge selection |
| **SecurityValidator** | Guest isolation, DHCP guard, IoT segregation |
| **OperationalValidator** | Device naming, firmware consistency, PoE budget |
| **DHCPValidator** | Gateway enabled, DNS settings, lease times |

See [Configuration Validation Documentation](docs/config-validation.md) for detailed usage.

## Configuration

Create a `.env` file with your UniFi Controller credentials:

```
UNIFI_URL=https://192.168.1.1
UNIFI_SITE=default
UNIFI_CONSOLE_API_TOKEN=your_api_token
# Or use username/password authentication
UNIFI_USERNAME=your_username
UNIFI_PASSWORD=your_password
UNIFI_VERIFY_SSL=false
UNIFI_TIMEOUT=10
```

## Security Features

The toolkit implements comprehensive security controls for safe operation with UniFi Controllers:

### Authentication Security
- **Multi-method Authentication**: Supports both API tokens and username/password with automatic detection
- **Session Management**: Secure session handling with automatic cleanup
- **Credential Sanitization**: All sensitive data is sanitized in logs and memory
- **Retry Logic**: Exponential backoff with authentication failure detection

### Network Security
- **Self-signed Certificate Support**: Proper handling of UniFi Controllers with self-signed certificates
- **SSL/TLS Validation**: Configurable SSL verification with security warnings
- **Input Validation**: All user inputs are validated and sanitized to prevent injection attacks
- **Response Sanitization**: API responses are sanitized before logging

### Data Protection
- **Secure Memory Management**: Credentials are overwritten in memory when no longer needed
- **Logging Security**: Sensitive information is never logged in plain text
- **Error Handling**: Comprehensive error handling without exposing sensitive details

## Troubleshooting

- **SSL Certificate Errors**: Use `--no-verify` or set `UNIFI_VERIFY_SSL=false` (the toolkit is designed for self-signed certificates)
- **Authentication Failures**: Verify your API token or username/password - the toolkit will attempt both methods
- **Connection Issues**: The toolkit includes retry logic with exponential backoff for transient network issues
- **Missing Access Points**: Ensure the code is properly detecting all device types
- **Layout Issues**: Try different diagram formats or adjust layout algorithms
- **Port Name Updates Not Persisting**: See [Port Update Persistence Fix](docs/port_update_persistence_fix.md) for comprehensive solutions

### Port Name Update Issues

If you're experiencing issues where port name updates return HTTP 200 but don't persist in the UniFi UI:

```bash
# Debug a specific device
./tools/debug_port_updates --env --device-id <device_id>

# Fix persistent port naming issues
./tools/fix_port_persistence --env --device-id <device_id> --port-updates '{"2": "DeviceName"}'
```

See the [detailed port persistence fix documentation](docs/port_update_persistence_fix.md) for more information.

For more detailed information, see the [DETAILED_README.md](DETAILED_README.md) file.

## Dependencies

The project uses the following dependencies:

### Core Dependencies

- **requests**: Used by the `api_client.py` module to communicate with the UniFi Controller API with comprehensive error handling and retry mechanisms
- **python-dotenv**: Used to load environment variables from `.env` files
- **pyunifi**: The Python library for UniFi Controller API

### Analysis and Monitoring

- **statistics**: Used for statistical analysis in network health monitoring and performance metrics
- **datetime/timedelta**: Used for time-based analysis, configuration drift detection, and historical data tracking
- **pathlib**: Used for file system operations in analysis result storage

### HTML Parsing

- **beautifulsoup4**: Used in `html_parser.py` for parsing HTML content
- **lxml**: Used as the HTML parser backend for BeautifulSoup

### Visualization

- **d3.js**: Used for interactive HTML visualizations (loaded via CDN in the HTML output)

### Optional Dependencies

These are included as commented options in requirements.txt since they're not actively used in the current codebase but were in the original requirements:

- **networkx**: For graph representation and algorithms
- **matplotlib**: For generating PNG/SVG diagrams
- **pydot**: For DOT format diagrams
- **pygraphviz**: Alternative for DOT format diagrams

### Utilities

- **rich**: For enhanced console output formatting

## Advanced Diagnostics & Analysis Tools

The toolkit includes a comprehensive suite of advanced network diagnostics, validation, and analysis tools. See [Advanced Diagnostics Documentation](docs/ADVANCED_DIAGNOSTICS.md) for full details.

### Quick Reference

| Tool | CLI Command | Purpose |
|------|-------------|---------|
| MAC Table Analyzer | `unifi-mac-analyzer` | Detect MAC flapping, loops, unauthorized devices |
| Link Quality Monitor | `unifi-link-quality` | Physical layer health, CRC errors, SFP diagnostics |
| Storm Detector | `unifi-storm-detector` | Broadcast/multicast storm detection |
| Client Path Tracer | `unifi-client-trace` | Trace client connectivity through switch fabric |
| Capacity Planner | `unifi-capacity-planner` | Port utilization, PoE budget, growth forecasting |
| QoS Validator | `unifi-qos-validator` | DSCP trust, voice VLAN, queue configuration audit |
| LAG Monitor | `unifi-lag-monitor` | Link aggregation health and load balance |
| Config Backup | `unifi-config-backup` | Configuration snapshots and change tracking |
| Firmware Advisor | `unifi-firmware-advisor` | Firmware security assessment and CVE checking |

### Diagnostics Architecture

```mermaid
flowchart TB
    subgraph "CLI Layer"
        MAC[unifi-mac-analyzer]
        LQ[unifi-link-quality]
        SD[unifi-storm-detector]
        CT[unifi-client-trace]
        CP[unifi-capacity-planner]
        QOS[unifi-qos-validator]
        LAG[unifi-lag-monitor]
        BK[unifi-config-backup]
        FW[unifi-firmware-advisor]
    end

    subgraph "Analysis Modules"
        direction TB
        A1[analyzers/]
        A2[validators/]
        A3[tracers/]
        A4[backup/]
        A5[advisors/]
    end

    subgraph "Core"
        API[UniFi API Client]
        Controller[UniFi Controller]
    end

    MAC --> A1
    LQ --> A1
    SD --> A1
    CP --> A1
    CT --> A3
    QOS --> A2
    LAG --> A2
    BK --> A4
    FW --> A5

    A1 --> API
    A2 --> API
    A3 --> API
    A4 --> API
    A5 --> API
    API --> Controller
```

### Example Usage

```bash
# Detect MAC flapping and unauthorized devices
unifi-mac-analyzer --env --allowed-macs /path/to/allowed.txt

# Check physical layer health
unifi-link-quality --env --output link_report.md

# Detect broadcast storms
unifi-storm-detector --env --broadcast-threshold 500

# Trace client path through network
unifi-client-trace --env --mac aa:bb:cc:dd:ee:ff

# Validate QoS configuration
unifi-qos-validator --env --strict

# Monitor LAG health
unifi-lag-monitor --env

# Backup and compare configurations
unifi-config-backup --env backup -d "Before maintenance"
unifi-config-backup --env diff backup_20241228_120000

# Firmware security assessment
unifi-firmware-advisor --env --min-score 70
```

All tools support common options: `--env`, `--config <file>`, `--json`, `--output <file>`, `--debug`

---

## Port Update Debugging Tools

### Port Update Debugging

The toolkit includes advanced debugging tools for troubleshooting UniFi API port update persistence issues:

- **debug_port_updates**: Comprehensive device configuration analysis and API endpoint testing
- **fix_port_persistence**: Enhanced port update methods with verification and fallback strategies

These tools address the common issue where UniFi API calls return HTTP 200 success but port name changes don't persist in the UI.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
