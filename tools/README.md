# UniFi Network Tools

This directory contains command-line tools for managing and troubleshooting UniFi networks.

## Available Tools

### UniFi Client Lookup

The `unifi_lookup` tool allows you to search for clients by name, MAC address, or IP address:

```bash
# Basic usage
./unifi_lookup "macbook" --env

# Search using command line arguments
./unifi_lookup "192.168.1" --url https://unifi.local:8443 --token your_api_token

# Enable debug logging
./unifi_lookup "printer" --env --debug
```

### UniFi IP Conflict Detector

The `unifi_ip_conflict` tool identifies duplicate IP addresses in your network:

```bash
# Basic usage
./unifi_ip_conflict --env

# Using command line arguments
./unifi_ip_conflict --url https://unifi.local:8443 --token your_api_token

# Include historical clients (may include stale data)
./unifi_ip_conflict --env --include-historical

# Enable debug logging
./unifi_ip_conflict --env --debug
```

## Common Options

All tools support the following options:

- `--url URL`: UniFi Controller URL (e.g., https://unifi.local:8443)
- `--site SITE`: UniFi site name (default: default)
- `--username USERNAME`: UniFi Controller username
- `--password PASSWORD`: UniFi Controller password
- `--token TOKEN`: UniFi Controller API token
- `--verify-ssl`: Verify SSL certificates (default: disabled)
- `--timeout SECONDS`: Connection timeout in seconds
- `--env`: Load credentials from .env file
- `--debug`: Enable debug logging

## Environment Variables

You can configure these tools using environment variables in a `.env` file:

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
