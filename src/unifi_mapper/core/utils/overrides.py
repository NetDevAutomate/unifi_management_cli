"""Load STP optimizer overrides from YAML."""

from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


def normalise_mac(mac: str) -> str:
    """Return a lowercase MAC address without separators."""
    return mac.strip().lower().replace(':', '').replace('-', '').replace('.', '')


@dataclass(frozen=True)
class STPOverrides:
    """Resolved STP override sets.

    MAC addresses are stored lowercase without separators.
    """

    root_eligible_macs: frozenset[str] = field(default_factory=frozenset)
    force_access_macs: frozenset[str] = field(default_factory=frozenset)
    source_path: Path | None = None

    def is_root_eligible_override(self, mac: str) -> bool:
        """Return True if MAC is in the root-eligible override list."""
        return normalise_mac(mac) in self.root_eligible_macs

    def is_force_access(self, mac: str) -> bool:
        """Return True if MAC is in the forced-access override list."""
        return normalise_mac(mac) in self.force_access_macs


def _default_path() -> Path:
    env = os.environ.get('UNIFI_STP_OVERRIDES')
    if env:
        return Path(env).expanduser()
    return Path.home() / '.config' / 'unifi_management_cli' / 'stp_overrides.yaml'


def _coerce_mac_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[Any], value)
    return [str(item) for item in items if item]


def load_stp_overrides(path: Path | None = None) -> STPOverrides:
    """Load STP overrides, returning empty overrides when absent or invalid."""
    target = path or _default_path()
    if not target.exists():
        return STPOverrides(source_path=None)

    try:
        with target.open(encoding='utf-8') as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError:
        return STPOverrides(source_path=target)

    if not isinstance(raw, dict):
        return STPOverrides(source_path=target)

    data = cast(dict[str, Any], raw)
    return STPOverrides(
        root_eligible_macs=frozenset(
            normalise_mac(mac) for mac in _coerce_mac_list(data.get('root_eligible_macs'))
        ),
        force_access_macs=frozenset(
            normalise_mac(mac) for mac in _coerce_mac_list(data.get('force_access_macs'))
        ),
        source_path=target,
    )
