"""`get_device_inventory` and `get_firmware_drift`: the MCP side of `inventory list` and
`inventory firmware-skew` (issues 017 and 078).

The pure core (`categorize_devices`, `find_firmware_skew`, `firmware_drift`) is tested on
fixtures; the two handlers run against a fake ``UniFiClient`` so no controller is needed.
``inventory_cli`` keeps its names as re-exports so the CLI and its tests are unchanged.
"""

import pytest
from typing import Any
from unifi_mapper.analysis import device_inventory
from unifi_mapper.analysis.device_inventory import (
    categorize_devices,
    find_firmware_skew,
    firmware_drift,
    get_device_inventory,
    get_firmware_drift,
    version_key,
)


DEVICES: list[dict[str, Any]] = [
    {
        '_id': 'a1',
        'name': 'Rack Switch',
        'model': 'USW-Pro-24-PoE',
        'model_name': 'USW Pro 24 PoE',
        'type': 'usw',
        'version': '7.1.26',
        'ip': '192.0.2.10',
        'mac': '02:00:00:00:00:10',
        'adopted': True,
        'state': 1,
        'uptime': 100,
        'upgradable': True,
        'upgrade_to_firmware': '7.2.2',
    },
    {
        '_id': 'a2',
        'name': 'Desk Switch',
        'model': 'USW-Pro-24-PoE',
        'type': 'usw',
        'version': '7.2.2',
        'ip': '192.0.2.11',
        'mac': '02:00:00:00:00:11',
        'adopted': True,
        'state': 1,
    },
    {
        '_id': 'a3',
        'name': 'Garage Switch',
        'model': 'USW-Pro-24-PoE',
        'type': 'usw',
        'version': '7.1.26',
        'ip': '192.0.2.12',
        'mac': '02:00:00:00:00:12',
        'adopted': True,
        'state': 0,
    },
    {
        '_id': 'b1',
        'name': 'Hall AP',
        'model': 'U6-Pro',
        'type': 'uap',
        'version': '6.6.65',
        'ip': '192.0.2.20',
        'mac': '02:00:00:00:00:20',
        'adopted': True,
        'state': 1,
    },
    {
        '_id': 'c1',
        'name': 'Gateway',
        'model': 'UDM-Pro',
        'type': 'udm',
        'version': '4.0.6',
        'ip': '192.0.2.1',
        'mac': '02:00:00:00:00:01',
        'adopted': True,
        'state': 1,
    },
    {'_id': 'd1', 'model': 'UNKNOWN-1', 'type': 'uxg?', 'version': '1.0.0'},
]


class FakeClient:
    """A ``UniFiClient`` stand-in that serves the fixture devices."""

    def __init__(self, devices: list[dict[str, Any]] | None = None) -> None:
        self.devices = DEVICES if devices is None else devices

    async def __aenter__(self) -> 'FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_devices(self) -> list[dict[str, Any]]:
        return self.devices


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device_inventory, 'UniFiClient', FakeClient)


# --- the pure core --------------------------------------------------------------------------


def test_categorize_devices_groups_by_type_and_sorts_by_name() -> None:
    categorized = categorize_devices(DEVICES)
    assert set(categorized) == {'firewall', 'switch', 'ap', 'other'}
    assert [d['name'] for d in categorized['switch']] == [
        'Desk Switch',
        'Garage Switch',
        'Rack Switch',
    ]
    assert [d['name'] for d in categorized['ap']] == ['Hall AP']
    assert [d['name'] for d in categorized['firewall']] == ['Gateway']
    assert categorized['other'][0]['name'] == 'Unnamed'
    rack = categorized['switch'][2]
    assert rack['type'] == 'switch' and rack['raw_type'] == 'usw'
    assert rack['upgradable'] is True and rack['upgrade_to_firmware'] == '7.2.2'


def test_find_firmware_skew_is_unchanged_and_re_exported() -> None:
    from unifi_mapper import inventory_cli

    assert inventory_cli.find_firmware_skew is find_firmware_skew
    assert inventory_cli.get_device_type is device_inventory.get_device_type
    skew = find_firmware_skew(categorize_devices(DEVICES), {'switch'})
    assert skew == {
        'USW-Pro-24-PoE': {'7.1.26': ['Garage Switch', 'Rack Switch'], '7.2.2': ['Desk Switch']}
    }


def test_version_key_orders_numeric_versions_and_tolerates_text() -> None:
    assert sorted(['7.2.2', '7.1.26', '7.10.0'], key=version_key) == ['7.1.26', '7.2.2', '7.10.0']
    assert version_key('Unknown') < version_key('1.0.0')


def test_firmware_drift_names_the_fleet_newest_and_the_devices_behind() -> None:
    report = firmware_drift(categorize_devices(DEVICES), {'all'}, timestamp='t')
    assert report.devices_analyzed == 6
    assert report.models_with_skew == 1
    (model,) = report.models
    assert model.model == 'USW-Pro-24-PoE'
    assert model.fleet_newest == '7.2.2'
    assert model.devices_behind == ['Garage Switch', 'Rack Switch']
    assert model.versions == {'7.1.26': ['Garage Switch', 'Rack Switch'], '7.2.2': ['Desk Switch']}
    assert report.model_dump(mode='json')['upgradable'] == [
        {'device': 'Rack Switch', 'offered': '7.2.2'}
    ]
    assert report.offline == ['Garage Switch', 'Unnamed']  # no state field counts as offline
    assert any('Garage Switch' in r for r in report.recommendations)


def test_firmware_drift_filters_by_device_type() -> None:
    assert firmware_drift(categorize_devices(DEVICES), 'ap', timestamp='t').models == []
    assert (
        firmware_drift(categorize_devices(DEVICES), 'switch', timestamp='t').models_with_skew == 1
    )


# --- the handlers -----------------------------------------------------------------------------


async def test_get_device_inventory_reports_counts_devices_and_summaries(
    fake_client: None,
) -> None:
    report = await get_device_inventory()
    assert report.device_type == 'all'
    assert report.total == 6
    assert report.counts == {'firewall': 1, 'switch': 3, 'ap': 1, 'other': 1}
    assert [d.name for d in report.devices][:3] == ['Gateway', 'Desk Switch', 'Garage Switch']
    garage = next(d for d in report.devices if d.name == 'Garage Switch')
    assert garage.online is False and garage.type == 'switch'
    assert report.firmware_summary['switch'] == {'7.1.26': 2, '7.2.2': 1}
    assert report.model_summary['switch'] == {'USW-Pro-24-PoE': 3}


async def test_get_device_inventory_filters_by_type(fake_client: None) -> None:
    report = await get_device_inventory('ap')
    assert report.device_type == 'ap'
    assert [d.name for d in report.devices] == ['Hall AP']
    assert report.counts == {'firewall': 1, 'switch': 3, 'ap': 1, 'other': 1}  # the site's counts
    assert set(report.firmware_summary) == {'ap'}


async def test_get_firmware_drift_runs_on_the_client(fake_client: None) -> None:
    report = await get_firmware_drift('switch')
    assert report.device_type == 'switch'
    assert report.models_with_skew == 1
    assert report.models[0].fleet_newest == '7.2.2'


def test_an_upgrade_with_no_named_version_is_offered_as_available() -> None:
    devices = [{**DEVICES[0], 'upgrade_to_firmware': ''}]
    report = firmware_drift(categorize_devices(devices), {'all'}, timestamp='t')
    assert [(o.device, o.offered) for o in report.upgradable] == [('Rack Switch', 'available')]


async def test_the_handlers_build_output_schemas() -> None:
    from unifi_mapper.mcp.catalog import build_tool
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    registry = ToolRegistry(default_manifests_dir(), strict=True)
    for name, handler in (
        ('get_device_inventory', get_device_inventory),
        ('get_firmware_drift', get_firmware_drift),
    ):
        meta = registry.get_metadata(name)
        assert meta is not None and meta.cli.startswith('inventory ')
        tool = build_tool(handler, meta)
        assert tool.output_schema is not None
        assert tool.parameters['properties']['device_type']['enum'][0] == 'all'
