"""Load STP-optimizer overrides from a YAML file.

Path (in order of precedence):

1. ``$UNIFI_STP_OVERRIDES`` environment variable (absolute path).
2. ``~/.config/unifi_network_mapper/stp_overrides.yaml``.

Schema::

    # Force-promote these MACs to Tier 0 / root-eligible.  The root
    # guard still refuses to lower their priority below 4096 if they
    # are not AGGREGATION or CORE_DISTRIBUTION class.
    root_eligible_macs:
      - 02:00:fe:02:00:09
      - 78:45:58:62:f1:4a

    # Force-demote these MACs: they will never be assigned priority
    # below STP_PRIORITY_DISTRIBUTION (8192) even if gateway-
    # connected.  Useful when an access switch happens to be cabled
    # directly to the gateway for convenience.
    force_access_macs:
      - 02:00:fe:02:00:13

All MACs are normalised to lowercase without separators before
comparison.
"""

from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


def _normalise_mac(mac: str) -> str:
    return mac.strip().lower().replace(':', '').replace('-', '').replace('.', '')


@dataclass(frozen=True)
class STPOverrides:
    """Resolved STP overrides.

    Both sets hold canonicalised (lowercase, separator-free) MACs.
    """

    root_eligible_macs: frozenset[str] = field(default_factory=lambda: frozenset[str]())
    force_access_macs: frozenset[str] = field(default_factory=lambda: frozenset[str]())
    source_path: Path | None = None

    def is_root_eligible_override(self, mac: str) -> bool:
        """Return True if MAC is in the root-eligible override list."""
        return _normalise_mac(mac) in self.root_eligible_macs

    def is_force_access(self, mac: str) -> bool:
        """Return True if MAC is in the forced-access override list."""
        return _normalise_mac(mac) in self.force_access_macs


def _default_path() -> Path:
    env = os.environ.get('UNIFI_STP_OVERRIDES')
    if env:
        return Path(env).expanduser()
    return Path.home() / '.config' / 'unifi_network_mapper' / 'stp_overrides.yaml'


def _coerce_mac_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[Any], value)
    return [str(item) for item in items if item]


def load_stp_overrides(path: Path | None = None) -> STPOverrides:
    """Load STP overrides from YAML, returning empty overrides if absent."""
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

    root_eligible = frozenset(
        _normalise_mac(m) for m in _coerce_mac_list(data.get('root_eligible_macs'))
    )
    force_access = frozenset(
        _normalise_mac(m) for m in _coerce_mac_list(data.get('force_access_macs'))
    )

    return STPOverrides(
        root_eligible_macs=root_eligible,
        force_access_macs=force_access,
        source_path=target,
    )
