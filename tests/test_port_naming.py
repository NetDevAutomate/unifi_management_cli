from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.run_methods import _choose_port_name
from unittest.mock import Mock


class DummyResponse:
    status_code = 200
    text = '{"meta":{"rc":"ok"}}'
    headers = {}

    def json(self):
        return {'meta': {'rc': 'ok'}}


def test_update_port_names_persists_names_in_port_overrides():
    client = UnifiApiClient(
        base_url='https://unifi.example',
        site='default',
        api_token='token',
    )
    client.is_authenticated = True
    client.is_unifi_os = True
    client.get_device_details = Mock(
        return_value={
            '_id': 'a' * 24,
            'mac': 'aa:bb:cc:dd:ee:ff',
            'config_version': 7,
            'port_overrides': [
                {'port_idx': 1, 'name': 'Old AP', 'poe_mode': 'auto'},
                {'port_idx': 2, 'name': 'Old stale device', 'speed': 0},
            ],
        }
    )
    client._retry_request = Mock(side_effect=lambda func: func())
    client.session.put = Mock(return_value=DummyResponse())

    assert client.update_port_names('a' * 24, {1: 'Charlie2 U6-Pro', 2: 'Port 2'})

    _, kwargs = client.session.put.call_args
    payload = kwargs['json']
    overrides = {override['port_idx']: override for override in payload['port_overrides']}

    assert payload['_id'] == 'a' * 24
    assert payload['mac'] == 'aa:bb:cc:dd:ee:ff'
    assert payload['config_version'] == 7
    assert overrides[1] == {
        'port_idx': 1,
        'name': 'Charlie2 U6-Pro',
        'poe_mode': 'auto',
    }
    assert overrides[2] == {'port_idx': 2, 'name': 'Port 2'}
    assert 'port_table' not in payload


def test_choose_port_name_prefers_lldp_device_name():
    port_mapper = Mock()

    name, source = _choose_port_name(
        3,
        {'remote_device_name': 'Hotel3 USW Flex XG 10G'},
        {},
        port_mapper,
    )

    assert (name, source) == ('Hotel3 USW Flex XG 10G', 'lldp')


def test_choose_port_name_uses_clients_when_lldp_is_only_mac():
    port_mapper = Mock()
    port_mapper.format_client_names.return_value = 'MacMini'

    name, source = _choose_port_name(
        2,
        {'remote_device_name': '02:00:fe:00:00:08'},
        {2: [{'name': 'MacMini'}]},
        port_mapper,
    )

    assert (name, source) == ('MacMini', 'client')


def test_choose_port_name_keeps_active_port_name_when_client_label_is_weak():
    port_mapper = Mock()
    port_mapper.format_client_names.return_value = 'DAC0FE'

    name, source = _choose_port_name(
        1,
        {},
        {1: [{'name': ''}]},
        port_mapper,
        current_name='Mike2 USW Lite 8 PoE',
        port_up=True,
    )

    assert (name, source) == ('Mike2 USW Lite 8 PoE', 'current')


def test_choose_port_name_defaults_disconnected_port_to_numbered_label():
    port_mapper = Mock()

    name, source = _choose_port_name(
        7,
        {},
        {},
        port_mapper,
        current_name='Old stale device',
        port_up=False,
    )

    assert (name, source) == ('Port 7', 'default')
