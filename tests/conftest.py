"""Simplified pytest configuration for foundation testing."""

import pytest


@pytest.fixture
def sample_mac() -> str:
    """Sample MAC address for testing."""
    return 'aa:bb:cc:dd:ee:ff'


@pytest.fixture
def sample_ip() -> str:
    """Sample IP address for testing."""
    return '192.168.1.10'


# Pytest markers for test organization
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        'markers',
        'live: marks tests that require live UniFi controller connection',
    )
    config.addinivalue_line('markers', 'slow: marks tests that take longer than 5 seconds')
    config.addinivalue_line('markers', 'integration: marks tests that test component integration')
