# UniFi Network Topology Visualization Toolkit

A comprehensive toolkit for visualizing and managing UniFi network topologies, including automatic port mapping, network diagram generation, and device management.

## Overview

This toolkit provides a unified interface for:

1. **Network Discovery**: Automatically discover all devices in a UniFi network
2. **Topology Mapping**: Generate network topology maps based on LLDP/CDP information
3. **Port Management**: Automatically name ports based on connected devices
4. **Visualization**: Create visual representations of network topology in multiple formats
5. **API Integration**: Seamless integration with the UniFi Controller API

## Features

### Core Features

- **Comprehensive Device Detection**: Automatically identifies all UniFi devices including routers, switches, and access points
- **LLDP/CDP Information Extraction**: Collects and processes Link Layer Discovery Protocol and Cisco Discovery Protocol information
- **Port Mapping**: Automatically maps and names ports based on connected devices
- **Multiple Visualization Formats**: Supports PNG, SVG, DOT, Mermaid, and interactive HTML diagrams
- **Flexible Authentication**: Supports both API token and username/password authentication
- **Dry Run Mode**: Test port naming changes without applying them
- **Cross-platform Compatibility**: Works on any platform that supports Python 3.6+

### Advanced Features

- **Inferred Topology**: Generates network topology even when LLDP/CDP information is limited
- **Interactive HTML Visualization**: Drag-and-drop interface with zoom, pan, and custom layout saving
- **Device Type Detection**: Automatically identifies device types (routers, switches, APs)
- **Location-based Grouping**: Groups devices by location based on naming conventions
- **Comprehensive Reporting**: Generates detailed reports of network topology and port mappings

## Code Structure

The project is organized into the following components:

### Main Entry Point

- **unifi_network_mapper.py**: The main entry point that provides a unified command-line interface

### Core Modules (`src/unifi_mapper/`)

- **api_client.py**: Handles communication with the UniFi Controller API
- **models.py**: Contains data models for devices and ports
- **enhanced_network_topology.py**: Manages network topology visualization with advanced features
- **run_methods.py**: Contains helper methods for running the port mapper
- **port_mapper.py**: Handles port mapping and naming
- **report_generator.py**: Generates detailed reports of network topology and port mappings
- **device_definitions.py**: Defines device models and their port configurations

### Command-line Scripts (`src/scripts/`)

- **topology_generator.py**: Generates network topology diagrams
- **port_mapper.py**: Maps and names ports based on connected devices
- **inferred_topology_generator.py**: Generates inferred network topology
- **api_client.py**: Command-line interface to the UniFi API
- **config_manager.py**: Manages configuration settings
- **device_definitions.py**: Manages device definitions

## Class Diagram

```mermaid
classDiagram
    class UnifiNetworkMapper {
        +main()
        +load_env_file()
    }
    
    class UnifiApiClient {
        -base_url: str
        -site: str
        -session: requests.Session
        -is_unifi_os: bool
        +login()
        +get_devices()
        +get_device_ports()
        +get_lldp_info()
        +get_clients()
        +update_port_name()
    }
    
    class DeviceInfo {
        +id: str
        +name: str
        +model: str
        +mac: str
        +ip: str
        +ports: List[PortInfo]
        +lldp_info: Dict
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
    }
    
    class NetworkTopology {
        -devices: Dict[str, DeviceInfo]
        -connections: List[Dict]
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
    }
    
    class UnifiPortMapper {
        -api_client: UnifiApiClient
        -site: str
        -dry_run: bool
        +map_ports()
        +generate_report()
        +generate_diagram()
    }
    
    class ReportGenerator {
        +generate_port_mapping_report()
        +generate_device_table()
        +generate_port_table()
    }
    
    UnifiNetworkMapper --> UnifiPortMapper: creates
    UnifiPortMapper --> UnifiApiClient: uses
    UnifiPortMapper --> NetworkTopology: creates
    UnifiPortMapper --> ReportGenerator: uses
    NetworkTopology --> DeviceInfo: contains
    DeviceInfo --> PortInfo: contains
```

## Sequence Diagram

```mermaid
sequenceDiagram
    participant User
    participant UnifiNetworkMapper
    participant UnifiPortMapper
    participant UnifiApiClient
    participant NetworkTopology
    participant ReportGenerator
    
    User->>UnifiNetworkMapper: Run with arguments
    UnifiNetworkMapper->>UnifiPortMapper: Create port mapper
    UnifiPortMapper->>UnifiApiClient: Initialize API client
    UnifiNetworkMapper->>UnifiApiClient: Login
    UnifiApiClient-->>UnifiNetworkMapper: Authentication result
    
    UnifiNetworkMapper->>UnifiApiClient: Get devices
    UnifiApiClient-->>UnifiNetworkMapper: Device list
    
    loop For each router/switch
        UnifiNetworkMapper->>UnifiApiClient: Get device ports
        UnifiApiClient-->>UnifiNetworkMapper: Port information
        UnifiNetworkMapper->>UnifiApiClient: Get LLDP/CDP info
        UnifiApiClient-->>UnifiNetworkMapper: LLDP/CDP information
    end
    
    UnifiNetworkMapper->>UnifiApiClient: Get clients
    UnifiApiClient-->>UnifiNetworkMapper: Client list
    
    UnifiNetworkMapper->>NetworkTopology: Create topology
    NetworkTopology->>NetworkTopology: Process devices and connections
    NetworkTopology->>NetworkTopology: Infer missing connections
    
    alt Generate HTML diagram
        UnifiNetworkMapper->>NetworkTopology: Generate HTML diagram
        NetworkTopology-->>UnifiNetworkMapper: HTML diagram
    else Generate PNG diagram
        UnifiNetworkMapper->>NetworkTopology: Generate PNG diagram
        NetworkTopology-->>UnifiNetworkMapper: PNG diagram
    else Generate other format
        UnifiNetworkMapper->>NetworkTopology: Generate diagram
        NetworkTopology-->>UnifiNetworkMapper: Diagram
    end
    
    UnifiNetworkMapper->>ReportGenerator: Generate report
    ReportGenerator-->>UnifiNetworkMapper: Markdown report
    
    UnifiNetworkMapper-->>User: Output files
```

## Module Dependencies

```mermaid
flowchart TD
    A[unifi_network_mapper.py] --> B[src/unifi_mapper/port_mapper.py]
    A --> C[src/unifi_mapper/run_methods.py]
    A --> D[src/unifi_mapper/models.py]
    
    B --> E[src/unifi_mapper/api_client.py]
    
    C --> E
    C --> F[src/unifi_mapper/enhanced_network_topology.py]
    C --> G[src/unifi_mapper/report_generator.py]
    
    F --> D
    E --> D
    G --> D
    
    F --> H[src/unifi_mapper/device_definitions.py]
    
    subgraph Core Modules
        B
        C
        D
        E
        F
        G
        H
    end
    
    subgraph Command-line Scripts
        I[src/scripts/topology_generator.py]
        J[src/scripts/port_mapper.py]
        K[src/scripts/inferred_topology_generator.py]
        L[src/scripts/api_client.py]
        M[src/scripts/config_manager.py]
        N[src/scripts/device_definitions.py]
    end
    
    I --> B
    J --> B
    K --> B
    L --> E
    N --> H
```

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/unifi-network-mapper.git
   cd unifi-network-mapper
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Configure your UniFi Controller credentials (see Configuration section below).

## Configuration

Before using the toolkit, you need to configure your UniFi Controller credentials. You can do this in two ways:

1. **Environment Variables** (create a `.env` file):
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

2. **Command Line Arguments**:
   ```
   --url https://192.168.1.1
   --site default
   --token your_api_token
   # Or use username/password authentication
   --username your_username
   --password your_password
   --no-verify  # Skip SSL verification
   ```

## Usage

### Quick Start

The simplest way to use the toolkit is with the unified command:

```bash
# Using environment variables
python unifi_network_mapper.py --env

# Using command line arguments
python unifi_network_mapper.py --url https://192.168.1.1 --token your_api_token

# Dry run mode (doesn't apply changes)
python unifi_network_mapper.py --env --dry-run

# Specify output paths
python unifi_network_mapper.py --env --output reports/port_mapping_report.md --diagram diagrams/network.png

# Specify diagram format
python unifi_network_mapper.py --env --format svg

# Generate interactive HTML diagram
python unifi_network_mapper.py --env --format html --diagram diagrams/network.html

# Include all connected devices (not just UniFi devices)
python unifi_network_mapper.py --env --format html --diagram diagrams/all_devices.html --connected-devices
```

### Output Files

After running the toolkit, you'll find:

1. **Port Mapping Report** (default: `reports/port_mapping_report.md`):
   - Summary of all devices and ports
   - Detailed information about each device
   - Tables showing port status, names, and connected devices

2. **Network Diagram** (default: `diagrams/network_diagram.png`):
   - Visual representation of your network topology
   - Shows connections between devices
   - Color-coded by device type

## Troubleshooting

### API Connection Issues

1. **SSL Certificate Errors**: If you encounter SSL certificate errors, use the `--no-verify` option or set `UNIFI_VERIFY_SSL=false` in your `.env` file.
2. **Authentication Failures**: Ensure your API token or username/password is correct. For UniFi OS devices (UDM, UDM Pro), you may need to use a different authentication method.
3. **API Version Issues**: Different UniFi Controller versions may have different API endpoints. The toolkit attempts to detect the correct version automatically.

### Port Mapping Issues

1. **No LLDP/CDP Information**: If devices don't have LLDP/CDP information, check that LLDP/CDP is enabled on your devices.
2. **Incorrect Port Names**: Check the device definitions in `src/unifi_mapper/device_definitions.py` to ensure the port naming scheme is correct for your devices.
3. **Permission Errors**: Ensure your API token or user account has sufficient permissions to modify device settings.

### Visualization Issues

1. **Missing Dependencies**: For PNG and SVG output, ensure you have the required dependencies installed:
   ```bash
   pip install matplotlib networkx pydot
   ```
2. **Layout Issues**: If the network diagram layout is not optimal, try adjusting the layout algorithm in `src/unifi_mapper/enhanced_network_topology.py`.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
