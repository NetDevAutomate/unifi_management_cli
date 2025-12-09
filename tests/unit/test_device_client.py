#!/usr/bin/env python3
"""
Binary pass/fail tests for DeviceClient.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

import requests

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.device_client import DeviceClient
from unifi_mapper.endpoint_builder import UnifiEndpointBuilder


def test_get_devices_success():
    """Binary test: get_devices returns device list on success"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"_id": "dev1", "name": "Switch1", "model": "USW-24"},
            {"_id": "dev2", "name": "Router1", "model": "UDM-PRO"},
        ]
    }
    session.get = Mock(return_value=mock_response)

    client = DeviceClient(endpoint_builder, session)
    result = client.get_devices("default")

    assert "data" in result
    assert len(result["data"]) == 2
    assert result["data"][0]["_id"] == "dev1"

    print("✅ PASS: get_devices returns device list")
    return True


def test_get_device_details_success():
    """Binary test: get_device_details returns device with port_table"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "_id": "device123",
                "name": "Test Switch",
                "model": "USW-24",
                "port_table": [
                    {"port_idx": 1, "name": "Port 1"},
                    {"port_idx": 2, "name": "Port 2"},
                ],
                "lldp_table": [],
            }
        ]
    }
    session.get = Mock(return_value=mock_response)

    client = DeviceClient(endpoint_builder, session)
    result = client.get_device_details("default", "device123")

    assert result["_id"] == "device123"
    assert "port_table" in result
    assert len(result["port_table"]) == 2

    print("✅ PASS: get_device_details returns device data")
    return True


def test_get_clients_success():
    """Binary test: get_clients returns client list"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"mac": "aa:bb:cc:dd:ee:ff", "name": "Laptop1", "is_wired": True},
            {"mac": "11:22:33:44:55:66", "name": "Phone1", "is_wired": False},
        ]
    }
    session.get = Mock(return_value=mock_response)

    client = DeviceClient(endpoint_builder, session)
    result = client.get_clients("default")

    assert "data" in result
    assert len(result["data"]) == 2
    assert result["data"][0]["mac"] == "aa:bb:cc:dd:ee:ff"

    print("✅ PASS: get_clients returns client list")
    return True


def test_get_device_ports_from_device_details():
    """Binary test: get_device_ports extracts port_table from device details"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock device details with port_table
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "_id": "device123",
                "port_table": [
                    {"port_idx": 1, "name": "Port 1", "up": True},
                    {"port_idx": 2, "name": "Port 2", "up": False},
                ],
            }
        ]
    }
    session.get = Mock(return_value=mock_response)

    client = DeviceClient(endpoint_builder, session)
    ports = client.get_device_ports("default", "device123")

    assert isinstance(ports, list)
    assert len(ports) == 2
    assert ports[0]["port_idx"] == 1
    assert ports[1]["port_idx"] == 2

    print("✅ PASS: get_device_ports extracts port_table")
    return True


def test_error_handling_returns_empty():
    """Binary test: Errors return empty collections, not exceptions"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock error response
    mock_response = Mock()
    mock_response.status_code = 500
    session.get = Mock(return_value=mock_response)

    client = DeviceClient(endpoint_builder, session)

    # Should return empty, not raise
    devices = client.get_devices("default")
    assert devices == {}

    clients = client.get_clients("default")
    assert clients == {}

    details = client.get_device_details("default", "dev123")
    assert details == {}

    ports = client.get_device_ports("default", "dev123")
    assert ports == []

    print("✅ PASS: Errors return empty collections gracefully")
    return True


if __name__ == "__main__":
    tests = [
        test_get_devices_success,
        test_get_device_details_success,
        test_get_clients_success,
        test_get_device_ports_from_device_details,
        test_error_handling_returns_empty,
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
