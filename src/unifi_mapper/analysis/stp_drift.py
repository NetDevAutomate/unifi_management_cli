"""STP desired-state drift detection."""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.models.stp import STPTopology, SwitchSTPConfig


class STPIntentEntry(BaseModel):
    """Desired STP state for one switch."""

    priority: int | None = None
    root_expected: bool | None = None


class STPDriftFinding(BaseModel):
    """A single STP drift finding."""

    severity: str = 'WARNING'
    finding_type: str
    identifier: str
    message: str
    expected: object = None
    actual: object = None
    device_id: str | None = None
    device_name: str | None = None
    recommendation: str = ''


def _empty_drift_findings() -> list[STPDriftFinding]:
    return []


class STPDriftReport(BaseModel):
    """Report comparing desired STP intent against live topology."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_checked: int
    findings: list[STPDriftFinding] = Field(default_factory=_empty_drift_findings)

    @property
    def findings_count(self) -> int:
        """Number of drift findings."""
        return len(self.findings)

    @property
    def drift_detected(self) -> bool:
        """True when live STP state differs from intent."""
        return bool(self.findings)


STPIntentMapping = dict[str, STPIntentEntry | dict[str, object]]


def detect_stp_config_drift(
    topology: STPTopology,
    intent: STPIntentMapping,
) -> STPDriftReport:
    """Compare desired STP intent with live topology and return drift findings.

    Intent keys may be switch names, UniFi device IDs, or MAC addresses. Each
    value may contain ``priority`` and/or ``root_expected``.
    """
    normalized_intent = _normalize_intent(intent)
    switch_index = _index_switches(topology.switches)
    findings: list[STPDriftFinding] = []

    for identifier, expected in normalized_intent.items():
        switch = switch_index.get(_normalize_identifier(identifier))
        if switch is None:
            findings.append(_missing_device_finding(identifier, expected))
            continue

        if expected.priority is not None and switch.current_priority != expected.priority:
            findings.append(_priority_mismatch_finding(identifier, switch, expected.priority))

        if expected.root_expected is not None:
            is_live_root = _is_live_root(topology, switch)
            if is_live_root != expected.root_expected:
                findings.append(
                    _root_expected_mismatch_finding(
                        identifier,
                        switch,
                        expected.root_expected,
                        is_live_root,
                    )
                )

    return STPDriftReport(devices_checked=len(normalized_intent), findings=findings)


def load_stp_intent(path: str | Path) -> dict[str, STPIntentEntry]:
    """Load STP intent from YAML or JSON-like text.

    PyYAML is used when available. Without PyYAML, the fallback supports JSON,
    Python literal mappings, and a small YAML subset for hand-written mappings:

    ``device-name:`` followed by indented ``priority: 4096`` and/or
    ``root_expected: true`` lines.
    """
    text = Path(path).read_text(encoding='utf-8')
    data = _load_mapping_text(text)
    return _normalize_intent(data)


def _normalize_intent(intent: dict[str, Any]) -> dict[str, STPIntentEntry]:
    raw_intent = intent.get('devices', intent)
    if not isinstance(raw_intent, dict):
        raise ValueError('STP intent must be a mapping of device identifier to intent')
    raw_mapping = cast(dict[Any, Any], raw_intent)

    normalized: dict[str, STPIntentEntry] = {}
    for identifier, value in raw_mapping.items():
        if not isinstance(identifier, str):
            raise ValueError('STP intent device identifiers must be strings')
        if isinstance(value, STPIntentEntry):
            normalized[identifier] = value
            continue
        if not isinstance(value, dict):
            raise ValueError(f'STP intent for {identifier!r} must be a mapping')
        normalized[identifier] = STPIntentEntry(**cast(dict[str, Any], value))
    return normalized


def _load_mapping_text(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        yaml = None

    if yaml is not None:
        loaded = yaml.safe_load(text)
        return cast(dict[str, Any], loaded or {})

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        return cast(dict[str, Any], loaded)

    try:
        loaded = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return _parse_simple_yaml_mapping(text)
    if not isinstance(loaded, dict):
        raise ValueError('STP intent file must contain a mapping')
    return cast(dict[str, Any], loaded)


def _parse_simple_yaml_mapping(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    current_map: dict[str, object] | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split('#', maxsplit=1)[0].rstrip()
        if not line:
            continue
        if not raw_line.startswith((' ', '\t')):
            if ':' not in line:
                raise ValueError(f'Invalid intent line {line_number}: {raw_line!r}')
            key, value = line.split(':', maxsplit=1)
            current_key = key.strip().strip('"\'')
            if not current_key:
                raise ValueError(f'Invalid empty device identifier on line {line_number}')
            if value.strip():
                result[current_key] = _parse_scalar(value.strip())
                current_map = None
            else:
                current_map = {}
                result[current_key] = current_map
            continue

        if current_key is None or current_map is None:
            raise ValueError(f'Unexpected nested intent line {line_number}: {raw_line!r}')
        nested = line.strip()
        if ':' not in nested:
            raise ValueError(f'Invalid nested intent line {line_number}: {raw_line!r}')
        key, value = nested.split(':', maxsplit=1)
        current_map[key.strip()] = _parse_scalar(value.strip())

    if 'devices' in result and isinstance(result['devices'], dict):
        return result
    return result


def _parse_scalar(value: str) -> object:
    lowered = value.lower()
    if lowered in {'true', 'yes', 'on'}:
        return True
    if lowered in {'false', 'no', 'off'}:
        return False
    if lowered in {'null', 'none', '~', ''}:
        return None
    try:
        return int(value)
    except ValueError:
        return value.strip('"\'')


def _index_switches(switches: list[SwitchSTPConfig]) -> dict[str, SwitchSTPConfig]:
    index: dict[str, SwitchSTPConfig] = {}
    for switch in switches:
        for identifier in (switch.device_id, switch.name, switch.mac):
            normalized = _normalize_identifier(identifier)
            if normalized:
                index[normalized] = switch
    return index


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().casefold()


def _is_live_root(topology: STPTopology, switch: SwitchSTPConfig) -> bool:
    if topology.root_bridge_id:
        return switch.device_id == topology.root_bridge_id
    if topology.root_bridge_name:
        return switch.name == topology.root_bridge_name
    return switch.is_root_bridge


def _missing_device_finding(
    identifier: str,
    expected: STPIntentEntry,
) -> STPDriftFinding:
    return STPDriftFinding(
        severity='CRITICAL',
        finding_type='missing_device',
        identifier=identifier,
        expected=expected.model_dump(exclude_none=True),
        actual=None,
        message=f'No live STP switch matched intent identifier {identifier!r}.',
        recommendation='Confirm the device exists in discovery data or update the STP intent identifier.',
    )


def _priority_mismatch_finding(
    identifier: str,
    switch: SwitchSTPConfig,
    expected_priority: int,
) -> STPDriftFinding:
    return STPDriftFinding(
        finding_type='priority_mismatch',
        identifier=identifier,
        expected=expected_priority,
        actual=switch.current_priority,
        device_id=switch.device_id,
        device_name=switch.name,
        message=(
            f'{switch.name} bridge priority is {switch.current_priority}; '
            f'expected {expected_priority}.'
        ),
        recommendation=f'Set {switch.name} STP bridge priority to {expected_priority}.',
    )


def _root_expected_mismatch_finding(
    identifier: str,
    switch: SwitchSTPConfig,
    expected_root: bool,
    actual_root: bool,
) -> STPDriftFinding:
    expected_text = 'to be root bridge' if expected_root else 'not to be root bridge'
    actual_text = 'is root bridge' if actual_root else 'is not root bridge'
    return STPDriftFinding(
        severity='CRITICAL' if expected_root else 'WARNING',
        finding_type='root_expected_mismatch',
        identifier=identifier,
        expected=expected_root,
        actual=actual_root,
        device_id=switch.device_id,
        device_name=switch.name,
        message=f'{switch.name} was expected {expected_text}, but live topology says it {actual_text}.',
        recommendation='Review STP bridge priorities and confirm the intended root bridge.',
    )
