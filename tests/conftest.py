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


@pytest.fixture(autouse=True)
def _no_live_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any real network request in a test, unless it is marked ``network`` or ``live``.

    This host holds the live controller credentials, so a missed stub must fail rather than
    reach the controller. The real HTTP transports (httpx's sync and async ones, requests'
    adapter) and TCP/UDP socket connects are refused; in-memory transports
    (``httpx.MockTransport``, the fake sessions) and Unix sockets are untouched, so the event
    loop and mocked clients work as before. ``block_network`` stays for tests that also want
    every ``send`` refused.
    """
    if any(request.node.get_closest_marker(name) for name in ('network', 'live')):
        return
    message = 'live network access in a test: use httpx.MockTransport or a fake session'

    def _refused(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError(message)

    async def _refused_async(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError(message)

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    inet = (socket.AF_INET, socket.AF_INET6)

    def _connect(self: socket.socket, address: object) -> None:
        if self.family in inet:
            raise AssertionError(message)
        return real_connect(self, address)  # type: ignore[arg-type]

    def _connect_ex(self: socket.socket, address: object) -> int:
        if self.family in inet:
            raise AssertionError(message)
        return real_connect_ex(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', _refused)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', _refused_async)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', _refused)
    monkeypatch.setattr(socket.socket, 'connect', _connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', _connect_ex)


@pytest.fixture
def isolated_credentials(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Opt-in credential isolation for a test module directly under ``tests/``.

    The isolation of ``tests/mcp/`` (``tests/credential_isolation.py``), plus a chdir into
    ``tmp_path``, so neither the live ``prod.env`` nor ``./.env`` resolves. A new module
    that runs CLI commands declares ``pytestmark = pytest.mark.usefixtures(
    'isolated_credentials')``.
    """
    from tests.credential_isolation import isolate_credentials

    isolate_credentials(request, monkeypatch, tmp_path, chdir=True)


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
