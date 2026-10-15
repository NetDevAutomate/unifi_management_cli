"""Fake UniFi controller payloads and an in-memory transport for diagnostic tests.

Nothing here touches a network. Identifiers are fake but shaped like real
sanitised payloads: locally administered MACs (``02:00:00:...``), RFC 5737
TEST-NET addresses, a ``FAKESERIAL`` serial and 24-hex-digit ``_id`` values.
Secret-bearing fields carry ``FAKE-*`` values that tests assert never reach any
output. All negotiation values are invented test data, not a description of any
real port profile.
"""

import copy
import json
import re
import requests
from typing import Any, Callable, Optional
from unifi_mapper.api_client import UnifiApiClient
from urllib.parse import urlsplit


SITE = 'default'
BASE_URL = 'https://192.0.2.1'
API = '/proxy/network/api/s/default'
V2 = '/proxy/network/v2/api/site/default'
# Route patterns match both UniFi OS (proxied) and legacy controller paths.
API_RE = r'(?:/proxy/network)?/api/s/default'
V2_RE = r'(?:/proxy/network)?/v2/api/site/default'

SWITCH_ID = 'ab0000000000000000000001'
OTHER_SWITCH_ID = '0000000000000000000000a2'
PEER_ID = '0000000000000000000000a3'
SWITCH_MAC = '02:00:00:00:00:01'
OTHER_SWITCH_MAC = '02:00:00:00:00:02'
PEER_MAC = '02:00:00:00:00:03'
NAS_MAC = '02:00:00:00:00:51'
NAS_MAC_2 = '02:00:00:00:00:52'
OTHER_CLIENT_MAC = '02:00:00:00:00:61'
SWITCH_IP = '192.0.2.10'
OTHER_SWITCH_IP = '192.0.2.11'
PEER_IP = '192.0.2.12'
NAS_IP = '203.0.113.51'
SERIAL = 'aaaaaaaaaa0001'
PROF_10G = '0000000000000000000000b1'
PROF_AUTO = '0000000000000000000000b2'
PROF_TRUNK = '0000000000000000000000b3'
NET_MGMT = '0000000000000000000000c1'
NET_GUEST = '0000000000000000000000c2'
SWITCH_NAME = 'USW Flex XG'
OTHER_SWITCH_NAME = 'Hotel3 USW Flex XG 10G'
PROFILE_10G_NAME = 'Access Port VLAN 255 Management 10Gbps'
PROFILE_AUTO_NAME = 'Access Port VLAN 255 Management Auto'

FAKE_AUTHKEY = 'FAKE-AUTHKEY-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_PORT_SECRET = 'FAKE-PORT-SECRET-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_PASSPHRASE = 'FAKE-PASSPHRASE-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_PW = 'FAKE-PW-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_TOKEN = 'FAKE-API-TOKEN-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_EVENT_SECRET = 'FAKE-EVENT-SECRET-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_SECRETS = (
    FAKE_AUTHKEY,
    FAKE_PORT_SECRET,
    FAKE_PASSPHRASE,
    FAKE_PW,
    FAKE_TOKEN,
    FAKE_EVENT_SECRET,
)

# A fixed clock: 2026-09-21T14:13:20Z.
NOW = 1_790_000_000
SPEED_CAPS = 1048623
OTHER_SPEED_CAPS = 1048591


def assert_no_secrets(payload: Any) -> None:
    """Fail if any fake secret value appears anywhere in ``payload``."""
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    for secret in FAKE_SECRETS:
        assert secret not in text, f'secret leaked: {secret}'


# ---------------------------------------------------------------------------
# Device payloads
# ---------------------------------------------------------------------------


def fake_port(idx: int, *, up: bool = True, speed: int = 10000, **over: Any) -> dict[str, Any]:
    """Return one ``port_table`` entry."""
    entry: dict[str, Any] = {
        'port_idx': idx,
        'name': f'Port {idx}',
        'media': 'GE',
        'speed': speed if up else 0,
        'full_duplex': True,
        'autoneg': True,
        'up': up,
        'enable': True,
        'is_uplink': False,
        'stp_state': 'forwarding' if up else 'disabled',
        'forward': 'native',
        'portconf_id': PROF_AUTO,
        'native_networkconf_id': NET_MGMT,
        'speed_caps': SPEED_CAPS,
        'port_poe': False,
        'rx_bytes': 1000 * idx,
        'tx_bytes': 2000 * idx,
        'rx_packets': 10 * idx,
        'tx_packets': 20 * idx,
        'rx_errors': 0,
        'tx_errors': 0,
        'rx_dropped': 0,
        'tx_dropped': 0,
        'rx_broadcast': 1,
        'tx_broadcast': 2,
        'rx_multicast': 3,
        'tx_multicast': 4,
        'link_down_count': 0,
    }
    entry.update(over)
    return entry


def fake_port_5(**over: Any) -> dict[str, Any]:
    """Return the port under test: up at 5000 although the override asks for 10G."""
    entry = fake_port(
        5,
        speed=5000,
        op_mode='switch',
        flowctrl_rx=False,
        flowctrl_tx=False,
        satisfaction=100,
        port_stats={'rx_crc_errors': 3, 'rx_pause_frames': 0},
        link_down_count=2,
        rx_errors=7,
        x_port_secret=FAKE_PORT_SECRET,
        last_connection={
            'connected': True,
            'mac': NAS_MAC,
            'ip': NAS_IP,
            'connected_at': NOW - 3600,
            'last_seen': NOW - 10,
        },
    )
    entry.update(over)
    return entry


def fake_switch(**over: Any) -> dict[str, Any]:
    """Return a ``stat/device`` record for the switch under test."""
    device: dict[str, Any] = {
        '_id': SWITCH_ID,
        'mac': SWITCH_MAC,
        'ip': SWITCH_IP,
        'name': SWITCH_NAME,
        'model': 'USFXG',
        'type': 'usw',
        'serial': SERIAL,
        'adopted': True,
        'version': '7.0.0.10000',
        'upgradable': True,
        'upgrade_to_firmware': '7.0.1.10001',
        'uptime': 86400,
        'state': 1,
        'last_seen': NOW - 20,
        'system-stats': {'cpu': '7.1', 'mem': '41.2', 'uptime': '86400'},
        'sys_stats': {'loadavg_1': '0.11', 'mem_total': 1000, 'mem_used': 400},
        # Fixture-only names: the collector captures thermal/power keys generically.
        'fixture_board_temp_c': 48.5,
        'fixture_power_budget_w': 12.0,
        'x_authkey': FAKE_AUTHKEY,
        'uplink': {'uplink_mac': PEER_MAC, 'uplink_remote_port': 9, 'port_idx': 2},
        'port_overrides': [
            {
                'port_idx': 5,
                'portconf_id': PROF_10G,
                'name': 'NAS 10G',
                'setting_preference': 'auto',
            },
            {'port_idx': 2, 'portconf_id': PROF_TRUNK, 'name': 'Uplink'},
        ],
        'port_table': [
            fake_port(1),
            fake_port(2, portconf_id=PROF_TRUNK, forward='all', is_uplink=True),
            fake_port(3),
            fake_port(4, up=False, speed_caps=OTHER_SPEED_CAPS),
            fake_port_5(),
        ],
        'lldp_table': [
            {
                'local_port_idx': 2,
                'chassis_id': PEER_MAC.upper(),
                'port_id': 'Port 9',
                'system_name': '',
                'is_wired': True,
            }
        ],
        'mac_table': [
            {'mac': NAS_MAC, 'port_idx': 5, 'vlan': 255, 'static': False, 'age': 3},
            {'mac': PEER_MAC, 'port_idx': 2, 'vlan': 1, 'static': False, 'age': 1},
        ],
    }
    device.update(over)
    return device


def fake_other_switch() -> dict[str, Any]:
    """A second Flex XG whose name contains the first switch's whole name."""
    return {
        '_id': OTHER_SWITCH_ID,
        'mac': OTHER_SWITCH_MAC,
        'ip': OTHER_SWITCH_IP,
        'name': OTHER_SWITCH_NAME,
        'model': 'USFXG',
        'type': 'usw',
        'state': 1,
        'x_authkey': FAKE_AUTHKEY,
        'port_overrides': [{'port_idx': 1, 'portconf_id': PROF_10G}],
        'port_table': [fake_port(1), fake_port(3, up=False)],
    }


def fake_peer() -> dict[str, Any]:
    """An adopted gateway, the LLDP peer on port 2."""
    return {
        '_id': PEER_ID,
        'mac': PEER_MAC,
        'ip': PEER_IP,
        'name': 'Test Gateway',
        'model': 'UDMPROMAX',
        'type': 'udm',
        'state': 1,
    }


def fake_devices() -> list[dict[str, Any]]:
    """Every adopted device on the fake site."""
    return [fake_switch(), fake_other_switch(), fake_peer()]


def fake_portconf() -> list[dict[str, Any]]:
    """Port profiles. The 10Gbps and Auto pair differ only in invented negotiation keys."""
    return [
        {
            '_id': PROF_10G,
            'name': PROFILE_10G_NAME,
            'site_id': 'fake-site',
            'forward': 'native',
            'native_networkconf_id': NET_MGMT,
            'tagged_networkconf_ids': [],
            'excluded_networkconf_ids': [NET_GUEST],
            'autoneg': False,
            'speed': 10000,
            'full_duplex': True,
            'poe_mode': 'off',
            'stp_port_mode': True,
            'attr_no_delete': False,
            'x_pw_test': FAKE_PW,
        },
        {
            '_id': PROF_AUTO,
            'name': PROFILE_AUTO_NAME,
            'site_id': 'fake-site',
            'forward': 'native',
            'native_networkconf_id': NET_MGMT,
            'tagged_networkconf_ids': [],
            'excluded_networkconf_ids': [NET_GUEST],
            'autoneg': True,
            'full_duplex': True,
            'poe_mode': 'off',
            'stp_port_mode': True,
            'attr_hidden_id': 'fixture',
        },
        {'_id': PROF_TRUNK, 'name': 'All', 'site_id': 'fake-site', 'forward': 'all'},
    ]


def fake_networkconf() -> list[dict[str, Any]]:
    """Networks, one carrying a passphrase that must be stripped."""
    return [
        {
            '_id': NET_MGMT,
            'name': 'Management',
            'vlan': 255,
            'ip_subnet': '203.0.113.1/24',
            'dhcpd_enabled': True,
            'dhcpd_start': '203.0.113.100',
            'dhcpd_stop': '203.0.113.200',
            'enabled': True,
            'x_passphrase': FAKE_PASSPHRASE,
        },
        {'_id': NET_GUEST, 'name': 'Guest', 'vlan': 30, 'ip_subnet': '198.51.100.1/24'},
    ]


# ---------------------------------------------------------------------------
# Client payloads
# ---------------------------------------------------------------------------


def fake_sta() -> list[dict[str, Any]]:
    """``stat/sta``: the NAS on switch port 5, plus an unrelated client."""
    return [
        {
            'mac': NAS_MAC,
            'hostname': 'ugreen-nas',
            'name': 'UGREEN NAS',
            'ip': NAS_IP,
            'sw_mac': SWITCH_MAC,
            'sw_port': 5,
            'sw_depth': 1,
            'is_wired': True,
            'network': 'Management',
            'vlan': 255,
            'uptime': 3600,
            'first_seen': NOW - 30 * 86400,
            'last_seen': NOW - 5,
            'oui': 'Fake Vendor',
        },
        {
            'mac': OTHER_CLIENT_MAC,
            'hostname': 'other-host',
            'ip': '203.0.113.61',
            'sw_mac': OTHER_SWITCH_MAC,
            'sw_port': 3,
            'is_wired': True,
        },
    ]


def fake_v2_active() -> list[dict[str, Any]]:
    """v2 ``clients/active``: carries the negotiated wire rate."""
    return [
        {
            'mac': NAS_MAC,
            'uplink_mac': SWITCH_MAC,
            'sw_port': 5,
            'wired_rate_mbps': 5000,
            'ip': NAS_IP,
            'network_name': 'Management',
            'vlan': 255,
            'type': 'WIRED',
            'is_wired': True,
            'last_seen': NOW - 5,
        }
    ]


def fake_v2_history() -> list[dict[str, Any]]:
    """v2 ``clients/history``: the NAS's second interface, last seen on port 3."""
    return [
        {
            'mac': NAS_MAC_2,
            'hostname': 'ugreen-nas-eth1',
            'last_uplink_mac': SWITCH_MAC,
            'last_uplink_name': SWITCH_NAME,
            'sw_port': 3,
            'wired_rate_mbps': 5000,
            'is_wired': True,
            'last_seen': NOW - 5 * 3600,
        }
    ]


def fake_users() -> list[dict[str, Any]]:
    """``rest/user``: historical client names."""
    return [
        {
            'mac': NAS_MAC,
            'name': 'UGREEN NAS',
            'hostname': 'ugreen-nas',
            'oui': 'Fake Vendor',
            'fixed_ip': NAS_IP,
            'use_fixedip': True,
        },
        {'mac': NAS_MAC_2, 'hostname': 'ugreen-nas-eth1'},
    ]


def fake_stat_user(mac: str) -> dict[str, Any]:
    """``stat/user/{mac}``."""
    return {
        'meta': {'rc': 'ok'},
        'data': [{'mac': mac, 'first_seen': NOW - 30 * 86400, 'last_seen': NOW - 5}],
    }


# ---------------------------------------------------------------------------
# History payloads
# ---------------------------------------------------------------------------


def fake_events() -> list[dict[str, Any]]:
    """``stat/event`` records, newest first, mixing ms and s timestamps."""
    return [
        {
            '_id': 'ev01',
            'key': 'EVT_SW_PoeDisconnect',
            'sw': SWITCH_MAC,
            'sw_name': SWITCH_NAME,
            'port': 5,
            'time': (NOW - 600) * 1000,
            'msg': f'Switch[{SWITCH_NAME}] PoE disconnect',
            'x_internal': FAKE_EVENT_SECRET,
        },
        {
            '_id': 'ev02',
            'key': 'EVT_SW_Connected',
            'sw': OTHER_SWITCH_MAC,
            'sw_name': OTHER_SWITCH_NAME,
            'time': (NOW - 500) * 1000,
            'msg': f'Switch[{OTHER_SWITCH_NAME}] was connected',
        },
        {
            '_id': 'ev03',
            'key': 'EVT_SW_Lldp',
            'sw': SWITCH_MAC,
            'time': NOW - 400,
            'msg': 'Port 15 link down',
        },
        {
            '_id': 'ev04',
            'key': 'EVT_LU_Disconnected',
            'user': NAS_MAC,
            'time': (NOW - 300) * 1000,
            'msg': 'User disconnected',
        },
        {
            '_id': 'ev05',
            'key': 'EVT_AP_Connected',
            'ap': '02:00:00:00:00:99',
            'time': (NOW - 200) * 1000,
            'msg': 'AP was connected',
        },
    ]


def fake_alarms() -> list[dict[str, Any]]:
    """``list/alarm``: one about the switch, one in the past beyond any window."""
    return [
        {
            '_id': 'al01',
            'key': 'EVT_SW_Lost_Contact',
            'sw': SWITCH_MAC,
            'time': (NOW - 7200) * 1000,
            'msg': f'Switch[{SWITCH_NAME}] was disconnected',
            'archived': True,
        },
        {
            '_id': 'al02',
            'key': 'EVT_SW_Lost_Contact',
            'sw': SWITCH_MAC,
            'time': (NOW - 800 * 86400) * 1000,
            'msg': 'very old alarm',
        },
    ]


def fake_system_log(log_class: str) -> dict[str, Any]:
    """v2 ``system-log/{class}`` page."""
    data: list[dict[str, Any]] = []
    if log_class == 'admin-activity':
        data = [
            {
                'id': 'sl01',
                'timestamp': (NOW - 3000) * 1000,
                'key': 'ADMIN_CHANGED_DEVICE',
                'title': 'Port 5 profile changed',
                'parameters': {'device': {'mac': SWITCH_MAC, 'name': SWITCH_NAME}},
            }
        ]
    elif log_class == 'device-alert':
        data = [
            {
                'id': 'sl02',
                'timestamp': (NOW - 100) * 1000,
                'key': 'DEVICE_PORT_SPEED',
                'message': 'Port 5 negotiated 5 Gbps',
                'device': {'mac': SWITCH_MAC},
            }
        ]
    return {'data': data, 'pageNumber': 0, 'pageSize': 100, 'totalElements': len(data)}


def fake_sysinfo() -> dict[str, Any]:
    """``stat/sysinfo``."""
    return {
        'meta': {'rc': 'ok'},
        'data': [
            {
                'version': '10.0.162',
                'build': 'atag_10.0.162_00000',
                'timezone': 'UTC',
                'hostname': 'fake-console',
                'x_console_token': FAKE_TOKEN,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Integration API payloads
# ---------------------------------------------------------------------------

INTEGRATION_SITE_ID = '00000000-0000-0000-0000-0000000000f1'
INTEGRATION_DEVICE_ID = '00000000-0000-0000-0000-0000000000f2'


def integration_routes(base: str = '/proxy/network/integrations') -> dict:
    """Routes for an Integration API that only answers on ``base``."""
    return {
        ('GET', rf'^{base}/v1/info$'): {'applicationVersion': '10.0.162'},
        ('GET', rf'^{base}/v1/sites$'): {
            'data': [{'id': INTEGRATION_SITE_ID, 'internalReference': SITE, 'name': 'Default'}]
        },
        ('GET', rf'^{base}/v1/sites/{INTEGRATION_SITE_ID}/devices$'): {
            'offset': 0,
            'limit': 200,
            'count': 1,
            'totalCount': 1,
            'data': [{'id': INTEGRATION_DEVICE_ID, 'macAddress': SWITCH_MAC.upper()}],
        },
        ('GET', rf'^{base}/v1/sites/{INTEGRATION_SITE_ID}/devices/{INTEGRATION_DEVICE_ID}$'): {
            'id': INTEGRATION_DEVICE_ID,
            'macAddress': SWITCH_MAC.upper(),
            'interfaces': {
                'ports': [
                    {
                        'idx': 5,
                        'state': 'UP',
                        'connector': 'RJ45',
                        'maxSpeedMbps': 10000,
                        'speedMbps': 5000,
                    }
                ]
            },
        },
        (
            'GET',
            rf'^{base}/v1/sites/{INTEGRATION_SITE_ID}/devices/{INTEGRATION_DEVICE_ID}/statistics/latest$',
        ): fake_statistics_latest(),
    }


def fake_statistics_latest() -> dict[str, Any]:
    """``.../devices/{id}/statistics/latest`` for a switch, in the shape the live endpoint sends.

    The keys are those a USW Flex answered with on 2026-10-15 (issue 081); a switch has no
    radios, so ``interfaces`` is an empty object.
    """
    return {
        'uptimeSec': 86400,
        'lastHeartbeatAt': '2026-09-21T14:13:00Z',
        'nextHeartbeatAt': '2026-09-21T14:14:17Z',
        'cpuUtilizationPct': 7.1,
        'memoryUtilizationPct': 41.2,
        'uplink': {'txRateBps': 0, 'rxRateBps': 0},
        'interfaces': {},
    }


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class FakeResponse:
    """The subset of ``requests.Response`` the client code uses."""

    def __init__(self, status_code: int, payload: Any) -> None:
        """Wrap ``payload`` with an HTTP status."""
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self) -> Any:
        """Return a deep copy so callers cannot mutate the fixture."""
        if isinstance(self._payload, str):
            raise ValueError('not JSON')
        return copy.deepcopy(self._payload)

    def raise_for_status(self) -> None:
        """Raise like requests does for 4xx/5xx."""
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code} Error', response=self)


Route = Any  # payload, (status, payload), or callable(**request) -> either


class FakeSession:
    """An in-memory session that answers from a route table and records every call.

    ``routes`` maps ``(METHOD, path_regex)`` to a payload, a ``(status, payload)``
    tuple, or a callable receiving ``method``, ``path``, ``params`` and ``json``.
    Unknown routes answer 404, so a missing fixture shows up as a recorded error.
    Any write verb fails the test outright.
    """

    def __init__(self, routes: dict[tuple[str, str], Route]) -> None:
        """Compile the route table."""
        self.routes = [(m, re.compile(p), v) for (m, p), v in routes.items()]
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        self.verify = False
        self.closed = False

    def _respond(
        self, method: str, url: str, params: Optional[dict] = None, body: Any = None
    ) -> FakeResponse:
        path = urlsplit(url).path
        self.calls.append(
            {'method': method, 'url': url, 'path': path, 'params': params, 'json': body}
        )
        for route_method, pattern, value in self.routes:
            if route_method == method and pattern.search(path):
                if callable(value):
                    value = value(method=method, path=path, params=params, json=body)
                if isinstance(value, tuple):
                    return FakeResponse(value[0], value[1])
                return FakeResponse(200, value)
        return FakeResponse(404, {'meta': {'rc': 'error', 'msg': 'api.err.NotFound'}})

    def get(self, url: str, params: Optional[dict] = None, **_: Any) -> FakeResponse:
        """Answer a GET."""
        return self._respond('GET', url, params=params)

    def head(self, url: str, **_: Any) -> FakeResponse:
        """Answer a HEAD."""
        return self._respond('HEAD', url)

    def post(self, url: str, data: Any = None, json: Any = None, **_: Any) -> FakeResponse:
        """Answer a POST query."""
        return self._respond('POST', url, body=json if json is not None else data)

    def _write(self, method: str, url: str) -> FakeResponse:
        self.calls.append({'method': method, 'url': url, 'path': urlsplit(url).path})
        raise AssertionError(f'{method} {url} reached the transport: writes must be impossible')

    def put(self, url: str, *_: Any, **__: Any) -> FakeResponse:
        """Fail: a write reached the transport."""
        return self._write('PUT', url)

    def patch(self, url: str, *_: Any, **__: Any) -> FakeResponse:
        """Fail: a write reached the transport."""
        return self._write('PATCH', url)

    def delete(self, url: str, *_: Any, **__: Any) -> FakeResponse:
        """Fail: a write reached the transport."""
        return self._write('DELETE', url)

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        """Dispatch an arbitrary-method request."""
        if method.upper() in ('PUT', 'PATCH', 'DELETE'):
            return self._write(method.upper(), url)
        return self._respond(
            method.upper(), url, params=kwargs.get('params'), body=kwargs.get('json')
        )

    def close(self) -> None:
        """Record that the session was closed."""
        self.closed = True

    def paths(self, method: Optional[str] = None) -> list[str]:
        """Return the paths requested, optionally for one method."""
        return [c['path'] for c in self.calls if method is None or c['method'] == method]


def paged_events(records: list[dict[str, Any]], page_size: int = 1000) -> Callable[..., Any]:
    """Return a ``stat/event`` route that honours ``_start`` / ``_limit``."""

    def route(json: Optional[dict] = None, **_: Any) -> dict[str, Any]:
        body = json or {}
        start = int(body.get('_start', 0))
        limit = int(body.get('_limit', page_size))
        return {'meta': {'rc': 'ok'}, 'data': records[start : start + limit]}

    return route


def default_routes(**overrides: Route) -> dict[tuple[str, str], Route]:
    """Every route a full diagnostic bundle needs. Keyword overrides replace by name."""
    devices = fake_devices()
    named: dict[str, tuple[tuple[str, str], Route]] = {
        'devices': (('GET', rf'^{API_RE}/stat/device$'), {'data': devices}),
        'device': (('GET', rf'^{API_RE}/stat/device/{SWITCH_ID}$'), {'data': [fake_switch()]}),
        'other_device': (
            ('GET', rf'^{API_RE}/stat/device/{OTHER_SWITCH_ID}$'),
            {'data': [fake_other_switch()]},
        ),
        'sysinfo': (('GET', rf'^{API_RE}/stat/sysinfo$'), fake_sysinfo()),
        'models': (('GET', rf'^{V2_RE}/models$'), (404, {'error': 'not found'})),
        'portconf': (('GET', rf'^{API_RE}/rest/portconf$'), {'data': fake_portconf()}),
        'networkconf': (('GET', rf'^{API_RE}/rest/networkconf$'), {'data': fake_networkconf()}),
        'sta': (('GET', rf'^{API_RE}/stat/sta$'), {'data': fake_sta()}),
        'users': (('GET', rf'^{API_RE}/rest/user$'), {'data': fake_users()}),
        'v2_active': (('GET', rf'^{V2_RE}/clients/active$'), fake_v2_active()),
        'v2_history': (('GET', rf'^{V2_RE}/clients/history$'), fake_v2_history()),
        'stat_user': (
            ('GET', rf'^{API_RE}/stat/user/'),
            lambda path, **_: fake_stat_user(path.rsplit('/', 1)[-1]),
        ),
        'events': (('POST', rf'^{API_RE}/stat/event$'), paged_events(fake_events())),
        'alarms': (('GET', rf'^{API_RE}/list/alarm$'), {'data': fake_alarms()}),
        'system_log': (
            ('POST', rf'^{V2_RE}/system-log/'),
            lambda path, **_: fake_system_log(path.rsplit('/', 1)[-1]),
        ),
    }
    for name, value in overrides.items():
        if name not in named:
            raise KeyError(f'unknown route {name!r}')
        named[name] = (named[name][0], value)
    routes: dict[tuple[str, str], Route] = dict(named.values())
    routes.update(integration_routes())
    return routes


def fake_client(
    session: FakeSession, *, unifi_os: bool = True, auth: str = 'token'
) -> UnifiApiClient:
    """Return a real ``UnifiApiClient`` wired to ``session``, already 'logged in'.

    Exercises the real request code (``get_devices``, ``get_device_details``,
    ``get_lldp_info``) without sockets. ``login()`` is never called.
    """
    client = UnifiApiClient(base_url=BASE_URL, site=SITE, api_token=FAKE_TOKEN, max_retries=1)
    client.is_authenticated = True
    client.is_unifi_os = unifi_os
    client.auth_method = auth
    client.session = session
    return client
