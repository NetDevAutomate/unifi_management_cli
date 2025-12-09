#!/usr/bin/env python3
"""
Integration test for refactored UnifiApiClient.
Binary test: Refactored client maintains backward compatibility.
"""

import os
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.api_client_refactored import UnifiApiClient


def test_refactored_client_integration():
    """
    Binary test: Refactored client works with real UniFi Controller.
    Tests all delegated methods maintain backward compatibility.
    """
    # Load environment
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, val = line.strip().split("=", 1)
                    os.environ[key] = val.strip('"').strip("'")

    # Create client using refactored implementation
    client = UnifiApiClient(
        base_url=os.environ["UNIFI_URL"],
        site="default",
        api_token=os.environ["UNIFI_CONSOLE_API_TOKEN"],
        verify_ssl=False,
    )

    # Test 1: Login
    assert client.login(), "❌ Login failed"
    assert client.is_authenticated, "❌ Not marked as authenticated"
    print("✅ Login successful")

    # Test 2: Get devices
    devices = client.get_devices("default")
    assert devices and "data" in devices, "❌ Failed to get devices"
    assert len(devices["data"]) > 0, "❌ No devices found"
    print(f"✅ Got {len(devices['data'])} devices")

    # Test 3: Get clients
    clients = client.get_clients("default")
    assert clients and "data" in clients, "❌ Failed to get clients"
    print(f"✅ Got {len(clients['data'])} clients")

    # Test 4: Get device details (find first switch)
    switch_device = None
    for device in devices["data"]:
        if device.get("type") in ["usw", "udm"]:
            switch_device = device
            break

    assert switch_device, "❌ No switch found"
    device_id = switch_device["_id"]
    print(f"✅ Found switch: {switch_device['name']}")

    details = client.get_device_details("default", device_id)
    assert details and "_id" in details, "❌ Failed to get device details"
    print("✅ Got device details")

    # Test 5: Get ports
    ports = client.get_device_ports("default", device_id)
    assert isinstance(ports, list), "❌ Ports not a list"
    print(f"✅ Got {len(ports)} ports")

    # Test 6: Get LLDP info (THE CRITICAL TEST - original bug)
    lldp_info = client.get_lldp_info("default", device_id)
    assert isinstance(lldp_info, dict), "❌ LLDP info not a dict"

    # Verify LLDP data matches lldp_table
    lldp_table = details.get("lldp_table", [])
    expected_count = len(lldp_table)
    actual_count = len(lldp_info)

    if actual_count == expected_count:
        print(f"✅ LLDP info correct: {actual_count} ports (ORIGINAL BUG FIXED)")
    else:
        print(f"❌ LLDP mismatch: got {actual_count}, expected {expected_count}")
        return False

    # Test 7: Logout
    assert client.logout(), "❌ Logout failed"
    print("✅ Logout successful")

    return True


if __name__ == "__main__":
    try:
        result = test_refactored_client_integration()
        if result:
            print("\n" + "=" * 50)
            print("✅ ALL INTEGRATION TESTS PASS")
            print("Refactored client maintains full backward compatibility")
            sys.exit(0)
        else:
            print("\n" + "=" * 50)
            print("❌ INTEGRATION TEST FAILED")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ TEST FAILED WITH EXCEPTION: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
