"""Every sync client gets the same timeout and retry settings, however it is built (issue 087).

Issue 042 handed ``UNIFI_TIMEOUT``, ``UNIFI_MAX_RETRIES`` and ``UNIFI_RETRY_DELAY`` to the
``UnifiApiClient`` wherever a ``UnifiConfig`` builds it (``typer_cli._readonly_client`` is
the reference here). Two sites built the client another way and kept the client's defaults:
``inventory_cli.get_api_client`` and ``port_diagnostics_tools._readonly_sync_client``, which
``inspect_port`` also uses. Each test builds a real client all three ways from one config and
compares the three settings.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from typing import Any
from unifi_mapper import inventory_cli, typer_cli
from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.diagnostics import port_diagnostics_tools


pytestmark = pytest.mark.usefixtures('block_network')

FAKE_TOKEN = 'fake-settings-token'  # pragma: allowlist secret


def _settings(client: Any) -> tuple[int, int, float]:
    return (client.timeout, client.max_retries, client.retry_delay)


@pytest.fixture
def no_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real clients, but no login, logout or guard reaches the network."""
    monkeypatch.setattr(UnifiApiClient, 'login', lambda self: True)
    monkeypatch.setattr(UnifiApiClient, 'logout', lambda self: True)
    monkeypatch.setattr(
        'unifi_mapper.core.utils.readonly.install_read_only_guard', lambda *a, **k: None
    )


def _config(tmp_path: Path, **settings: str) -> Path:
    lines = ['UNIFI_URL=https://192.0.2.1', f'UNIFI_CONSOLE_API_TOKEN={FAKE_TOKEN}']
    lines += [f'{key}={value}' for key, value in settings.items()]
    path = tmp_path / 'settings.env'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _three_ways(monkeypatch: pytest.MonkeyPatch, config: Path) -> dict[str, tuple]:
    """Build the client through each site from ``config`` and return each one's settings."""
    built: dict[str, tuple] = {}

    monkeypatch.setattr(typer_cli.state, 'config_path', config)
    with typer_cli._readonly_client() as (client, _site):
        built['config'] = _settings(client)

    client, _site = inventory_cli.get_api_client(str(config))
    built['inventory'] = _settings(client)

    # The MCP server has already put the config's keys in the environment.
    with port_diagnostics_tools._readonly_sync_client() as (client, _site):
        built['mcp'] = _settings(client)
    return built


@pytest.mark.usefixtures('no_login')
def test_configured_settings_reach_every_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config(tmp_path, UNIFI_TIMEOUT='42', UNIFI_MAX_RETRIES='7', UNIFI_RETRY_DELAY='2.5')

    built = _three_ways(monkeypatch, config)

    assert built == {'config': (42, 7, 2.5), 'inventory': (42, 7, 2.5), 'mcp': (42, 7, 2.5)}


@pytest.mark.usefixtures('no_login')
def test_out_of_range_settings_are_clamped_the_same_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config(
        tmp_path, UNIFI_TIMEOUT='999', UNIFI_MAX_RETRIES='50', UNIFI_RETRY_DELAY='0.01'
    )

    built = _three_ways(monkeypatch, config)

    assert set(built.values()) == {(300, 10, 0.1)}


@pytest.mark.usefixtures('no_login')
def test_unset_settings_give_every_client_the_same_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _three_ways(monkeypatch, _config(tmp_path))

    assert set(built.values()) == {(10, 3, 1.0)}
    assert 'UNIFI_MAX_RETRIES' not in os.environ


def test_a_malformed_setting_is_a_config_error_for_the_mcp_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unifi_mapper.core.utils.errors import ErrorCodes, ToolError

    monkeypatch.setitem(os.environ, 'UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setitem(os.environ, 'UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)
    monkeypatch.setitem(os.environ, 'UNIFI_TIMEOUT', 'ten')

    with pytest.raises(ToolError) as caught:
        with port_diagnostics_tools._readonly_sync_client():
            pass

    assert caught.value.error_code == ErrorCodes.CONFIG_INVALID


def test_inspect_port_builds_its_client_through_the_shared_sync_client() -> None:
    """``inspect_port`` has no construction of its own to drift (it reuses the MCP client)."""
    import inspect
    from unifi_mapper.diagnostics import inspect_port

    source = inspect.getsource(inspect_port)
    assert '_sync_tools._readonly_sync_client()' in source
    assert 'UnifiApiClient(' not in source
