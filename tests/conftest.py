#!/usr/bin/env python3
"""
Pytest configuration and shared fixtures for UniFi Network Mapper tests.
"""

import sys
from pathlib import Path

import pytest

# Add src to Python path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def mock_unifi_config():
    """Fixture providing mock UniFi configuration."""
    from unifi_mapper.config import UnifiConfig

    return UnifiConfig(
        base_url="https://test-unifi.local:8443",
        site="default",
        api_token="mock-token-12345",
        verify_ssl=False,
        timeout=10,
    )


@pytest.fixture
def mock_device_data():
    """Fixture providing sample device data."""
    return {
        "_id": "device123",
        "name": "Office Switch",
        "model": "USW-24-POE",
        "type": "usw",
        "mac": "aa:bb:cc:dd:ee:ff",
        "ip": "192.168.1.10",
        "adopted": True,
        "state": 1,
    }


@pytest.fixture
def mock_lldp_table():
    """Fixture providing sample LLDP table data."""
    return [
        {
            "chassis_id": "11:22:33:44:55:66",
            "port_id": "Port 1",
            "local_port_name": "eth0",
            "local_port_idx": 1,
            "system_name": "Router-Main",
            "is_wired": True,
        },
        {
            "chassis_id": "77:88:99:aa:bb:cc",
            "port_id": "Port 5",
            "local_port_name": "eth4",
            "local_port_idx": 5,
            "system_name": "AP-Office",
            "is_wired": True,
        },
    ]


@pytest.fixture
def mock_client_data():
    """Fixture providing sample client data."""
    return {
        "mac": "dd:ee:ff:11:22:33",
        "name": "Laptop-001",
        "hostname": "laptop-office",
        "ip": "192.168.1.100",
        "is_wired": True,
        "sw_mac": "aa:bb:cc:dd:ee:ff",
        "sw_port": 10,
        "is_online": True,
        "last_seen": 1700000000,
        "dev_cat_name": "Computer",
        "dev_vendor": "Apple",
        "dev_id": "MacBook",
    }
