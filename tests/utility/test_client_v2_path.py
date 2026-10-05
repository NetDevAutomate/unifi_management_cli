"""``UniFiClient.build_v2_path`` builds the Network application's v2 API paths."""

from tests.fixtures_unifi import FAKE_TOKEN
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.readonly import request_allowed


def _client() -> UniFiClient:
    return UniFiClient(Credentials(host='192.0.2.1', api_token=FAKE_TOKEN))


def test_build_v2_path_names_the_site() -> None:
    client = _client()
    assert client.build_v2_path('apgroups') == '/proxy/network/v2/api/site/default/apgroups'
    client._site_name = 'site-b'
    assert client.build_v2_path('system-log/admin-activity') == (
        '/proxy/network/v2/api/site/site-b/system-log/admin-activity'
    )


def test_a_get_on_a_v2_path_passes_the_read_only_guard_and_a_put_does_not() -> None:
    path = _client().build_v2_path('apgroups')
    assert request_allowed('GET', f'https://192.0.2.1{path}', 'default')[0] is True
    assert request_allowed('PUT', f'https://192.0.2.1{path}', 'default')[0] is False
