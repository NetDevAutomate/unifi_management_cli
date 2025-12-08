#!/usr/bin/env python3
"""
Binary pass/fail tests for PortClient.
"""

import sys
from pathlib import Path
from unittest.mock import Mock
import requests

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.port_client import PortClient
from unifi_mapper.endpoint_builder import UnifiEndpointBuilder


def test_update_port_name_success():
    """Binary test: Single port name update succeeds"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock device details with port_table
    device_data = {
        "_id": "device123",
        "port_table": [
            {"port_idx": 1, "name": "Port 1"},
            {"port_idx": 2, "name": "Port 2"}
        ]
    }

    # Mock device client
    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = device_data

    # Mock successful update
    mock_response = Mock()
    mock_response.status_code = 200
    session.put = Mock(return_value=mock_response)

    client = PortClient(endpoint_builder, session, mock_device_client)
    result = client.update_port_name("default", "device123", 1, "New Port Name")

    assert result is True
    # Verify port was updated in the call
    call_args = session.put.call_args
    port_table = call_args[1]['json']['port_table']
    assert port_table[0]['name'] == "New Port Name"

    print("✅ PASS: Single port update succeeds")
    return True


def test_batch_update_port_names():
    """Binary test: Batch port updates apply all changes"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock device details
    device_data = {
        "_id": "device123",
        "port_table": [
            {"port_idx": 1, "name": "Port 1"},
            {"port_idx": 2, "name": "Port 2"},
            {"port_idx": 3, "name": "Port 3"}
        ]
    }

    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = device_data

    # Mock successful update
    mock_response = Mock()
    mock_response.status_code = 200
    session.put = Mock(return_value=mock_response)

    client = PortClient(endpoint_builder, session, mock_device_client)

    # Update ports 1 and 3
    updates = {
        1: "Router-Main",
        3: "AP-Office"
    }

    result = client.batch_update_port_names("default", "device123", updates)

    assert result is True

    # Verify all ports updated
    call_args = session.put.call_args
    port_table = call_args[1]['json']['port_table']
    assert port_table[0]['name'] == "Router-Main"
    assert port_table[1]['name'] == "Port 2"  # Unchanged
    assert port_table[2]['name'] == "AP-Office"

    print("✅ PASS: Batch port updates apply all changes")
    return True


def test_update_nonexistent_port():
    """Binary test: Updating nonexistent port returns False"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    device_data = {
        "_id": "device123",
        "port_table": [
            {"port_idx": 1, "name": "Port 1"}
        ]
    }

    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = device_data

    client = PortClient(endpoint_builder, session, mock_device_client)

    # Try to update port 99 (doesn't exist)
    result = client.update_port_name("default", "device123", 99, "New Name")

    assert result is False  # Should fail gracefully

    print("✅ PASS: Nonexistent port update returns False")
    return True


def test_batch_update_empty_dict():
    """Binary test: Empty batch update returns True (no-op)"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()
    mock_device_client = Mock()

    client = PortClient(endpoint_builder, session, mock_device_client)

    result = client.batch_update_port_names("default", "device123", {})

    assert result is True  # Empty update is successful no-op
    assert mock_device_client.get_device_details.call_count == 0  # No API calls

    print("✅ PASS: Empty batch update is no-op")
    return True


def test_verify_port_update_success():
    """Binary test: Port verification succeeds when name matches"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock device details with updated port
    device_data = {
        "_id": "device123",
        "port_table": [
            {"port_idx": 1, "name": "Updated-Name"}
        ]
    }

    mock_device_client = Mock()
    mock_device_client.get_device_details.return_value = device_data

    client = PortClient(endpoint_builder, session, mock_device_client)

    result = client.verify_port_update("default", "device123", 1, "Updated-Name", max_retries=1)

    assert result is True

    print("✅ PASS: Port verification succeeds when name matches")
    return True


if __name__ == "__main__":
    tests = [
        test_update_port_name_success,
        test_batch_update_port_names,
        test_update_nonexistent_port,
        test_batch_update_empty_dict,
        test_verify_port_update_success
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

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✅ ALL TESTS PASS")
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        sys.exit(1)
