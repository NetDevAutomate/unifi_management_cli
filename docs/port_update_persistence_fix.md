# UniFi Port Name Update Persistence Fix

## Problem Description

Users reported that UniFi API port name updates return HTTP 200 success codes but the changes don't persist in the UniFi UI. The logs show successful updates, but ports continue to display "Port 2" instead of the expected client device name like "Genos".

## Root Cause Analysis

The issue was caused by several factors in the original `update_device_port_table()` method:

### 1. Insufficient Payload Structure
The original implementation sent minimal update payloads containing only:
```python
{
    "port_table": [...],
    "_id": "device_id",
    "mac": "device_mac"
}
```

### 2. Missing Configuration Context
UniFi devices require complete device configuration context for changes to persist, including:
- Configuration revision numbers (`config_version`, `cfgversion`, `config_revision`)
- Complete current device configuration
- Proper field validation

### 3. API Endpoint Selection Issues
The method used generic device REST endpoints that may not be optimal for port configuration updates.

### 4. No Verification Process
Updates returned HTTP 200 but there was no verification that changes actually persisted.

## Solution Implementation

### Enhanced API Client Methods

The fix implements a multi-layered approach in `src/unifi_mapper/api_client.py`:

#### 1. Comprehensive Device Configuration Update
```python
def _update_device_config_with_ports(self, device_id, device_details, port_table):
    """Update with complete device configuration context."""
    update_data = device_details.copy()  # Start with current config
    update_data["port_table"] = port_table
    
    # Include configuration revision fields (critical for persistence)
    if "config_version" in device_details:
        update_data["config_version"] = device_details["config_version"]
    if "cfgversion" in device_details:
        update_data["cfgversion"] = device_details["cfgversion"]
    if "config_revision" in device_details:
        update_data["config_revision"] = device_details["config_revision"]
```

#### 2. Alternative API Endpoints
```python
def _update_ports_via_port_endpoint(self, device_id, port_table):
    """Try port-specific API endpoints."""
    port_endpoints = [
        f"{base_url}/proxy/network/api/s/{site}/rest/device/{device_id}/port",
        f"{base_url}/proxy/network/api/s/{site}/cmd/devmgr"
    ]
```

#### 3. Fallback Methods
The system tries three approaches in order:
1. Complete device configuration update (recommended)
2. Port-specific endpoint updates
3. Legacy minimal update method (original approach)

#### 4. Update Verification
```python
def verify_port_update(self, device_id, port_idx, expected_name, max_retries=3):
    """Verify that port name update was successfully applied and persisted."""
    # Progressive delay and multiple verification attempts
    # Fresh device details retrieval
    # Actual vs expected name comparison
```

### Enhanced Port Mapper

Updated `src/unifi_mapper/port_mapper.py` with:

#### Verification-Enabled Batch Updates
```python
def batch_update_port_names(self, device_id, port_updates, verify_updates=True):
    """Update multiple port names with verification."""
    # Enhanced logging with device details
    # Comprehensive update process
    # Individual port verification
    # Detailed failure reporting
```

## Debugging Tools

### 1. Debug Port Updates Script
```bash
./tools/debug_port_updates --env --device-id <device_id>
```

Features:
- Comprehensive device configuration analysis
- API endpoint availability testing  
- Port table inspection
- Configuration field validation
- Test port name updates with verification

Example output:
```
=== DEVICE DEBUG INFORMATION ===
Device ID: 60e327b3b2f1234567890123
UniFi OS Mode: True
Site: default

CONFIGURATION FIELDS:
  _id: 60e327b3b2f1234567890123
  mac: 78:45:c4:12:34:56
  model: USW-24-POE
  version: 6.0.45.13762
  config_version: abc123def456

API ENDPOINTS TESTED:
  ✓ /proxy/network/api/s/default/rest/device/60e327b3b2f1234567890123 (Status: 200)
  ✗ /proxy/network/api/s/default/rest/device/60e327b3b2f1234567890123/port (Status: 404)
  ✓ /proxy/network/api/s/default/cmd/devmgr (Status: 200)
```

### 2. Port Persistence Fix Script
```bash
./tools/fix_port_persistence --env --device-id <device_id> --port-updates '{"2": "Genos", "3": "Server"}'
```

Features:
- Enhanced update methods
- Force device provisioning
- Optional device restart
- Multiple verification attempts
- Detailed success/failure reporting

## Usage Examples

### Basic Port Update with New System
```python
from src.unifi_mapper.port_mapper import UnifiPortMapper

port_mapper = UnifiPortMapper(base_url="https://unifi.local", api_token="your_token")
port_mapper.login()

# This now includes automatic verification
success = port_mapper.batch_update_port_names(
    device_id="60e327b3b2f1234567890123",
    port_updates={2: "Genos", 3: "Server"},
    verify_updates=True
)
```

### Debug a Problematic Device
```bash
# Comprehensive device debugging
./tools/debug_port_updates --env --device-id 60e327b3b2f1234567890123

# Test a specific port update
./tools/debug_port_updates --env --device-id 60e327b3b2f1234567890123 --test-port 2 --test-name "TestName"
```

### Force Fix Persistent Issues
```bash
# Standard fix attempt
./tools/fix_port_persistence --env --device-id 60e327b3b2f1234567890123 --port-updates '{"2": "Genos"}'

# Fix with device restart if needed (use with caution)
./tools/fix_port_persistence --env --device-id 60e327b3b2f1234567890123 --port-updates '{"2": "Genos"}' --allow-restart
```

## Implementation Details

### Multi-Approach Update Strategy

The enhanced `update_device_port_table()` method tries three approaches:

1. **Comprehensive Configuration Update** (Primary)
   - Sends complete device configuration with updated port table
   - Includes all configuration revision fields
   - Preserves all current device settings
   - Highest success rate for persistence

2. **Port-Specific Endpoints** (Secondary) 
   - Uses dedicated port configuration endpoints
   - Tries device manager commands
   - More targeted approach

3. **Legacy Method** (Fallback)
   - Original minimal payload approach
   - Maintained for compatibility
   - Used when other methods fail

### Verification Process

Each update is verified through:
- Progressive retry delays (1s, 2s, 3s)
- Fresh device configuration retrieval
- Port-by-port name comparison
- Detailed logging of mismatches

### Enhanced Logging

The system now provides:
- Device identification (name, model, MAC)
- Update attempt details
- Verification results
- Failure diagnosis
- Suggested debugging commands

## Common Issues and Solutions

### Issue: Updates Return 200 but Don't Persist
**Solution**: The enhanced system addresses this through:
- Complete configuration context in updates
- Configuration revision field inclusion
- Multi-endpoint fallback strategy
- Verification with retry logic

### Issue: Specific Device Models Not Working
**Solution**: Debug with:
```bash
./tools/debug_port_updates --env --device-id <device_id>
```
This reveals device-specific configuration requirements and available endpoints.

### Issue: Updates Work but Revert After Time
**Solution**: Use force provisioning:
```bash
./tools/fix_port_persistence --env --device-id <device_id> --port-updates '{"2": "Name"}'
```
This forces the device to sync with the controller configuration.

### Issue: Critical Device Won't Accept Updates
**Solution**: Last resort with device restart:
```bash
./tools/fix_port_persistence --env --device-id <device_id> --port-updates '{"2": "Name"}' --allow-restart
```
**Warning**: This will restart the device and may cause brief network downtime.

## Testing and Validation

To test the fixes:

1. **Identify a problematic device**:
   ```bash
   python unifi_network_mapper.py --env --dry-run
   ```

2. **Debug the device configuration**:
   ```bash
   ./tools/debug_port_updates --env --device-id <device_id>
   ```

3. **Test a single port update**:
   ```bash
   ./tools/debug_port_updates --env --device-id <device_id> --test-port 2 --test-name "TestUpdate"
   ```

4. **Apply real updates with verification**:
   ```bash
   ./tools/fix_port_persistence --env --device-id <device_id> --port-updates '{"2": "RealName"}'
   ```

5. **Verify in UniFi UI**: Check that the port names appear correctly and persist after browser refresh.

## Technical Notes

### Configuration Revision Fields
These fields are critical for persistence:
- `config_version`: Main configuration version identifier
- `cfgversion`: Legacy configuration version field  
- `config_revision`: Alternative revision identifier

### API Endpoint Differences
- **UniFi OS** (UDM, UDM Pro): Uses `/proxy/network/api/...` endpoints
- **Legacy Controllers**: Uses `/api/...` endpoints
- **Port-specific endpoints**: May not be available on all device types

### Verification Strategy
- Multiple attempts with progressive delays
- Fresh data retrieval prevents cached results
- Port-by-port verification ensures granular success detection

This comprehensive fix should resolve the port name persistence issues that users have been experiencing with UniFi API updates.