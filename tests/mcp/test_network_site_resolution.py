"""The six ``network_api`` tools with only the controller's config (issue 037).

Fake Integration API pages through ``httpx.MockTransport`` behind the tools' own read-only
guard, so nothing reaches a network. The site id comes from one ``GET /v1/sites`` matched on
``internalReference == UNIFI_SITE`` and is cached for the process; zero or several matches
are a clear error naming what was found. ``--check`` stays offline and reports the deferred
resolution.
"""

from __future__ import annotations

import httpx
import json
import os
import pytest
from pathlib import Path
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.mcp import config as mcp_config
from unifi_mapper.mcp import server
from unifi_mapper.mcp.tools import network as network_tools
from unifi_mapper.network import client as network_client


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
OTHER_ID = '660e8400-e29b-41d4-a716-446655440001'
API = '/proxy/network/integration/v1'
PROBE = ('GET', f'{API}/info')
CONTROLLER = {
    'UNIFI_URL': 'https://192.0.2.1',
    'UNIFI_SITE': 'home',
    'UNIFI_CONSOLE_API_TOKEN': FAKE_TOKEN,
}
ZONES = [{'id': 'z1', 'name': 'Internal'}]


class Api(httpx.MockTransport):
    """A fake Integration API: records every request and the API key header it carried."""

    def __init__(self, sites: list[dict[str, Any]], redirect_to: str | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.keys: set[str] = set()
        self._sites = sites
        self._redirect_to = redirect_to
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.host, request.url.path))
        self.keys.add(request.headers.get('X-API-KEY', ''))
        if self._redirect_to:
            return httpx.Response(302, headers={'Location': self._redirect_to})
        if (request.method, request.url.path) == PROBE:
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        if request.url.path == f'{API}/sites':
            data = self._sites
        elif request.url.path == f'{API}/sites/{SITE_ID}/firewall/zones':
            data = ZONES
        elif request.url.path == f'{API}/sites/{SITE_ID}/firewall/policies':
            data = []
        else:
            return httpx.Response(404, json={'statusCode': 404, 'statusName': 'NOT_FOUND'})
        page = {'offset': 0, 'limit': 200, 'count': len(data), 'totalCount': len(data)}
        return httpx.Response(200, json={**page, 'data': data})


def _site(site_id: str, name: str) -> dict[str, Any]:
    return {'id': site_id, 'internalReference': name, 'name': name.title()}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    fresh: dict[str, str] = dict(CONTROLLER)
    monkeypatch.setattr(os, 'environ', fresh)
    network_client.clear_site_id_cache()
    return fresh


def _serve(monkeypatch: pytest.MonkeyPatch, api: Api) -> Api:
    monkeypatch.setattr(network_tools, '_inner_transport', lambda _config: api)
    return api


async def test_one_matching_site_is_resolved_once_and_cached(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _serve(monkeypatch, Api([_site(OTHER_ID, 'lab'), _site(SITE_ID, 'home')]))

    zones = await network_tools.get_firewall_zones()
    zones_again = await network_tools.get_firewall_zones()

    assert [z['id'] for z in zones] == [z['id'] for z in zones_again] == ['z1']
    sites_calls = [c for c in api.calls if c[2] == f'{API}/sites']
    assert len(sites_calls) == 1, api.calls  # cached for the process
    assert api.keys == {FAKE_TOKEN}  # the console token, same origin
    assert all(host == '192.0.2.1' for _, host, _ in api.calls)


async def test_no_matching_site_is_a_clear_error_naming_what_was_found(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, Api([_site(OTHER_ID, 'lab'), _site(SITE_ID, 'office')]))
    with pytest.raises(ToolError) as excinfo:
        await network_tools.get_firewall_zones()
    error = excinfo.value
    assert error.error_code == ErrorCodes.CONFIG_INVALID
    assert "'home'" in error.message and 'lab' in error.message and 'office' in error.message
    assert error.suggestion and 'UNIFI_NETWORK_SITE_ID' in error.suggestion
    assert FAKE_TOKEN not in error.message


async def test_two_matching_sites_are_refused_naming_both_ids(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, Api([_site(SITE_ID, 'home'), _site(OTHER_ID, 'home')]))
    with pytest.raises(ToolError) as excinfo:
        await network_tools.get_firewall_zones()
    assert excinfo.value.error_code == ErrorCodes.CONFIG_INVALID
    assert SITE_ID in excinfo.value.message and OTHER_ID in excinfo.value.message


async def test_an_explicit_site_id_skips_the_lookup(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env['UNIFI_NETWORK_SITE_ID'] = SITE_ID
    api = _serve(monkeypatch, Api([]))
    assert [z['id'] for z in await network_tools.get_firewall_zones()] == ['z1']
    assert not [c for c in api.calls if c[2] == f'{API}/sites']


async def test_a_different_network_host_gets_no_console_token(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env['UNIFI_NETWORK_HOST'] = 'other.example'
    api = _serve(monkeypatch, Api([_site(SITE_ID, 'home')]))
    with pytest.raises(ToolError) as excinfo:
        await network_tools.get_firewall_zones()
    assert excinfo.value.error_code == ErrorCodes.CONFIG_MISSING
    assert 'UNIFI_NETWORK_API_KEY' in excinfo.value.message
    assert api.calls == []  # nothing was sent anywhere
    assert FAKE_TOKEN not in excinfo.value.message


async def test_a_redirect_to_another_origin_is_not_followed(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _serve(
        monkeypatch, Api([], redirect_to='https://evil.example/proxy/network/integration/v1/info')
    )
    with pytest.raises(ToolError):
        await network_tools.get_firewall_zones()
    assert {host for _, host, _ in api.calls} == {'192.0.2.1'}


# --- --check stays offline ----------------------------------------------------------------------


def test_readiness_reports_the_deferred_resolution_without_a_controller_call(
    tmp_path: Path,
) -> None:
    env: dict[str, str] = dict(CONTROLLER)
    status = mcp_config.family_status('network_api', env, 'environment')
    assert status.ready
    assert status.missing == ()
    assert status.derived == (
        'host: derived from UNIFI_URL',
        'site id: resolved at first call',
        'key: console token (same origin)',
    )
    assert status.to_json_dict()['derived'] == list(status.derived)
    assert FAKE_TOKEN not in repr(status.to_json_dict())


def test_readiness_with_a_different_host_is_missing_the_key_not_leaking_the_token() -> None:
    env = {**CONTROLLER, 'UNIFI_NETWORK_HOST': 'other.example'}
    status = mcp_config.family_status('network_api', env, 'environment')
    assert not status.ready
    assert any('UNIFI_NETWORK_API_KEY' in m for m in status.missing)
    assert 'key: console token (same origin)' not in status.derived


def test_check_report_from_a_controller_only_file_is_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``unifi-mcp --check`` on a file with only the controller keys: the network family is
    ready with the three deferred notes, and nothing is sent anywhere."""
    config = tmp_path / 'prod.env'
    config.write_text(''.join(f'{k}={v}\n' for k, v in CONTROLLER.items()))
    monkeypatch.setattr(os, 'environ', {})
    monkeypatch.setattr(network_tools, '_inner_transport', lambda _c: pytest.fail('went online'))

    with pytest.raises(SystemExit) as e:
        server.main(['--check', '--config', str(config)])

    assert e.value.code == 0
    report = json.loads(capsys.readouterr().out)
    family = report['families']['network_api']
    assert family['ready'] is True
    assert family['derived'] == [
        'host: derived from UNIFI_URL',
        'site id: resolved at first call',
        'key: console token (same origin)',
    ]
    assert FAKE_TOKEN not in json.dumps(report)
