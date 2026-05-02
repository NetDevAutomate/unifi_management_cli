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
