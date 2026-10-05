"""WAN and internet health from the controller's ``stat/health`` (read-only).

``build_wan_health`` is a pure summary of the ``wan`` and ``www`` subsystems, including the
result of the controller's last *scheduled* speedtest; ``get_wan_health`` reads
``stat/health`` with one guarded GET. Nothing here starts a speedtest: that is a controller
command (``cmd/devmgr``) the read-only guard refuses, and it saturates the WAN for 10 to 30
seconds (decision D2 in issue 060). ``unifi-mapper diagnose wan --record`` stores the last
scheduled result through :mod:`unifi_mapper.diagnostics.wan_history`.
"""

from typing import Any
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.coerce import float_or_none, int_or_none


SPEEDTEST_NOTE = (
    "last_speedtest is the result of the controller's last scheduled speedtest; nothing here "
    'starts one.'
)


def _subsystems(rows: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    return {str(r.get('subsystem')): r for r in rows if isinstance(r, dict)}


def build_wan_health(health_rows: Any) -> dict[str, Any]:
    """Summarise the WAN and internet subsystems of a ``stat/health`` payload.

    Pure. Only named fields are read, so nothing else in the payload reaches the result.

    Args:
        health_rows: The ``stat/health`` subsystem records (``wan``, ``www``, ``lan`` …).

    Returns:
        ``wan`` and ``www`` summaries, ``last_speedtest`` (the controller's last scheduled
        result, or None when it reports none), ``healthy`` (both subsystems ``ok``) and
        notes.
    """
    subsystems = _subsystems(health_rows)
    wan = subsystems.get('wan', {})
    www = subsystems.get('www', {})
    last_speedtest = None
    if www.get('speedtest_status') or www.get('xput_up') is not None:
        last_speedtest = {
            'run_epoch': int_or_none(www.get('speedtest_lastrun')),
            'up_mbps': float_or_none(www.get('xput_up')),
            'down_mbps': float_or_none(www.get('xput_down')),
            'ping_ms': float_or_none(www.get('speedtest_ping')),
            'status': www.get('speedtest_status'),
        }
    return {
        'wan': {
            'status': wan.get('status'),
            'isp_name': wan.get('isp_name'),
            'isp_organization': wan.get('isp_organization'),
            'wan_ip': wan.get('wan_ip'),
            'gw_version': wan.get('gw_version'),
            'nameservers': wan.get('nameservers'),
            'uptime': int_or_none(wan.get('uptime')),
        },
        'www': {
            'status': www.get('status'),
            'latency_ms': float_or_none(www.get('latency')),
            'uptime': int_or_none(www.get('uptime')),
            'drops': int_or_none(www.get('drops')),
            'rx_bytes_rate': float_or_none(www.get('rx_bytes-r')),
            'tx_bytes_rate': float_or_none(www.get('tx_bytes-r')),
        },
        'last_speedtest': last_speedtest,
        'healthy': wan.get('status') == 'ok' and www.get('status') == 'ok',
        'notes': [SPEEDTEST_NOTE],
    }


async def get_wan_health() -> dict[str, Any]:
    """WAN and internet health, and the controller's last scheduled speedtest. Read-only.

    When to use this tool:
    - Confirming WAN and ISP status before or after maintenance
    - Reading the most recent speedtest result without starting a new one

    One GET of stat/health. last_speedtest is the result of the controller's own scheduled
    speedtest (None if it reports none); this tool never starts a speedtest.
    get_wan_speedtest_history lists the results recorded by ``unifi-mapper diagnose wan
    --record``.

    Returns:
        wan, www, last_speedtest, healthy and notes.

    Raises:
        ToolError: CONTROLLER_UNREACHABLE or API_ERROR if the controller read fails.
    """
    async with UniFiClient() as client:
        rows = await client.get(client.build_path('stat/health'))
    if isinstance(rows, dict):
        rows = rows.get('data', [])
    return build_wan_health(rows)
