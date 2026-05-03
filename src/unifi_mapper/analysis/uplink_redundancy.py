"""Uplink redundancy check tool for UniFi networks."""

from datetime import datetime
from unifi_mapper.core.models import DeviceUplinkStatus, UplinkInfo, UplinkRedundancyReport
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def check_uplink_redundancy() -> UplinkRedundancyReport:
    """Check uplink redundancy for all switches.

    For each switch, counts uplink ports and flags single-uplink devices
    as potential single points of failure.

    Returns:
        UplinkRedundancyReport with per-device uplink status

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
            statuses, warnings, recommendations = _analyze_uplink_redundancy(devices)

            single = sum(1 for d in statuses if not d.redundant)
            redundant = sum(1 for d in statuses if d.redundant)

            return UplinkRedundancyReport(
                timestamp=datetime.now().isoformat(),
                devices_analyzed=len(statuses),
                single_uplink_devices=single,
                redundant_devices=redundant,
                devices=statuses,
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
                message=f'Error checking uplink redundancy: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _analyze_uplink_redundancy(
    devices: list[dict],
) -> tuple[list[DeviceUplinkStatus], list[str], list[str]]:
    """Pure analysis function for uplink redundancy."""
    statuses: list[DeviceUplinkStatus] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    for device in devices:
        device_type = device.get('type', '')
        # Only analyze switches (gateways are the root, APs are leaf)
        if device_type not in ('usw', 'switch'):
            continue

        dev_name = device.get('name', device.get('mac', 'Unknown'))
        port_table = device.get('port_table', [])

        uplinks: list[UplinkInfo] = []
        for port in port_table:
            if port.get('is_uplink', False):
                uplinks.append(
                    UplinkInfo(
                        port_idx=port.get('port_idx', 0),
                        speed_mbps=port.get('speed', 0) or 0,
                        is_up=port.get('up', False),
                    )
                )

        uplink_count = len(uplinks)
        redundant = uplink_count >= 2
        total_speed = sum(u.speed_mbps for u in uplinks)

        if uplink_count == 1:
            status = 'WARNING'
            warnings.append(f'{dev_name}: single uplink — potential single point of failure')
            recommendations.append(f'Consider adding a redundant uplink to {dev_name}')
        elif uplink_count == 0:
            status = 'WARNING'
            warnings.append(f'{dev_name}: no uplink detected')
        else:
            status = 'OK'

        statuses.append(
            DeviceUplinkStatus(
                device_id=device.get('_id', ''),
                device_name=dev_name,
                model=device.get('model', ''),
                uplinks=uplinks,
                uplink_count=uplink_count,
                redundant=redundant,
                total_uplink_speed_mbps=total_speed,
                status=status,
            )
        )

    return statuses, warnings, recommendations
