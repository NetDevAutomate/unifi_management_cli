"""Tests for inventory firmware skew helpers."""

from __future__ import annotations

from unifi_mapper.inventory_cli import find_firmware_skew


def test_find_firmware_skew_groups_mixed_versions_by_model() -> None:
    """Models with multiple firmware versions should be reported."""
    categorized = {
        'switch': [
            {'name': 'Switch A', 'model': 'USW-Flex-XG', 'version': '7.0.1'},
            {'name': 'Switch B', 'model': 'USW-Flex-XG', 'version': '7.0.2'},
            {'name': 'Switch C', 'model': 'USW-Lite-8-PoE', 'version': '6.6.1'},
        ],
        'ap': [
            {'name': 'AP A', 'model': 'U6-Pro', 'version': '6.6.77'},
            {'name': 'AP B', 'model': 'U6-Pro', 'version': '6.6.77'},
        ],
        'firewall': [],
        'other': [],
    }

    skew = find_firmware_skew(categorized, {'switch'})

    assert skew == {
        'USW-Flex-XG': {
            '7.0.1': ['Switch A'],
            '7.0.2': ['Switch B'],
        }
    }


def test_firmware_skew_json_prints_the_drift_report(monkeypatch) -> None:
    """``--json`` prints the ``get_firmware_drift`` shape for the same filter (issue 017)."""
    import json
    from typer.testing import CliRunner
    from unifi_mapper import inventory_cli

    class _Client:
        def logout(self) -> None:
            return None

    categorized = {
        'firewall': [],
        'switch': [
            {'name': 'A', 'model': 'USW-24', 'version': '7.1.26', 'state': 1, 'upgradable': False},
            {'name': 'B', 'model': 'USW-24', 'version': '7.2.2', 'state': 1, 'upgradable': False},
        ],
        'ap': [],
        'other': [],
    }
    monkeypatch.setattr(inventory_cli, 'get_api_client', lambda config_path=None: (_Client(), 's'))
    monkeypatch.setattr(inventory_cli, 'fetch_and_categorize_devices', lambda _c, _s: categorized)
    result = CliRunner().invoke(
        inventory_cli.inventory_app, ['firmware-skew', '--filter', 'switch', '--json']
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report['device_type'] == 'switch'
    assert report['models'][0]['fleet_newest'] == '7.2.2'
    assert report['models'][0]['devices_behind'] == ['A']
