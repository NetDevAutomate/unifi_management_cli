"""The one place that decides a switch port's effective profile and link settings.

A port's configuration can come from a ``port_overrides`` entry on the device or
be inherited from the profile (``portconf``) its ``port_table`` entry references.
The override's ``portconf_id`` wins, because that is what the controller pushes
to the device. Every caller that picks a port's effective profile uses
:func:`effective_profile_id`: ``ports inspect`` (through
:func:`effective_port_settings`), the sibling's ``collect_override``,
``summarise_ports`` and ``profile_usage``, and the link-speed and profile-usage
audits. So no two views can name a different profile for the same port.

Negotiation keys (verified against a live controller's ``rest/portconf`` and
``port_overrides``): ``autoneg`` (bool), ``speed`` (Mbps) and ``full_duplex``
(bool). A forced speed is ``speed`` when ``autoneg`` is False.

Import-cycle rule: this module imports only the standard library, ``typing`` and
pydantic. ``port_inspect`` imports it, and both ``diagnostic_reads`` and
``port_diagnostics`` import ``port_inspect``, so it carries private copies of
``diagnostic_reads.int_or_none`` and ``str_or_none`` (pinned equal by a test).
"""

from pydantic import BaseModel, Field
from typing import Any, Literal, Optional


ProfileSource = Literal['override', 'port_table', 'unknown']
FieldSource = Literal['override', 'profile', 'port_table', 'unknown']


def _int_or_none(value: Any) -> Optional[int]:
    """Return ``value`` as an int, or None when it is absent or not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> Optional[str]:
    """Return a non-empty string form of ``value``, or None."""
    if value is None:
        return None
    text = str(value)
    return text if text else None


class EffectivePortSettings(BaseModel):
    """A port's effective profile and the settings it resolves to.

    The first seven fields are exactly what ``ports inspect`` reports as the
    port's profile. Values are copied verbatim from the controller.
    ``sources`` names where each field came from.
    """

    profile_id: Optional[str] = None
    name: Any = None
    forward: Any = None
    native_network_id: Any = None
    tagged_vlans: Optional[list[Any]] = None
    poe_mode: Any = None
    source: ProfileSource = 'unknown'
    autoneg: Optional[bool] = None
    forced_speed_mbps: Optional[int] = None
    full_duplex: Optional[bool] = None
    sources: dict[str, FieldSource] = Field(default_factory=lambda: {})


def port_override(device: dict[str, Any], port_idx: Optional[int]) -> Optional[dict[str, Any]]:
    """Return the device's first ``port_overrides`` entry for ``port_idx``, or None.

    An entry matches when it is a dict and its ``port_idx``, coerced like
    ``diagnostic_reads.int_or_none`` (bools and non-numerics never match),
    equals ``port_idx``. A ``port_idx`` of None matches nothing.

    Args:
        device: A ``stat/device`` record.
        port_idx: The port index.

    Returns:
        The override entry, or None.
    """
    if port_idx is None or isinstance(port_idx, bool):
        return None
    for override in device.get('port_overrides') or []:
        if isinstance(override, dict) and _int_or_none(override.get('port_idx')) == port_idx:
            return override
    return None


def effective_profile_id(
    device: dict[str, Any], port_entry: dict[str, Any], port_idx: Optional[int]
) -> tuple[Optional[str], ProfileSource]:
    """The single precedence rule: the override's ``portconf_id`` wins, else the port table's.

    Ids are coerced like ``diagnostic_reads.str_or_none``, so ``''`` and None
    mean "absent". An override entry without a ``portconf_id`` falls through to
    the port table.

    Args:
        device: A ``stat/device`` record (its ``port_overrides`` are read).
        port_entry: The port's ``port_table`` entry.
        port_idx: The port index.

    Returns:
        ``(override id, 'override')``, else ``(port table id, 'port_table')``,
        else ``(None, 'unknown')``.
    """
    override = port_override(device, port_idx)
    override_id = _str_or_none(override.get('portconf_id')) if override else None
    if override_id:
        return override_id, 'override'
    table_id = _str_or_none(port_entry.get('portconf_id'))
    if table_id:
        return table_id, 'port_table'
    return None, 'unknown'


def _bool_value(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _first(
    candidates: list[tuple[FieldSource, Any]],
) -> tuple[Any, FieldSource]:
    """Return the first candidate value that is not None, with its source."""
    for source, value in candidates:
        if value is not None:
            return value, source
    return None, 'unknown'


def _first_truthy(
    candidates: list[tuple[FieldSource, Any]],
) -> tuple[Any, FieldSource]:
    """Return the first truthy candidate value, with its source (``ports inspect``'s ``or``)."""
    for source, value in candidates:
        if value:
            return value, source
    last = candidates[-1][1] if candidates else None
    return last, 'unknown'


def effective_port_settings(
    switch: dict[str, Any],
    port_table: dict[str, Any],
    port_idx: Optional[int],
    profiles: dict[str, dict[str, Any]],
    networks: dict[str, dict[str, Any]],
) -> EffectivePortSettings:
    """Resolve a port's effective settings: override, then profile, then port_table.

    ``profile_id`` and ``source`` come from :func:`effective_profile_id`, the
    override entry from :func:`port_override`. Field precedence:

    * ``forward``: the profile's, then the override's (``ports inspect``'s rule).
    * ``native_network_id``: override, then profile, then port table.
    * ``poe_mode``: override, then profile.
    * ``name`` and ``tagged_vlans``: the profile's (tagged network ids mapped to
      VLAN numbers through ``networks``).
    * ``autoneg`` and ``full_duplex``: override, then profile, then port table
      (bools only).
    * ``forced_speed_mbps``: the configured ``speed`` (override, then profile)
      when ``autoneg`` is False. The port table's ``speed`` is the negotiated
      rate, never a configured one, so it is not a candidate.

    Args:
        switch: The ``stat/device`` record.
        port_table: The port's ``port_table`` entry.
        port_idx: The port index.
        profiles: ``portconf`` records keyed by ``_id``.
        networks: ``networkconf`` records keyed by ``_id``.

    Returns:
        The resolved settings.
    """
    override = port_override(switch, port_idx) or {}
    profile_id, source = effective_profile_id(switch, port_table, port_idx)
    profile = profiles.get(profile_id or '', {})
    sources: dict[str, FieldSource] = {
        'profile_id': source,
        'name': 'profile' if profile.get('name') is not None else 'unknown',
    }

    tagged_ids = profile.get('tagged_networkconf_ids')
    tagged_vlans: Optional[list[Any]] = None
    if isinstance(tagged_ids, list):
        tagged_vlans = [
            networks[t]['vlan']
            for t in tagged_ids
            if t in networks and networks[t].get('vlan') is not None
        ]
    sources['tagged_vlans'] = 'profile' if tagged_vlans is not None else 'unknown'

    forward, sources['forward'] = _first_truthy(
        [('profile', profile.get('forward')), ('override', override.get('forward'))]
    )
    native, sources['native_network_id'] = _first_truthy(
        [
            ('override', override.get('native_networkconf_id')),
            ('profile', profile.get('native_networkconf_id')),
            ('port_table', port_table.get('native_networkconf_id')),
        ]
    )
    poe_mode, sources['poe_mode'] = _first_truthy(
        [('override', override.get('poe_mode')), ('profile', profile.get('poe_mode'))]
    )
    autoneg, sources['autoneg'] = _first(
        [
            ('override', _bool_value(override.get('autoneg'))),
            ('profile', _bool_value(profile.get('autoneg'))),
            ('port_table', _bool_value(port_table.get('autoneg'))),
        ]
    )
    full_duplex, sources['full_duplex'] = _first(
        [
            ('override', _bool_value(override.get('full_duplex'))),
            ('profile', _bool_value(profile.get('full_duplex'))),
            ('port_table', _bool_value(port_table.get('full_duplex'))),
        ]
    )
    speed, speed_source = _first(
        [
            ('override', _int_or_none(override.get('speed'))),
            ('profile', _int_or_none(profile.get('speed'))),
        ]
    )
    forced = speed if autoneg is False and speed else None
    sources['forced_speed_mbps'] = speed_source if forced is not None else 'unknown'

    return EffectivePortSettings(
        profile_id=profile_id,
        name=profile.get('name'),
        forward=forward,
        native_network_id=native,
        tagged_vlans=tagged_vlans,
        poe_mode=poe_mode,
        source=source,
        autoneg=autoneg,
        forced_speed_mbps=forced,
        full_duplex=full_duplex,
        sources=sources,
    )
