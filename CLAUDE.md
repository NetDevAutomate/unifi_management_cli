# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is the UniFi Network Topology Visualization Toolkit - a Python-based tool for managing UniFi networks through automatic port mapping, topology visualization, and network analysis.

## Common Development Commands

### Installation and Setup
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### Running the Application
```bash
# Main entry point - unified interface
python unifi_network_mapper.py --env

# Enhanced port naming with client device names for PCs
python unifi_network_mapper.py --env --connected-devices

# Dry run to preview port name changes
python unifi_network_mapper.py --env --connected-devices --dry-run

# Individual scripts
python src/scripts/unifi_lookup.py "search_term" --env
python src/scripts/unifi_ip_conflict_detector.py --env

# Wrapper tools
./tools/unifi_lookup "search_term" --env
./tools/unifi_ip_conflict --env
```

### Development and Testing
```bash
# No formal test suite - testing is done through dry runs
python unifi_network_mapper.py --env --dry-run

# Debug mode with enhanced logging
python unifi_network_mapper.py --env --debug
```

## Architecture Overview

### Core Components

**Main Entry Points:**
- `unifi_network_mapper.py` - Unified CLI interface
- `src/unifi_mapper/main.py` - Core application logic

**Key Modules:**
- `src/unifi_mapper/api_client.py` - UniFi Controller API communication
- `src/unifi_mapper/models.py` - Data models (DeviceInfo, PortInfo)
- `src/unifi_mapper/enhanced_network_topology.py` - Network topology visualization
- `src/unifi_mapper/port_mapper.py` - Port mapping and naming logic
- `src/unifi_mapper/report_generator.py` - Report generation

**Utility Scripts:**
- `src/scripts/unifi_lookup.py` - Client search functionality
- `src/scripts/unifi_ip_conflict_detector.py` - IP conflict detection

### Data Flow

1. **Authentication** - API client connects to UniFi Controller using token or credentials
2. **Discovery** - Fetches devices, ports, LLDP/CDP info, and clients
3. **Topology Building** - Creates network topology from discovered data
4. **Port Mapping** - Names ports based on connected devices
5. **Visualization** - Generates diagrams (HTML, PNG, SVG, DOT, Mermaid)
6. **Reporting** - Creates detailed markdown reports

### Key Data Models

- `DeviceInfo` - Represents UniFi devices (switches, routers, APs)
- `PortInfo` - Represents individual ports with connection details
- `NetworkTopology` - Manages device relationships and visualizations

## Configuration

The application uses environment variables loaded from `.env` file:

```env
UNIFI_URL=https://192.168.1.1
UNIFI_SITE=default
UNIFI_CONSOLE_API_TOKEN=your_api_token
UNIFI_VERIFY_SSL=false
UNIFI_TIMEOUT=10
```

Alternative username/password authentication:
```env
UNIFI_USERNAME=your_username
UNIFI_PASSWORD=your_password
```

## Enhanced Port Naming

The toolkit now supports enhanced port naming that works with both UniFi devices and PC/client connections:

### How It Works

1. **UniFi-to-UniFi Connections**: Uses LLDP/CDP information (existing functionality)
2. **PC/Client Connections**: Uses client device names from UniFi controller when `--connected-devices` flag is used

### Client Name Priority
When naming ports connected to PCs/clients, the system uses this priority:
1. **Custom client name** (set in UniFi controller)
2. **Hostname** (from DHCP/NetBIOS)
3. **Device vendor + model** (e.g., "Dell-OptiPlex")
4. **MAC address** (last 6 characters as fallback)

### Usage Examples
```bash
# Enable client-based port naming
python unifi_network_mapper.py --env --connected-devices

# Preview changes without applying them
python unifi_network_mapper.py --env --connected-devices --dry-run
```

### Port Naming Results
- **Before**: "Port 3"
- **After**: "Johns-MacBook" or "Dell-OptiPlex (+2)" for multiple devices

## Authentication Patterns

The toolkit supports multiple authentication methods:
- **API Token** (preferred) - Set `UNIFI_CONSOLE_API_TOKEN`
- **Username/Password** - Set `UNIFI_USERNAME` and `UNIFI_PASSWORD`
- **Interactive** - Prompts for credentials if not provided

API client automatically detects UniFi OS vs Classic controller and adjusts endpoints accordingly.

## Output Files

Default output locations:
- Reports: `reports/port_mapping_report.md`
- Diagrams: `diagrams/network_diagram.png` (or specified format)
- Interactive diagrams: `diagrams/network.html`

## Development Considerations

- **SSL Verification** - Disabled by default due to self-signed certificates
- **Dry Run Mode** - Always test changes before applying to production
- **Error Handling** - API client handles authentication failures and endpoint detection
- **Logging** - Uses Python logging module with configurable levels
- **Cross-platform** - Works on Windows, macOS, and Linux

## Implementation Details

### Enhanced Port Naming (New Feature)
- **Client Detection**: `get_client_port_mapping()` in `port_mapper.py` correlates wired clients to switch ports
- **Name Formatting**: `format_client_names()` handles multiple clients per port with configurable limits
- **Integration**: Enhanced logic in `run_methods.py` applies client names when `--connected-devices` is used
- **Fallback Logic**: Only uses client names when no LLDP/CDP information is available

## Important Notes

- The `tmp/` directory contains experimental and backup code - avoid using these files
- Interactive HTML diagrams use D3.js loaded via CDN
- LLDP/CDP information is crucial for accurate topology mapping
- The toolkit can infer connections even when LLDP/CDP data is limited
- **New**: Use `--connected-devices` flag to enable client-based port naming for PC connections