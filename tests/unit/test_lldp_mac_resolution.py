#!/usr/bin/env python3
"""
Binary test for LLDP MAC address resolution to device names.
CRITICAL: This tests the diagram data accuracy fix.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.lldp_client import LldpClient


def test_mac_resolution_to_device_names():
    """Binary test: chassis_id (MAC) resolves to device name"""
    # Mock device client
    mock_device_client = Mock()

    # Mock device list with MACs
    mock_device_client.get_devices.return_value = {
        "data": [
            {"_id": "dev1", "name": "Switch-Main", "mac": "aa:bb:cc:dd:ee:ff"},
            {"_id": "dev2", "name": "Router-Core", "mac": "11:22:33:44:55:66"},
            {"_id": "dev3", "name": "AP-Office", "mac": "77:88:99:aa:bb:cc"},
        ]
    }

    # Mock device details with lldp_table (no system_name, only chassis_id)
    mock_device_client.get_device_details.return_value = {
        "_id": "dev1",
        "lldp_table": [
            {
                "local_port_idx": 1,
                "chassis_id": "11:22:33:44:55:66",  # Router MAC
                "port_id": "Port 5",
            },
            {
                "local_port_idx": 2,
                "chassis_id": "77:88:99:aa:bb:cc",  # AP MAC
                "port_id": "Port 1",
            },
        ],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "dev1")

    # Verify MAC resolved to device names
    assert result["1"]["remote_device_name"] == "Router-Core"
    assert result["1"]["chassis_id"] == "11:22:33:44:55:66"

    assert result["2"]["remote_device_name"] == "AP-Office"
    assert result["2"]["chassis_id"] == "77:88:99:aa:bb:cc"

    print("✅ PASS: MACs resolve to device names")
    return True


def test_mac_resolution_case_insensitive():
    """Binary test: MAC resolution works regardless of case"""
    mock_device_client = Mock()

    mock_device_client.get_devices.return_value = {
        "data": [{"_id": "dev1", "name": "Switch-Test", "mac": "AA:BB:CC:DD:EE:FF"}]
    }

    # LLDP has lowercase MAC
    mock_device_client.get_device_details.return_value = {
        "_id": "dev1",
        "lldp_table": [
            {
                "local_port_idx": 1,
                "chassis_id": "aa:bb:cc:dd:ee:ff",  # Lowercase
                "port_id": "Port 1",
            }
        ],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "dev1")

    assert result["1"]["remote_device_name"] == "Switch-Test"

    print("✅ PASS: MAC resolution is case-insensitive")
    return True


def test_mac_resolution_without_colons():
    """Binary test: MAC resolution works with or without colons"""
    mock_device_client = Mock()

    mock_device_client.get_devices.return_value = {
        "data": [{"_id": "dev1", "name": "Device-Test", "mac": "11:22:33:44:55:66"}]
    }

    # LLDP has MAC without colons
    mock_device_client.get_device_details.return_value = {
        "_id": "dev1",
        "lldp_table": [
            {
                "local_port_idx": 1,
                "chassis_id": "112233445566",  # No colons
                "port_id": "Port 1",
            }
        ],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "dev1")

    assert result["1"]["remote_device_name"] == "Device-Test"

    print("✅ PASS: MAC resolution works without colons")
    return True


def test_unresolvable_mac_returns_mac():
    """Binary test: Unresolvable MACs return the MAC address"""
    mock_device_client = Mock()

    # Device list has different MACs
    mock_device_client.get_devices.return_value = {
        "data": [{"_id": "dev1", "name": "Known-Device", "mac": "aa:bb:cc:dd:ee:ff"}]
    }

    # LLDP has unknown MAC
    mock_device_client.get_device_details.return_value = {
        "_id": "dev1",
        "lldp_table": [
            {
                "local_port_idx": 1,
                "chassis_id": "99:88:77:66:55:44",  # Unknown MAC
                "port_id": "Port 1",
            }
        ],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "dev1")

    # Should return MAC as fallback
    assert result["1"]["remote_device_name"] == "99:88:77:66:55:44"

    print("✅ PASS: Unresolvable MACs return MAC address")
    return True


if __name__ == "__main__":
    tests = [
        test_mac_resolution_to_device_names,
        test_mac_resolution_case_insensitive,
        test_mac_resolution_without_colons,
        test_unresolvable_mac_returns_mac,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"❌ ERROR: {test.__name__} - {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✅ ALL TESTS PASS")
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        sys.exit(1)
