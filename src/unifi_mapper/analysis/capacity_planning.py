"""Capacity planning tool for UniFi networks."""

from datetime import datetime
from unifi_mcp.models import (
    CapacityReport,
    DeviceCapacity,
)
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def get_capacity_report() -> CapacityReport:
    """Generate network capacity planning report.

    When to use this tool:
    - Before deploying new devices or expanding the network
    - During quarterly/annual infrastructure planning
    - When users report slow performance during peak times
    - To identify switches approaching port exhaustion
    - To monitor PoE budget utilization

    How capacity planning works:
    - Inventories all switch ports (total vs used)
    - Calculates PoE power budget utilization
    - Identifies devices near capacity limits
    - Provides expansion recommendations
    - Tracks uplink capacity for bandwidth planning

    Key metrics tracked:
    - Port utilization: % of ports with active links
    - PoE utilization: % of power budget consumed
    - Available ports: Remaining capacity for growth
    - Uplink capacity: Aggregate uplink bandwidth

    Common workflow:
    1. get_capacity_report() - assess current state
    2. Review devices at WARNING or CRITICAL utilization
    3. Plan expansion for devices >75% utilized
    4. Consider consolidation for devices <30% utilized
    5. Budget for hardware before reaching exhaustion

    What to do next:
    - If CRITICAL: Order additional switches immediately
    - If WARNING: Plan expansion within 30-60 days
    - Low utilization: Consider consolidating switches
    - PoE issues: Add PoE switches or redistribute devices

    Returns:
        CapacityReport with device capacities and recommendations

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()

            device_capacities: list[DeviceCapacity] = []
            total_ports = 0
            used_ports = 0
            available_ports = 0
            total_poe_budget = 0.0
            total_poe_used = 0.0

            bottlenecks: list[str] = []
            recommendations: list[str] = []
            expansion_needed = False

            for device in devices:
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch', 'udm', 'udmpro'):
                    continue

                dev_id = device.get('_id', '')
                dev_name = device.get('name', device.get('mac', 'Unknown'))
                dev_model = device.get('model', '')
                port_table = device.get('port_table', [])

                # Count ports
                dev_total_ports = len(port_table)
                dev_used_ports = sum(1 for p in port_table if p.get('up', False))
                dev_available = dev_total_ports - dev_used_ports

                total_ports += dev_total_ports
                used_ports += dev_used_ports
                available_ports += dev_available

                # Calculate port utilization
                port_util = 0.0
                if dev_total_ports > 0:
                    port_util = (dev_used_ports / dev_total_ports) * 100

                # Get PoE info
                sys_stats = device.get('sys_stats', {})
                poe_consumption = sys_stats.get('poe_consumption', 0) or 0
                poe_budget = (
                    device.get('poe_budget', 0) or sys_stats.get('poe_power_budget', 0) or 0
                )
                poe_available = max(0, poe_budget - poe_consumption)

                total_poe_budget += poe_budget
                total_poe_used += poe_consumption

                poe_util = 0.0
                if poe_budget > 0:
                    poe_util = (poe_consumption / poe_budget) * 100

                # Get uplink info
                uplink_ports = [p for p in port_table if p.get('is_uplink', False)]
                uplink_capacity = sum(p.get('speed', 0) for p in uplink_ports) / 1000  # Gbps

                # Generate recommendation
                recommendation = _generate_device_recommendation(
                    dev_name, port_util, poe_util, dev_available, poe_available
                )

                # Track bottlenecks
                if port_util >= 85:
                    bottlenecks.append(f'{dev_name}: {port_util:.0f}% port utilization')
                    expansion_needed = True
                if poe_util >= 85:
                    bottlenecks.append(f'{dev_name}: {poe_util:.0f}% PoE utilization')

                device_capacities.append(
                    DeviceCapacity(
                        device_id=dev_id,
                        device_name=dev_name,
                        model=dev_model,
                        total_ports=dev_total_ports,
                        used_ports=dev_used_ports,
                        available_ports=dev_available,
                        utilization_percent=round(port_util, 1),
                        poe_budget_watts=poe_budget if poe_budget > 0 else None,
                        poe_used_watts=poe_consumption if poe_budget > 0 else None,
                        poe_available_watts=poe_available if poe_budget > 0 else None,
                        poe_utilization_percent=round(poe_util, 1) if poe_budget > 0 else None,
                        uplink_capacity_gbps=uplink_capacity,
                        recommendation=recommendation,
                    )
                )

            # Calculate network-wide utilization
            overall_util = 0.0
            if total_ports > 0:
                overall_util = (used_ports / total_ports) * 100

            # Generate recommendations
            if overall_util >= 75:
                recommendations.append(
                    f'Network-wide port utilization at {overall_util:.0f}% - plan expansion'
                )
                expansion_needed = True

            critical_devices = [d for d in device_capacities if d.utilization_percent >= 85]
            if critical_devices:
                recommendations.append(
                    f'{len(critical_devices)} switches at critical capacity (>85% ports used)'
                )

            warning_devices = [d for d in device_capacities if 75 <= d.utilization_percent < 85]
            if warning_devices:
                recommendations.append(
                    f'{len(warning_devices)} switches approaching capacity (75-85% ports used)'
                )

            low_util_devices = [
                d for d in device_capacities if d.utilization_percent < 30 and d.total_ports > 8
            ]
            if low_util_devices:
                recommendations.append(
                    f'{len(low_util_devices)} switches have low utilization (<30%) - '
                    'consider consolidation'
                )

            poe_critical = [
                d
                for d in device_capacities
                if d.poe_utilization_percent and d.poe_utilization_percent >= 85
            ]
            if poe_critical:
                recommendations.append(f'{len(poe_critical)} switches at critical PoE capacity')

            return CapacityReport(
                timestamp=datetime.now().isoformat(),
                total_devices=len(device_capacities),
                total_ports=total_ports,
                used_ports=used_ports,
                available_ports=available_ports,
                overall_utilization=round(overall_util, 1),
                total_poe_budget=total_poe_budget,
                total_poe_used=total_poe_used,
                devices=device_capacities,
                bottlenecks=bottlenecks,
                expansion_needed=expansion_needed,
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
                message=f'Error generating capacity report: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _generate_device_recommendation(
    device_name: str,
    port_util: float,
    poe_util: float,
    available_ports: int,
    poe_available: float,
) -> str | None:
    """Generate recommendation for a device."""
    if port_util >= 95:
        return 'CRITICAL: Ports exhausted - add switch immediately'
    if port_util >= 85:
        return f'WARNING: Only {available_ports} ports available - plan expansion'
    if poe_util >= 95:
        return 'CRITICAL: PoE budget exhausted - add PoE switch'
    if poe_util >= 85:
        return f'WARNING: Only {poe_available:.0f}W PoE available'
    if port_util >= 75:
        return f'MONITOR: {available_ports} ports remaining'
    if port_util < 30 and available_ports > 10:
        return 'Consider consolidation opportunity'
    return None
