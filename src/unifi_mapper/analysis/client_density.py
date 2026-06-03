"""Client density analysis tool for UniFi networks."""

from datetime import datetime
from unifi_mapper.core.models import APClientDensity, ClientDensityReport
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def analyze_client_density() -> ClientDensityReport:
    """Analyze wireless client density per access point.

    Groups wireless clients by their associated AP, calculates average
    signal strength, and flags APs with excessive client counts (>30).

    Returns:
        ClientDensityReport with per-AP density metrics

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            clients = await client.get_clients()
            devices = await client.get_devices()

            aps, total_wireless, warnings, recommendations = _analyze_density(clients, devices)

            return ClientDensityReport(
                timestamp=datetime.now().isoformat(),
                aps_analyzed=len(aps),
                total_wireless_clients=total_wireless,
                access_points=aps,
                warnings=warnings,
                recommendations=recommendations,
            )

        except ToolError:
            raise
        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                )
            raise ToolError(
                message=f'Error analyzing client density: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _analyze_density(
    clients: list[dict],
    devices: list[dict],
) -> tuple[list[APClientDensity], int, list[str], list[str]]:
    """Pure analysis function for client density."""
    # Build AP lookup by MAC
    ap_info: dict[str, dict] = {}
    for device in devices:
        if device.get('type') in ('uap', 'ap'):
            mac = device.get('mac', '').lower()
            if mac:
                ap_info[mac] = device

    # Group wireless clients by ap_mac
    ap_clients: dict[str, list[dict]] = {}
    total_wireless = 0
    for c in clients:
        if not c.get('is_wired', True):
            total_wireless += 1
            ap_mac = (c.get('ap_mac') or '').lower()
            if ap_mac:
                ap_clients.setdefault(ap_mac, []).append(c)

    aps: list[APClientDensity] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    for ap_mac, ap_client_list in ap_clients.items():
        device = ap_info.get(ap_mac, {})
        ap_name = device.get('name', ap_mac)
        client_count = len(ap_client_list)

        # Calculate average signal strength
        signals = [c.get('signal', 0) or c.get('rssi', 0) for c in ap_client_list]
        valid_signals = [s for s in signals if s != 0]
        avg_signal = sum(valid_signals) / len(valid_signals) if valid_signals else None

        # Determine status
        if client_count > 50:
            status = 'CRITICAL'
            warnings.append(f'{ap_name}: {client_count} clients — severely overloaded')
            recommendations.append(f'Add AP near {ap_name} to offload clients')
        elif client_count > 30:
            status = 'WARNING'
            warnings.append(f'{ap_name}: {client_count} clients — approaching capacity')
        else:
            status = 'OK'

        aps.append(
            APClientDensity(
                device_id=device.get('_id', ap_mac),
                device_name=ap_name,
                model=device.get('model', ''),
                client_count=client_count,
                avg_signal_dbm=round(avg_signal, 1) if avg_signal is not None else None,
                status=status,
            )
        )

    # Sort by client count descending
    aps.sort(key=lambda a: a.client_count, reverse=True)

    return aps, total_wireless, warnings, recommendations
