#!/usr/bin/env python3
"""
Binary pass/fail tests for LldpClient.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.lldp_client import LldpClient


def test_extract_lldp_from_device_details():
    """Binary test: LLDP data extracted from device_details lldp_table"""
    # Mock device client
    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = {
        "_id": "device123",
        "lldp_table": [
            {
                "local_port_idx": 1,
                "chassis_id": "aa:bb:cc:dd:ee:ff",
                "port_id": "Port 5",
                "system_name": "Router-Main",
                "local_port_name": "eth0",
            },
            {
                "local_port_idx": 3,
                "chassis_id": "11:22:33:44:55:66",
                "port_id": "Port 1",
                "chassis_name": "AP-Office",
                "local_port_name": "eth2",
            },
        ],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "device123")

    assert "1" in result  # Port 1 has LLDP data
    assert "3" in result  # Port 3 has LLDP data
    assert len(result) == 2

    # Verify field mapping
    port1_info = result["1"]
    assert port1_info["port_idx"] == 1
    assert port1_info["system_name"] == "Router-Main"
    assert port1_info["remote_device_name"] == "Router-Main"
    assert port1_info["remote_port_name"] == "Port 5"

    port3_info = result["3"]
    assert port3_info["port_idx"] == 3
    assert port3_info["remote_device_name"] == "AP-Office"  # Falls back to chassis_name

    print("✅ PASS: LLDP data extracted from lldp_table")
    return True


def test_empty_lldp_table():
    """Binary test: Empty lldp_table returns empty dict"""
    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = {
        "_id": "device123",
        "lldp_table": [],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "device123")

    assert result == {}
    assert len(result) == 0

    print("✅ PASS: Empty lldp_table returns empty dict")
    return True


def test_missing_lldp_table():
    """Binary test: Missing lldp_table returns empty dict"""
    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = {
        "_id": "device123"
        # No lldp_table key
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "device123")

    assert result == {}

    print("✅ PASS: Missing lldp_table returns empty dict")
    return True


def test_lldp_field_mapping():
    """Binary test: LLDP fields correctly mapped to expected format"""
    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = {
        "_id": "device123",
        "lldp_table": [
            {
                "local_port_idx": 5,
                "chassis_id": "test:mac:addr",
                "port_id": "ge-0/0/5",
                "system_name": "CoreSwitch",
                "chassis_name": "backup-name",
                "local_port_name": "eth4",
                "is_wired": True,
            }
        ],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "device123")

    assert "5" in result  # String key
    lldp_info = result["5"]

    # Verify all expected fields present
    required_fields = [
        "port_idx",
        "chassis_id",
        "port_id",
        "system_name",
        "chassis_name",
        "remote_device_name",
        "remote_port_name",
        "is_wired",
        "local_port_name",
    ]

    for field in required_fields:
        assert field in lldp_info, f"Missing field: {field}"

    # Verify mapping logic
    assert lldp_info["port_idx"] == 5  # Int value
    assert (
        lldp_info["remote_device_name"] == "CoreSwitch"
    )  # system_name takes precedence
    assert lldp_info["remote_port_name"] == "ge-0/0/5"

    print("✅ PASS: LLDP field mapping correct")
    return True


def test_system_name_fallback():
    """Binary test: Falls back to chassis_name when system_name missing"""
    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = {
        "_id": "device123",
        "lldp_table": [
            {
                "local_port_idx": 1,
                "chassis_id": "aa:bb:cc:dd:ee:ff",
                "chassis_name": "FallbackName",
                # No system_name
                "port_id": "Port 1",
            }
        ],
    }

    client = LldpClient(mock_device_client)
    result = client.get_lldp_info("default", "device123")

    assert result["1"]["remote_device_name"] == "FallbackName"

    print("✅ PASS: Falls back to chassis_name correctly")
    return True


if __name__ == "__main__":
    tests = [
        test_extract_lldp_from_device_details,
        test_empty_lldp_table,
        test_missing_lldp_table,
        test_lldp_field_mapping,
        test_system_name_fallback,
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
