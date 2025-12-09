# Unifi Port Mapper

A Python tool to automatically name Unifi device ports based on LLDP/CDP neighbor information.

## Features

- Connects to a Unifi Controller using credentials from a `.env` file
- Retrieves all devices and their port information
- Automatically names ports based on LLDP/CDP neighbor information
- If no LLDP/CDP information is available, sets port names to "Port X"
- Generates a Markdown report with:
  - Mermaid diagram showing network topology
  - Detailed tables for each device's ports
  - Summary of all changes made

## Requirements

- Python 3.7+
- Unifi Controller with API access

## Installation

1. Clone this repository
2. Create a virtual environment using uv:
   ```bash
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies using uv:
   ```bash
   uv pip install -r requirements.txt
   ```

## Configuration

Create a `.env` file in the project directory with the following variables:

```
# URL of your Unifi Controller (required)
UNIFI_URL=https://your-unifi-controller:8443

# Authentication - either use API token (recommended) or username/password
UNIFI_CONSOLE_API_TOKEN=your_api_token
# OR
UNIFI_USERNAME=your_username
UNIFI_PASSWORD=your_password

# Optional settings
UNIFI_SITE=default
APPLY_CHANGES=false
```

### Required Settings
- `UNIFI_URL`: The URL of your Unifi Controller (including port)

### Authentication (choose one method)
- **API Token Authentication (Recommended):**
  - `UNIFI_CONSOLE_API_TOKEN`: Your Unifi Controller API token
- **Username/Password Authentication:**
  - `UNIFI_USERNAME`: Your Unifi Controller username
  - `UNIFI_PASSWORD`: Your Unifi Controller password

### Optional Settings
- `UNIFI_SITE`: The site name (default: "default")
- `APPLY_CHANGES`: Whether to apply the port name changes (true/false)

## Usage

Run the script:

```bash
python unifi_port_mapper.py [options]
```

This will:
1. Connect to your Unifi Controller
2. Retrieve all devices and their port information
3. Determine new port names based on LLDP/CDP information
4. Apply changes if `APPLY_CHANGES=true` in your `.env` file (unless `--dry-run` is specified)
5. Generate a Markdown report

### Command-line Options

```
  --dry-run             Run in dry-run mode (don't apply changes)
  --report REPORT       Path to save the report (default: port_mapping_report.md)
  --site SITE           Unifi site name (default: from .env or 'default')
  --url URL             Unifi Controller URL (default: from .env)
  --username USERNAME   Unifi Controller username (default: from .env)
  --password PASSWORD   Unifi Controller password (default: from .env)
  --token TOKEN         Unifi Controller API token (default: from .env)
  --debug               Enable debug logging
```

### Examples

```bash
# Run in dry-run mode (don't apply any changes)
python unifi_port_mapper.py --dry-run

# Specify a custom report filename
python unifi_port_mapper.py --report my_report.md

# Connect to a specific site
python unifi_port_mapper.py --site my-site

# Override credentials from .env file (username/password)
python unifi_port_mapper.py --url https://unifi.example.com:8443 --username admin --password secret

# Use API token authentication
python unifi_port_mapper.py --token your_api_token
```

## Report

The generated report includes:

- A Mermaid diagram showing the network topology
- Detailed tables for each device's ports
- A summary of all changes made

## Extending the Tool

The tool is designed with extensibility in mind using a class-based approach. You can:

- Subclass `UnifiPortMapper` to add custom functionality
- Add new methods to process different types of devices
- Implement different naming schemes
- Add support for other network management systems

## License

MIT
