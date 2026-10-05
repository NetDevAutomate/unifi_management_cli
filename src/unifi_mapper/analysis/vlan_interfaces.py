"""Match the controller's VLAN networks to the gateway's live interfaces, by subnet.

Pure: no I/O. Ported from the July work's VLAN sampler (a local archive, not in the repo),
logic unchanged. A network's interface is the one whose address lies in the network's
``ip_subnet``, never one assumed from a ``br<vlan>`` naming convention, which survives neither
renumbering nor a gateway migration. Used by ``gateway http --vlan`` (and, later, the VLAN
traffic sampler).
"""

import ipaddress
from typing import Any


# Network purposes that are L3 LAN segments; WAN uplinks and VPN servers have subnets too
# but are not VLANs.
LAN_PURPOSES = ('corporate', 'guest')


def network_vlan_id(network: dict[str, Any]) -> int | None:
    """A network's VLAN ID; an untagged LAN (no ``vlan``, not ``vlan_enabled``) is VLAN 1."""
    vlan_id = network.get('vlan')
    if vlan_id is not None:
        try:
            return int(vlan_id)
        except (TypeError, ValueError):
            return None
    if network.get('purpose') in LAN_PURPOSES and not network.get('vlan_enabled'):
        return 1
    return None


def _iface_addrs(entry: dict[str, Any]) -> list[str]:
    """The local addresses of one ``ip -j addr show`` interface entry."""
    return [str(info['local']) for info in entry.get('addr_info') or [] if info.get('local')]


def resolve_vlan_interfaces(
    networks: list[dict[str, Any]], ip_addr_json: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Match each enabled LAN network to the live interface whose IPv4 address is in it.

    Args:
        networks: The controller's legacy ``rest/networkconf`` records
            (``UniFiClient.get_networks()``).
        ip_addr_json: The gateway's parsed ``ip -j addr show`` output: interface entries with
            ``ifname`` and ``addr_info``. IPv6 and unparsable addresses are ignored.

    Returns:
        ``resolved`` (``{vlan_id, network_name, iface, subnet}`` each) and ``unresolved``
        (``{vlan_id, network_name, subnet}``; ``vlan_id`` None when it can't be derived).
        Every enabled LAN network with a subnet lands in exactly one of them; disabled
        networks and other purposes are out of scope.
    """
    live: list[tuple[str, ipaddress.IPv4Address]] = []
    for entry in ip_addr_json:
        ifname = entry.get('ifname')
        if not ifname:
            continue
        for addr in _iface_addrs(entry):
            try:
                live.append((str(ifname), ipaddress.IPv4Address(addr)))
            except ipaddress.AddressValueError:
                continue

    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for network in networks:
        if network.get('enabled') is False:
            continue
        purpose = network.get('purpose')
        if purpose is not None and purpose not in LAN_PURPOSES:
            continue
        subnet = network.get('ip_subnet')
        if not subnet:
            continue
        vlan_id = network_vlan_id(network)
        name = network.get('name') or (f'VLAN {vlan_id}' if vlan_id is not None else 'unknown')
        if vlan_id is None:
            unresolved.append({'vlan_id': None, 'network_name': name, 'subnet': str(subnet)})
            continue
        try:
            net = ipaddress.IPv4Network(str(subnet), strict=False)
        except ValueError:
            unresolved.append({'vlan_id': vlan_id, 'network_name': name, 'subnet': str(subnet)})
            continue
        match = next((ifname for ifname, ip in live if ip in net), None)
        if match is None:
            unresolved.append({'vlan_id': vlan_id, 'network_name': name, 'subnet': str(net)})
            continue
        resolved.append(
            {'vlan_id': vlan_id, 'network_name': name, 'iface': match, 'subnet': str(net)}
        )
    return {'resolved': resolved, 'unresolved': unresolved}
