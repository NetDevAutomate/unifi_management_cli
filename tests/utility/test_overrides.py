"""Tests for STP overrides loader."""

from __future__ import annotations

from pathlib import Path
from unifi_mapper.core.utils.overrides import (
    STPOverrides,
    load_stp_overrides,
)


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """Missing override file yields empty overrides, never raises."""
    target = tmp_path / 'does_not_exist.yaml'
    result = load_stp_overrides(target)
    assert isinstance(result, STPOverrides)
    assert result.root_eligible_macs == frozenset()
    assert result.force_access_macs == frozenset()
    assert result.source_path is None


def test_valid_file_round_trip(tmp_path: Path) -> None:
    """Valid YAML populates both sets and normalises MAC formatting."""
    target = tmp_path / 'stp_overrides.yaml'
    target.write_text(
        '\n'.join(
            [
                'root_eligible_macs:',
                '  - 02:00:fe:02:00:09',
                '  - aabb-ccdd-eeff',
                'force_access_macs:',
                '  - 02:00:fe:02:00:13',
            ]
        ),
        encoding='utf-8',
    )

    result = load_stp_overrides(target)

    assert result.is_root_eligible_override('02:00:fe:02:00:09')
    assert result.is_root_eligible_override('AA:BB:CC:DD:EE:FF')
    assert not result.is_root_eligible_override('00:00:00:00:00:00')
    assert result.is_force_access('02-00-fe-02-00-13')
    assert not result.is_force_access('11:22:33:44:55:66')
    assert result.source_path == target


def test_malformed_yaml_returns_empty(tmp_path: Path) -> None:
    """Invalid YAML does not raise; overrides come back empty."""
    target = tmp_path / 'bad.yaml'
    target.write_text(': :\n  - broken', encoding='utf-8')
    result = load_stp_overrides(target)
    assert result.root_eligible_macs == frozenset()
    assert result.force_access_macs == frozenset()


def test_non_dict_root_returns_empty(tmp_path: Path) -> None:
    """Top-level list (not dict) yields empty overrides."""
    target = tmp_path / 'list.yaml'
    target.write_text('- 1\n- 2\n', encoding='utf-8')
    result = load_stp_overrides(target)
    assert result.root_eligible_macs == frozenset()


def test_non_list_values_ignored(tmp_path: Path) -> None:
    """Scalar values for MAC keys are coerced to empty lists."""
    target = tmp_path / 'mixed.yaml'
    target.write_text(
        'root_eligible_macs: not-a-list\nforce_access_macs: also-not-a-list\n',
        encoding='utf-8',
    )
    result = load_stp_overrides(target)
    assert result.root_eligible_macs == frozenset()
    assert result.force_access_macs == frozenset()
