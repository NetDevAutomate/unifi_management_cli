"""Simplified pytest configuration for foundation testing."""

import httpx
import pytest
import requests
import socket


@pytest.fixture
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to reach a real network (opt-in).

    Patches the requests and httpx send paths and raw socket connects, so a
    unit test that accidentally builds a live client fails loudly instead of
    talking to a controller.
    """

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('live network access in a unit test')

    monkeypatch.setattr(requests.Session, 'request', _blocked)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', _blocked)
    monkeypatch.setattr(httpx.Client, 'send', _blocked)
    monkeypatch.setattr(httpx.AsyncClient, 'send', _blocked)
    monkeypatch.setattr(socket.socket, 'connect', _blocked)


@pytest.fixture
def sample_mac() -> str:
    """Sample MAC address for testing."""
    return 'aa:bb:cc:dd:ee:ff'


@pytest.fixture
def sample_ip() -> str:
    """Sample IP address for testing."""
    return '192.0.2.10'


# Pytest markers for test organization
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        'markers',
        'live: marks tests that require live UniFi controller connection',
    )
    config.addinivalue_line('markers', 'slow: marks tests that take longer than 5 seconds')
    config.addinivalue_line('markers', 'integration: marks tests that test component integration')
