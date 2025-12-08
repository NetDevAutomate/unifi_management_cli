#!/usr/bin/env python3
"""
Test to verify LLDP/CDP data is correctly extracted from device details.
This test has a binary pass/fail outcome.
"""
import sys
import os
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.api_client import UnifiApiClient

def test_lldp_extraction():
    """Test that LLDP info is correctly extracted from device details."""
    # Load environment
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key] = val.strip('"').strip("'")

    # Create client
    client = UnifiApiClient(
        base_url=os.environ['UNIFI_URL'],
        site='default',
        api_token=os.environ['UNIFI_CONSOLE_API_TOKEN'],
        verify_ssl=False
    )

    # Login
    assert client.login(), "Authentication failed"
    print("✅ Authentication successful")

    # Get devices
    devices = client.get_devices('default')
    assert devices and 'data' in devices, "Failed to get devices"
    print(f"✅ Got {len(devices['data'])} devices")

    # Find a switch
    switch_device = None
    for device in devices['data']:
        if device.get('type') in ['usw', 'udm']:
            switch_device = device
            break

    assert switch_device, "No switch found"
    device_id = switch_device.get('_id')
    print(f"✅ Found switch: {switch_device.get('name')} ({switch_device.get('model')})")

    # Get LLDP info using current method
    lldp_info = client.get_lldp_info('default', device_id)
    print(f"📊 LLDP info from get_lldp_info(): {len(lldp_info)} ports")

    # Get device details directly
    details = client.get_device_details('default', device_id)
    lldp_table = details.get('lldp_table', [])
    print(f"📊 lldp_table in device details: {len(lldp_table)} entries")

    # BINARY PASS/FAIL TEST:
    # Test passes if get_lldp_info() returns the same count as lldp_table
    if len(lldp_info) == len(lldp_table) and len(lldp_table) > 0:
        print(f"✅ TEST PASS: get_lldp_info() correctly returns {len(lldp_info)} ports")
        print(f"✅ Matches lldp_table with {len(lldp_table)} entries")
        return True
    elif len(lldp_table) > 0 and len(lldp_info) == 0:
        print(f"❌ TEST FAIL: LLDP data EXISTS ({len(lldp_table)} entries)")
        print(f"❌ BUT get_lldp_info() returns {len(lldp_info)} ports")
        print("\n🔧 FIX NEEDED: get_lldp_info() should extract from lldp_table")
        return False
    elif len(lldp_table) == 0:
        print("❌ TEST FAIL: No LLDP data found in device (LLDP may be disabled)")
        return False
    else:
        print(f"❌ TEST FAIL: Mismatch - get_lldp_info()={len(lldp_info)}, lldp_table={len(lldp_table)}")
        return False

if __name__ == "__main__":
    try:
        result = test_lldp_extraction()
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
