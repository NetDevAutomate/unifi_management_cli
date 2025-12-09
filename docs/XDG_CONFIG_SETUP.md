# XDG Base Directory Configuration Guide

## Overview

UniFi Network Mapper follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html) for configuration file management.

## Default Configuration Location

```bash
# XDG_CONFIG_HOME (if set)
$XDG_CONFIG_HOME/unifi_network_mapper/

# Or default
~/.config/unifi_network_mapper/
```

## Setup Instructions

### 1. Create Configuration Directory

```bash
# Create XDG-compliant config directory
mkdir -p ~/.config/unifi_network_mapper

# Or use XDG_CONFIG_HOME if you have it set
mkdir -p $XDG_CONFIG_HOME/unifi_network_mapper
```

### 2. Create Configuration Files

```bash
# Production network
cat > ~/.config/unifi_network_mapper/prod.env << 'EOF'
UNIFI_URL=https://unifi.company.com
UNIFI_CONSOLE_API_TOKEN=your_production_token_here
UNIFI_SITE=default
UNIFI_VERIFY_SSL=true
UNIFI_TIMEOUT=30
EOF

# Staging network
cat > ~/.config/unifi_network_mapper/staging.env << 'EOF'
UNIFI_URL=https://unifi-staging.company.com
UNIFI_CONSOLE_API_TOKEN=your_staging_token_here
UNIFI_SITE=staging
UNIFI_VERIFY_SSL=false
UNIFI_TIMEOUT=10
EOF

# Home lab
cat > ~/.config/unifi_network_mapper/homelab.env << 'EOF'
UNIFI_URL=https://192.168.1.1:8443
UNIFI_CONSOLE_API_TOKEN=your_homelab_token_here
UNIFI_SITE=default
UNIFI_VERIFY_SSL=false
UNIFI_TIMEOUT=10
EOF

# Default configuration (used when no --config specified)
ln -s ~/.config/unifi_network_mapper/prod.env ~/.config/unifi_network_mapper/default.env
```

### 3. Set Appropriate Permissions

```bash
# Secure config files (contain sensitive tokens)
chmod 600 ~/.config/unifi_network_mapper/*.env

# Verify permissions
ls -la ~/.config/unifi_network_mapper/
# Should show: -rw------- (read/write for owner only)
```

## Usage Examples

### Using Default Config

```bash
# If ~/.config/unifi_network_mapper/default.env exists
unifi-mapper --format png

# Uses default config automatically
```

### Using Specific Configs

```bash
# Production network
unifi-mapper --config ~/.config/unifi_network_mapper/prod.env

# Staging network
unifi-mapper --config ~/.config/unifi_network_mapper/staging.env --dry-run

# Home lab
unifi-mapper --config ~/.config/unifi_network_mapper/homelab.env --debug
```

### Shorthand Paths

```bash
# Full path
unifi-mapper --config ~/.config/unifi_network_mapper/prod.env

# Or use environment variable
export UNIFI_CONFIG=~/.config/unifi_network_mapper/prod.env
unifi-mapper --config $UNIFI_CONFIG
```

## Directory Structure

```
~/.config/unifi_network_mapper/
├── default.env      → symlink to prod.env
├── prod.env         # Production controller
├── staging.env      # Staging/test controller
├── homelab.env      # Personal lab
├── office.env       # Office network
└── remote.env       # Remote site
```

## Environment Variable Support

### XDG_CONFIG_HOME

```bash
# Override default config location
export XDG_CONFIG_HOME=/custom/config/location
unifi-mapper  # Will look in /custom/config/location/unifi_network_mapper/
```

### Per-Session Override

```bash
# Use different config for this session only
XDG_CONFIG_HOME=/tmp/test-config unifi-mapper --format html
```

## Fallback Behavior

1. **CLI --config flag**: Highest priority (explicit path)
2. **XDG config**: `$XDG_CONFIG_HOME/unifi_network_mapper/default.env`
3. **Default XDG**: `~/.config/unifi_network_mapper/default.env`
4. **Current directory**: `.env` (legacy fallback)

```bash
# Priority demonstration
unifi-mapper --config /custom/path/special.env  # Uses this (priority 1)
unifi-mapper  # Uses ~/.config/unifi_network_mapper/default.env (priority 2-3)
# If no default.env exists, uses .env in current directory (priority 4)
```

## Migration from Legacy

### If you have existing .env files:

```bash
# Move to XDG location
mkdir -p ~/.config/unifi_network_mapper
mv .env ~/.config/unifi_network_mapper/default.env

# Or copy for multiple networks
cp .env ~/.config/unifi_network_mapper/prod.env
# Edit staging-specific settings
cp prod.env ~/.config/unifi_network_mapper/staging.env
```

## Best Practices

### 1. Security

```bash
# Always set restrictive permissions
chmod 600 ~/.config/unifi_network_mapper/*.env

# Never commit config files
echo "*.env" >> .gitignore
```

### 2. Organization

```bash
# Use descriptive names
prod.env        # Production
staging.env     # Staging
dev.env         # Development
homelab.env     # Personal
remote-site.env # Specific locations
```

### 3. Documentation

```bash
# Add README in config directory
cat > ~/.config/unifi_network_mapper/README.md << 'EOF'
# UniFi Network Mapper Configurations

## Networks
- prod.env: Main production network (unifi.company.com)
- staging.env: Testing environment
- homelab.env: Personal lab setup

## Security
All .env files contain API tokens - keep permissions at 600
EOF
```

## Troubleshooting

### Config file not found

```bash
# Check default location
ls -la ~/.config/unifi_network_mapper/

# Check XDG_CONFIG_HOME
echo $XDG_CONFIG_HOME

# Test with explicit path
unifi-mapper --config ~/.config/unifi_network_mapper/prod.env --debug
```

### Permission denied

```bash
# Fix permissions
chmod 600 ~/.config/unifi_network_mapper/*.env

# Verify
ls -la ~/.config/unifi_network_mapper/
```

### Wrong config loaded

```bash
# Check which config is being used
unifi-mapper --debug 2>&1 | grep "Loaded configuration from"
```

## Advantages of XDG Standard

✅ **Consistent**: Follows Linux/Unix conventions
✅ **Clean**: Keeps home directory uncluttered
✅ **Discoverable**: Standard location for all apps
✅ **Portable**: Works with XDG_CONFIG_HOME override
✅ **Secure**: Easy to backup/sync entire ~/.config
✅ **Professional**: Industry standard for CLI tools

## Related Environment Variables

```bash
# Configuration
XDG_CONFIG_HOME=~/.config          # Config files

# Data (for future use)
XDG_DATA_HOME=~/.local/share       # Persistent data (could store history)

# Cache (for future use)
XDG_CACHE_HOME=~/.cache            # Cache files (could store API cache)

# Runtime (for future use)
XDG_RUNTIME_DIR=/run/user/$(id -u) # Runtime files (sockets, PIDs)
```

## Example: Multi-Environment Setup

```bash
# Setup script for new user
#!/bin/bash

CONFIG_DIR=~/.config/unifi_network_mapper
mkdir -p "$CONFIG_DIR"

# Production
cat > "$CONFIG_DIR/prod.env" << 'EOF'
UNIFI_URL=https://unifi-prod.company.com
UNIFI_CONSOLE_API_TOKEN=${PROD_TOKEN}
UNIFI_SITE=default
UNIFI_VERIFY_SSL=true
EOF

# Staging
cat > "$CONFIG_DIR/staging.env" << 'EOF'
UNIFI_URL=https://unifi-staging.company.com
UNIFI_CONSOLE_API_TOKEN=${STAGING_TOKEN}
UNIFI_SITE=staging
UNIFI_VERIFY_SSL=false
EOF

# Set default
ln -sf "$CONFIG_DIR/prod.env" "$CONFIG_DIR/default.env"

# Secure
chmod 600 "$CONFIG_DIR"/*.env

echo "✅ Configuration setup complete at $CONFIG_DIR"
```

---

**Compliance**: XDG Base Directory Specification v0.8
**Standard**: freedesktop.org
**Status**: ✅ Fully Compliant
