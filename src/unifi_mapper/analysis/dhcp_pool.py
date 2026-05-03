"""DHCP pool utilization analysis tool for UniFi networks."""

import ipaddress
from datetime import datetime
from unifi_mapper.core.models import DHCPPoolReport, DHCPPoolStatus
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def check_dhcp_pool_utilization() -> DHCPPoolReport:
    """Check DHCP pool utilization across all networks.

    Analyzes each DHCP-enabled network to calculate pool size from the
    configured IP range, counts active clients per pool, and flags pools
    approaching exhaustion.

    Returns:
        DHCPPoolReport with per-network pool utilization

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            networks = await client.get_networks()
            clients = await client.get_clients()

            pools, warnings, recommendations = _analyze_dhcp_pools(networks, clients)

            total_pool = sum(p.pool_size for p in pools)
            total_clients = sum(p.active_clients for p in pools)

            return DHCPPoolReport(
                timestamp=datetime.now().isoformat(),
                networks_analyzed=len(pools),
                total_pool_size=total_pool,
                total_active_clients=total_clients,
                pools=pools,
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
                message=f'Error checking DHCP pool utilization: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _analyze_dhcp_pools(
    networks: list[dict],
    clients: list[dict],
) -> tuple[list[DHCPPoolStatus], list[str], list[str]]:
    """Pure analysis function for DHCP pool utilization."""
    # Build client count per network_id
    clients_by_network: dict[str, int] = {}
    for c in clients:
        nid = c.get('network_id', '')
        if nid:
            clients_by_network[nid] = clients_by_network.get(nid, 0) + 1

    pools: list[DHCPPoolStatus] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    for network in networks:
        if not network.get('dhcpd_enabled', False):
            continue

        pool_start = network.get('dhcpd_start', '')
        pool_stop = network.get('dhcpd_stop', '')
        if not pool_start or not pool_stop:
            continue

        # Calculate pool size using ipaddress module
        try:
            start_ip = ipaddress.IPv4Address(pool_start)
            stop_ip = ipaddress.IPv4Address(pool_stop)
            pool_size = int(stop_ip) - int(start_ip) + 1
        except (ipaddress.AddressValueError, ValueError):
            continue

        if pool_size <= 0:
            continue

        network_id = network.get('_id', '')
        network_name = network.get('name', 'Unknown')
        vlan_id = network.get('vlan')
        active_clients = clients_by_network.get(network_id, 0)
        utilization = (active_clients / pool_size) * 100 if pool_size > 0 else 0.0

        # Determine status
        if utilization >= 90:
            status = 'CRITICAL'
            warnings.append(f'{network_name}: DHCP pool at {utilization:.0f}% — near exhaustion')
            recommendations.append(
                f'Expand DHCP range for {network_name} or add static assignments'
            )
        elif utilization >= 80:
            status = 'WARNING'
            warnings.append(f'{network_name}: DHCP pool at {utilization:.0f}%')
        else:
            status = 'OK'

        pools.append(
            DHCPPoolStatus(
                network_id=network_id,
                network_name=network_name,
                vlan_id=vlan_id,
                pool_start=pool_start,
                pool_stop=pool_stop,
                pool_size=pool_size,
                active_clients=active_clients,
                utilization_percent=round(utilization, 1),
                status=status,
            )
        )

    return pools, warnings, recommendations
