"""Safe WLAN (SSID) configuration writes with guard-field verification.

Why this module exists
----------------------
On 2026-08-03 two `minrate_*` fields were changed on a 5 GHz WLAN by fetching the WLAN
object, mutating it and PUTting the whole object back. Controller 10.5.67 ran schema
migration over the echoed object and silently changed four fields nobody asked for::

    wlan_bands:      ['5g'] -> ['5g', '6g']
    wpa3_support:    False  -> True
    wpa3_transition: False  -> True
    pmf_mode:        'disabled' -> 'optional'

6 GHz mandates WPA3, so gaining the band dragged WPA3 transition mode along with it,
which broke association for the existing WPA2 clients. Around nine devices dropped off
the 5 GHz SSID and reattached to the 2.4 GHz IoT SSID. The 2.4-only WLAN escaped
untouched because it has no 6 GHz band to add.

Two rules follow, and this module enforces both:

1. Send a MINIMAL patch containing only the fields being changed — never the whole
   object. Anything echoed back is a field the controller may "migrate".
2. After writing, re-read and assert the security-relevant fields did not move.

A second, quieter trap is also covered: `minrate_setting_preference` gates the manual
rate fields. Leaving it at ``'auto'`` means the controller recomputes
``minrate_*_data_rate_kbps`` on provision and the written value silently reverts.
"""

from __future__ import annotations

from typing import Any
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# Fields that must never change as a side effect of an unrelated patch. Drift in any of
# these can break client association or authentication for an entire SSID.
WLAN_GUARD_FIELDS: tuple[str, ...] = (
    'wpa3_support',
    'wpa3_transition',
    'wpa3_fast_roaming',
    'wpa3_enhanced_192',
    'pmf_mode',
    'wlan_bands',
    'wlan_band',
    'wpa_mode',
    'wpa_enc',
    'security',
    'x_passphrase',
    'enabled',
)

# Manual rate fields that are ignored unless the preference gate is set to 'manual'.
_MINRATE_VALUE_FIELDS: tuple[str, ...] = (
    'minrate_ng_data_rate_kbps',
    'minrate_na_data_rate_kbps',
    'minrate_ng_enabled',
    'minrate_na_enabled',
    'minrate_ng_advertising_rates',
    'minrate_na_advertising_rates',
)
_MINRATE_GATE_FIELD = 'minrate_setting_preference'


def check_minrate_gate(patch: dict[str, Any]) -> list[str]:
    """Warn when manual rate fields are patched without the 'manual' preference gate.

    Returns:
        A list of human-readable warnings; empty when the patch is safe.
    """
    touches_rates = any(field in patch for field in _MINRATE_VALUE_FIELDS)
    if not touches_rates:
        return []

    gate = patch.get(_MINRATE_GATE_FIELD)
    if gate == 'manual':
        return []

    if gate is None:
        return [
            f'patch sets {sorted(f for f in _MINRATE_VALUE_FIELDS if f in patch)} but does '
            f"not set {_MINRATE_GATE_FIELD}='manual'; the controller will recompute these "
            'values on provision and the change will silently revert'
        ]
    return [
        f'{_MINRATE_GATE_FIELD}={gate!r} leaves rate control with the controller; set it '
        "to 'manual' for the patched rate values to persist"
    ]


def verify_wlan_patch(
    before: dict[str, Any],
    after: dict[str, Any],
    patch: dict[str, Any],
    guard_fields: tuple[str, ...] = WLAN_GUARD_FIELDS,
) -> dict[str, Any]:
    """Confirm a patch applied and that no guarded field drifted.

    Args:
        before: WLAN object read immediately before the write.
        after: WLAN object re-read immediately after the write.
        patch: The fields that were intended to change.
        guard_fields: Fields that must be identical in `before` and `after`.

    Returns:
        Dict with:
            - ``ok``: True only when everything applied and nothing drifted.
            - ``applied``: patch fields confirmed present in `after`.
            - ``not_applied``: {field: (intended, actual)} for silently reverted writes.
            - ``drifted``: {field: (before, after)} for guarded collateral damage.
    """
    applied: dict[str, Any] = {}
    not_applied: dict[str, tuple[Any, Any]] = {}
    for field, intended in patch.items():
        actual = after.get(field)
        if actual == intended:
            applied[field] = actual
        else:
            not_applied[field] = (intended, actual)

    drifted: dict[str, tuple[Any, Any]] = {}
    for field in guard_fields:
        if field in patch:
            continue  # deliberately changed
        if field not in before and field not in after:
            continue
        if before.get(field) != after.get(field):
            drifted[field] = (before.get(field), after.get(field))

    return {
        'ok': not not_applied and not drifted,
        'applied': applied,
        'not_applied': not_applied,
        'drifted': drifted,
    }


async def update_wlan_settings(
    ssid: str,
    patch: dict[str, Any],
    dry_run: bool = True,
    guard_fields: tuple[str, ...] = WLAN_GUARD_FIELDS,
) -> dict[str, Any]:
    """Patch a WLAN using a minimal PUT, then verify nothing else moved.

    Args:
        ssid: SSID name (the WLAN's ``name`` field).
        patch: Only the fields to change. Never pass a full WLAN object.
        dry_run: When True, report the intended diff and warnings without writing.
        guard_fields: Fields asserted unchanged after the write.

    Returns:
        Dict with ``ssid``, ``diff``, ``warnings`` and (when applied) ``verification``.

    Raises:
        ToolError: if the SSID is not found, or if the write caused guard-field drift
            or was silently reverted.
    """
    warnings = check_minrate_gate(patch)

    async with UniFiClient() as client:
        raw = await client.get(client.build_path('rest/wlanconf'))
        wlans = raw.get('data', raw) if isinstance(raw, dict) else raw
        before = next((w for w in wlans if w.get('name') == ssid), None)
        if before is None:
            raise ToolError(
                message=f'WLAN not found: {ssid}',
                error_code=ErrorCodes.CONFIG_INVALID,
            )

        diff = {k: (before.get(k), v) for k, v in patch.items() if before.get(k) != v}
        result: dict[str, Any] = {
            'ssid': ssid,
            'wlan_id': before.get('_id'),
            'diff': diff,
            'warnings': warnings,
        }

        if dry_run or not diff:
            result['applied'] = False
            return result

        # MINIMAL patch only — echoing the full object triggers schema migration.
        await client.put(client.build_path(f'rest/wlanconf/{before["_id"]}'), dict(patch))

        raw_after = await client.get(client.build_path('rest/wlanconf'))
        wlans_after = (
            raw_after.get('data', raw_after) if isinstance(raw_after, dict) else raw_after
        )
        after = next((w for w in wlans_after if w.get('_id') == before['_id']), {})

        verification = verify_wlan_patch(before, after, patch, guard_fields=guard_fields)
        result['applied'] = True
        result['verification'] = verification

        if not verification['ok']:
            raise ToolError(
                message=(
                    f'WLAN {ssid!r} write did not verify — '
                    f'drifted={verification["drifted"]} '
                    f'not_applied={verification["not_applied"]}'
                ),
                error_code=ErrorCodes.API_ERROR,
            )

        return result
