"""Device inventory and firmware drift for both surfaces (issues 017 and 078).

The pure core of ``unifi-mapper inventory`` and the MCP tools ``get_device_inventory`` and
``get_firmware_drift``. ``inventory_cli`` fetches with the sync client and calls
:func:`categorize_devices` and :func:`find_firmware_skew` from here; the MCP handlers fetch
``stat/device`` through the async, read-only ``UniFiClient`` and call the same functions.
Nothing here prints or exits.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mapper.core.models import (
    DeviceInventoryReport,
    FirmwareDriftModel,
    FirmwareDriftReport,
    InventoryDevice,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# The inventory's device types, in the order the CLI prints them.
INVENTORY_TYPES: tuple[str, ...] = ('firewall', 'switch', 'ap', 'other')
InventoryType = Literal['all', 'firewall', 'switch', 'ap', 'other']
DriftType = Literal['all', 'firewall', 'switch', 'ap']

_VERSION_PART = re.compile(r'\d+|[A-Za-z]+')


def get_device_type(model: str, device_type_field: str = '') -> str:
    """Return ``firewall``, ``switch``, ``ap`` or ``other`` for a device.

    The controller's ``type`` code wins when it is one of the known ones; otherwise the model
    code is matched against the known families.

    Args:
        model: The model code (e.g. ``USW-Pro-24-PoE``).
        device_type_field: The controller's ``type`` (``udm``, ``usw``, ``uap``, ...).

    Returns:
        One of :data:`INVENTORY_TYPES`.
    """
    model_lower = model.lower()
    type_lower = device_type_field.lower() if device_type_field else ''

    if type_lower in ('ugw', 'udm', 'usg'):
        return 'firewall'
    if type_lower == 'usw':
        return 'switch'
    if type_lower == 'uap':
        return 'ap'

    if any(x in model_lower for x in ['udm', 'usg', 'ugw', 'gateway', 'router', 'dream']):
        return 'firewall'

    if any(
        x in model_lower
        for x in ['usw', 'switch', 'us-', 'usl', 'usm', 'us8', 'us16', 'us24', 'us48']
    ):
        return 'switch'
    if model_lower.startswith('us') and len(model_lower) > 2 and model_lower[2].isdigit():
        return 'switch'

    if any(
        x in model_lower
        for x in ['uap', 'u6', 'u7', 'ac', 'nano', 'litebeam', 'flexhd', 'ualr', 'uacc']
    ):
        return 'ap'

    return 'other'


def categorize_devices(devices: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group ``stat/device`` records by inventory type, each category sorted by name.

    Args:
        devices: The controller's device records.

    Returns:
        ``{'firewall': [...], 'switch': [...], 'ap': [...], 'other': [...]}``; every key is
        present. Each entry is the flat record the inventory prints (name, model, version,
        ip, mac, id, adopted, state, uptime, upgradable, upgrade_to_firmware, type, raw_type).
    """
    categorized: dict[str, list[dict[str, Any]]] = {t: [] for t in INVENTORY_TYPES}
    for device in devices:
        model = device.get('model', 'Unknown')
        type_field = device.get('type', '')
        device_type = get_device_type(model, type_field)
        categorized[device_type].append(
            {
                'name': device.get('name', 'Unnamed'),
                'model': model,
                'model_name': device.get('model_name', model),
                'version': device.get('version', 'Unknown'),
                'ip': device.get('ip', 'N/A'),
                'mac': device.get('mac', 'N/A'),
                'id': device.get('_id', ''),
                'adopted': device.get('adopted', False),
                'state': device.get('state', 0),
                'uptime': device.get('uptime', 0),
                'upgradable': device.get('upgradable', False),
                'upgrade_to_firmware': device.get('upgrade_to_firmware', ''),
                'type': device_type,
                'raw_type': type_field,
            }
        )
    for category in categorized.values():
        category.sort(key=lambda x: str(x['name']).lower())
    return categorized


def find_firmware_skew(
    categorized: dict[str, list[dict[str, Any]]],
    filter_types: set[str],
) -> dict[str, dict[str, list[str]]]:
    """Group devices by model and return the models with mixed firmware versions.

    Args:
        categorized: :func:`categorize_devices`'s result.
        filter_types: The types to include; ``{'all'}`` includes every type.

    Returns:
        ``{model: {version: [device names]}}`` for models with more than one version.
    """
    show_all = 'all' in filter_types
    by_model: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for device_type, devices in categorized.items():
        if not show_all and device_type not in filter_types:
            continue
        for device in devices:
            model = device.get('model', 'Unknown')
            version = device.get('version', 'Unknown')
            name = device.get('name', 'Unnamed')
            by_model[model][version].append(name)

    return {model: dict(versions) for model, versions in by_model.items() if len(versions) > 1}


def version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """A sort key that orders ``7.2.2`` after ``7.1.26`` and any text before any number.

    Args:
        version: A firmware version string.

    Returns:
        A tuple of ``(1, int)`` for numeric parts and ``(0, text)`` for the rest.
    """
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.lower())
        for part in _VERSION_PART.findall(version)
    ) or ((0, version.lower()),)


def _kept(
    categorized: dict[str, list[dict[str, Any]]], filter_types: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """The categories ``filter_types`` keeps (``{'all'}`` keeps every one), in inventory order."""
    if 'all' in filter_types:
        return categorized
    return {t: categorized.get(t, []) for t in INVENTORY_TYPES if t in filter_types}


def firmware_drift(
    categorized: dict[str, list[dict[str, Any]]], filter_types: set[str], *, timestamp: str
) -> FirmwareDriftReport:
    """Build the firmware drift report from categorised devices (pure).

    Args:
        categorized: :func:`categorize_devices`'s result.
        filter_types: The inventory types to keep, as ``parse_filter`` returns them
            (``{'all'}`` keeps every type).
        timestamp: When the devices were read.

    Returns:
        The report: skewed models with the fleet's newest version and the devices behind it,
        plus the upgrades the controller offers and the kept devices that are offline.
    """
    kept = _kept(categorized, filter_types)
    skew = find_firmware_skew(categorized, filter_types)
    models: list[FirmwareDriftModel] = []
    for model in sorted(skew):
        versions = skew[model]
        newest = max(versions, key=version_key)
        behind = sorted(n for v, names in versions.items() if v != newest for n in names)
        models.append(
            FirmwareDriftModel(
                model=model,
                versions={v: sorted(names) for v, names in sorted(versions.items())},
                fleet_newest=newest,
                devices_behind=behind,
            )
        )
    devices = [d for group in kept.values() for d in group]
    upgradable = {
        str(d['name']): str(d.get('upgrade_to_firmware') or 'available')
        for d in devices
        if d.get('upgradable')
    }
    offline = sorted(str(d['name']) for d in devices if d.get('state') != 1)
    recommendations: list[str] = []
    for entry in models:
        recommendations.append(
            f'{entry.model}: bring {", ".join(entry.devices_behind)} up to {entry.fleet_newest}'
        )
    if offline and models:
        recommendations.append(
            f'Offline devices ({", ".join(offline)}) report their last known version; '
            'check them before scheduling upgrades'
        )
    if models:
        recommendations.append(
            'Finish STP root or priority changes first; schedule firmware updates separately'
        )
    return FirmwareDriftReport(
        timestamp=timestamp,
        device_type='all' if 'all' in filter_types else ','.join(sorted(filter_types)),
        devices_analyzed=len(devices),
        models_with_skew=len(models),
        models=models,
        upgradable=upgradable,
        offline=offline,
        recommendations=recommendations,
    )


async def _read_categorized() -> dict[str, list[dict[str, Any]]]:
    """Read ``stat/device`` through the read-only client and categorise it."""
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
        except ToolError:
            raise
        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                ) from e
            raise ToolError(
                message=f'Error reading devices: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            ) from e
    return categorize_devices(devices)


async def get_device_inventory(
    device_type: Annotated[
        InventoryType, Field(description='all, firewall, switch, ap or other')
    ] = 'all',
) -> DeviceInventoryReport:
    """The device inventory by type, as `unifi-mapper inventory list` prints it. Read-only.

    Every device the controller lists, grouped as firewall (gateways), switch, ap or other,
    with model, firmware, address, state and the upgrade the controller offers. The counts
    cover the whole site; ``devices`` and the summaries cover the type asked for.

    Args:
        device_type: ``all`` or one type to keep.

    Returns:
        The inventory report.

    Raises:
        ToolError: CONTROLLER_UNREACHABLE or API_ERROR when the devices cannot be read.
    """
    categorized = await _read_categorized()
    kept = _kept(categorized, {device_type})
    firmware_summary: dict[str, dict[str, int]] = {}
    model_summary: dict[str, dict[str, int]] = {}
    devices: list[InventoryDevice] = []
    for type_name in INVENTORY_TYPES:
        if type_name not in kept:
            continue
        group = kept[type_name]
        if not group:
            continue
        versions: dict[str, int] = defaultdict(int)
        models: dict[str, int] = defaultdict(int)
        for d in group:
            versions[str(d['version'])] += 1
            models[str(d['model'])] += 1
            devices.append(
                InventoryDevice(
                    name=str(d['name']),
                    model=str(d['model']),
                    model_name=str(d['model_name']),
                    version=str(d['version']),
                    ip=str(d['ip']),
                    mac=str(d['mac']),
                    id=str(d['id']),
                    type=type_name,
                    raw_type=str(d['raw_type']),
                    adopted=bool(d['adopted']),
                    state=int(d['state'] or 0),
                    online=d['state'] == 1,
                    uptime=int(d['uptime'] or 0),
                    upgradable=bool(d['upgradable']),
                    upgrade_to_firmware=str(d['upgrade_to_firmware'] or ''),
                )
            )
        firmware_summary[type_name] = dict(
            sorted(versions.items(), key=lambda i: version_key(i[0]))
        )
        model_summary[type_name] = dict(sorted(models.items()))
    return DeviceInventoryReport(
        timestamp=datetime.now().isoformat(),
        device_type=device_type,
        total=sum(len(g) for g in categorized.values()),
        counts={t: len(categorized[t]) for t in INVENTORY_TYPES},
        devices=devices,
        firmware_summary=firmware_summary,
        model_summary=model_summary,
    )


async def get_firmware_drift(
    device_type: Annotated[DriftType, Field(description='all, firewall, switch or ap')] = 'all',
) -> FirmwareDriftReport:
    """Models whose devices run mixed firmware versions (`inventory firmware-skew`). Read-only.

    Per skewed model: each version's devices, the newest version any of them runs and the
    devices behind it; plus the upgrades the controller currently offers and the kept devices
    that are not connected (their version is the last one reported).

    Args:
        device_type: ``all`` or one type to keep.

    Returns:
        The drift report.

    Raises:
        ToolError: CONTROLLER_UNREACHABLE or API_ERROR when the devices cannot be read.
    """
    categorized = await _read_categorized()
    return firmware_drift(categorized, {device_type}, timestamp=datetime.now().isoformat())
