"""PoE budget validation tool for UniFi networks."""

from datetime import datetime
from unifi_mapper.core.models import PoEBudgetReport, PoEDeviceStatus, PoEPortDetail
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def check_poe_budget() -> PoEBudgetReport:
    """Validate PoE budget utilization across all PoE-capable devices.

    For each switch with a PoE budget, reports consumption, utilization,
    and per-port breakdown for high-draw ports. Flags devices approaching
    or exceeding safe PoE thresholds.

    Returns:
        PoEBudgetReport with per-device PoE status

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
            device_statuses, warnings, recommendations = _analyze_poe_budgets(devices)

            total_budget = sum(d.poe_budget for d in device_statuses)
            total_consumption = sum(d.poe_consumption for d in device_statuses)

            return PoEBudgetReport(
                timestamp=datetime.now().isoformat(),
                devices_analyzed=len(device_statuses),
                total_budget=total_budget,
                total_consumption=total_consumption,
                devices=device_statuses,
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
                message=f'Error checking PoE budget: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _analyze_poe_budgets(
    devices: list[dict],
) -> tuple[list[PoEDeviceStatus], list[str], list[str]]:
    """Pure analysis function for PoE budget validation."""
    statuses: list[PoEDeviceStatus] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    for device in devices:
        device_type = device.get('type', '')
        if device_type not in ('usw', 'switch', 'udm', 'udmpro'):
            continue

        # PoE budget is in total_max_power (watts) on UniFi devices
        poe_budget = device.get('total_max_power') or device.get('poe_budget', 0) or 0
        if poe_budget <= 0:
            continue

        # Consumption: sum per-port poe_power (strings in API response)
        port_table = device.get('port_table', [])
        poe_consumption = sum(
            float(p.get('poe_power', 0) or 0)
            for p in port_table
            if p.get('poe_mode') and p.get('poe_mode') != 'off'
        )
        poe_available = max(0, poe_budget - poe_consumption)
        utilization = (poe_consumption / poe_budget) * 100

        dev_name = device.get('name', device.get('mac', 'Unknown'))

        # Collect high-draw ports (>5W)
        high_draw: list[PoEPortDetail] = []
        for port in port_table:
            poe_power = float(port.get('poe_power', 0) or 0)
            if poe_power > 5:
                high_draw.append(
                    PoEPortDetail(
                        port_idx=port.get('port_idx', 0),
                        port_name=port.get('name', f'Port {port.get("port_idx", 0)}'),
                        poe_power=poe_power,
                        poe_class=port.get('poe_class'),
                    )
                )

        # Determine status
        if utilization >= 90:
            status = 'CRITICAL'
            warnings.append(
                f'{dev_name}: PoE at {utilization:.0f}% — only {poe_available:.0f}W remaining'
            )
            recommendations.append(f'Redistribute PoE load from {dev_name} or add a PoE switch')
        elif utilization >= 80:
            status = 'WARNING'
            warnings.append(f'{dev_name}: PoE at {utilization:.0f}%')
        else:
            status = 'OK'

        statuses.append(
            PoEDeviceStatus(
                device_id=device.get('_id', ''),
                device_name=dev_name,
                model=device.get('model', ''),
                poe_budget=poe_budget,
                poe_consumption=poe_consumption,
                poe_available=poe_available,
                utilization_percent=round(utilization, 1),
                status=status,
                high_draw_ports=high_draw,
            )
        )

    return statuses, warnings, recommendations
