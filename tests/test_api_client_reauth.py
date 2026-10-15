"""A 401 or 403 mid-session re-authenticates for real before the retry.

``UnifiApiClient.login`` returns ``True`` without a request whenever ``is_authenticated`` is
already set. The three readers that catch a 401/403 (``get_devices``, ``get_clients``,
``get_device_details``) called it as their re-authentication step, so on an expired session
they logged "Re-authentication successful", performed no login, and replayed the request with
the same dead session. Found by the 0.4.0 MCP-runtime lane while building the shared sync
session (issue 021); the shared session's own refresh covers its callers, and these fix the
client for everyone else.
"""

from __future__ import annotations

import pytest
from typing import Any
from unifi_mapper.api_client import UnifiApiClient
from unittest.mock import Mock


SITE = 'default'
DEVICE_ID = 'a' * 24


def _response(status: int, payload: Any = None) -> Mock:
    response = Mock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    return response


def _client(answers: list[Mock]) -> tuple[UnifiApiClient, list[str]]:
    """A client whose session answers from ``answers`` in order and whose login is counted."""
    client = UnifiApiClient(base_url='https://unifi.example', site=SITE, api_token='token')
    client.is_authenticated = True
    client.is_unifi_os = True
    client.session = Mock()
    client.session.headers = {}
    client.session.get = Mock(side_effect=answers)
    client.session.post = Mock(side_effect=answers)
    events: list[str] = []

    def perform_login() -> bool:
        events.append('login')
        client.is_authenticated = True
        return True

    client._perform_login = perform_login  # type: ignore[method-assign]
    return client, events


@pytest.mark.parametrize(
    ('method', 'args', 'payload'),
    [
        ('get_devices', (SITE,), {'data': [{'_id': DEVICE_ID}]}),
        ('get_clients', (SITE,), {'data': [{'mac': '02:00:00:00:00:01'}]}),
    ],
)
def test_a_401_performs_a_real_re_login_before_the_retry(
    method: str, args: tuple, payload: dict
) -> None:
    client, events = _client([_response(401), _response(200, payload)])

    result = getattr(client, method)(*args)

    assert events == ['login'], (
        'the re-authentication must reach _perform_login, not the cached short-circuit'
    )
    assert result == payload
    assert client.session.get.call_count == 2


def test_device_details_401_performs_a_real_re_login_before_the_retry() -> None:
    details = {'_id': DEVICE_ID, 'mac': '02:00:00:00:00:01'}
    client, events = _client([_response(401), _response(200, {'data': [details]})])

    result = client.get_device_details(SITE, DEVICE_ID)

    assert events == ['login']
    assert result == details


def test_the_mac_name_cache_is_rebuilt_once_it_is_older_than_the_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client that lives for a server process re-learns device names within the TTL."""
    from unifi_mapper import api_client as module

    client, _events = _client([])
    builds: list[str] = []
    client._build_mac_to_device_cache = lambda site_id: builds.append(site_id)  # type: ignore[method-assign]
    client.get_device_details = Mock(return_value={})  # type: ignore[method-assign]
    clock = {'now': 1000.0}
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock['now'])

    client.get_lldp_info(SITE, DEVICE_ID)
    clock['now'] += module.MAC_CACHE_TTL_SECONDS / 2
    client.get_lldp_info(SITE, DEVICE_ID)
    assert builds == [SITE], 'inside the TTL the cache is reused'

    clock['now'] += module.MAC_CACHE_TTL_SECONDS
    client.get_lldp_info(SITE, DEVICE_ID)
    assert builds == [SITE, SITE], 'past the TTL it is rebuilt once'
