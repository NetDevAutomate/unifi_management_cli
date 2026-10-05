"""Simplified pytest configuration for foundation testing."""

import asyncssh
import httpx
import os
import pytest
import requests
import socket
from pathlib import Path
from typing import NoReturn


pytest_plugins = ['pytester']  # T13. Only this top-level conftest may define pytest_plugins.


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add --run-slow to opt in to slow/network tests."""
    parser.addoption('--run-slow', action='store_true', help='run slow and network tests')


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests marked slow/network unless --run-slow or UNIFI_RUN_SLOW=1."""
    if config.getoption('--run-slow') or os.environ.get('UNIFI_RUN_SLOW') == '1':
        return
    skip = pytest.mark.skip(reason='slow/network: pass --run-slow')
    for item in items:
        if any(item.iter_markers(name='slow')) or any(item.iter_markers(name='network')):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _isolate_xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point XDG_STATE_HOME at a per-test directory so no test touches ~/.local/state."""
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg-state'))


@pytest.fixture(autouse=True)
def _no_live_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any real SSH connect; tests that need SSH install a fake connection.

    This host can hold the gateway's root SSH password, so a missed stub must fail rather
    than connect. ``tests/fake_ssh.py`` holds the shared fake; a test's own
    ``monkeypatch.setattr(asyncssh, 'connect', ...)`` runs later and wins.
    """

    async def _refused(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError('live SSH in a test: install the ssh fake')

    monkeypatch.setattr(asyncssh, 'connect', _refused)


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
