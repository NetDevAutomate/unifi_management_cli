"""Tests for STP override loading."""

from __future__ import annotations

import pytest
from pathlib import Path
from unifi_mapper.core.utils.overrides import STPOverrides, load_stp_overrides


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """Missing override file yields empty overrides."""
    result = load_stp_overrides(tmp_path / 'missing.yaml')

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
    """Invalid YAML does not raise."""
    target = tmp_path / 'bad.yaml'
    target.write_text(': :\n  - broken', encoding='utf-8')

    result = load_stp_overrides(target)

    assert result.root_eligible_macs == frozenset()
    assert result.force_access_macs == frozenset()


def test_non_dict_root_returns_empty(tmp_path: Path) -> None:
    """Top-level list yields empty overrides."""
    target = tmp_path / 'list.yaml'
    target.write_text('- 1\n- 2\n', encoding='utf-8')

    result = load_stp_overrides(target)

    assert result.root_eligible_macs == frozenset()


def test_non_list_values_are_ignored(tmp_path: Path) -> None:
    """Scalar values for MAC keys are ignored."""
    target = tmp_path / 'mixed.yaml'
    target.write_text(
        'root_eligible_macs: not-a-list\nforce_access_macs: also-not-a-list\n',
        encoding='utf-8',
    )

    result = load_stp_overrides(target)

    assert result.root_eligible_macs == frozenset()
    assert result.force_access_macs == frozenset()


# ─── Default location must track the project's config directory ───────────────


def test_default_overrides_path_lives_in_the_project_config_dir() -> None:
    """The default path must match where every other config file lives.

    It previously pointed at `~/.config/unifi_network_mapper/`, the project's old
    name, while prod.env is loaded from `~/.config/unifi_management_cli/`. An
    stp_overrides.yaml created in the documented directory was therefore read
    from a different one and silently ignored - a no-op with no error, which is
    the failure class this repo exists to catch.
    """
    from unifi_mapper.core.utils.overrides import _default_path

    path = _default_path()

    assert path.parent.name == 'unifi_management_cli'
    assert path.name == 'stp_overrides.yaml'
    assert 'unifi_network_mapper' not in str(path)


def test_overrides_path_env_var_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNIFI_STP_OVERRIDES overrides the default location."""
    from unifi_mapper.core.utils.overrides import _default_path

    monkeypatch.setenv('UNIFI_STP_OVERRIDES', '/tmp/custom-overrides.yaml')

    assert _default_path() == Path('/tmp/custom-overrides.yaml')
