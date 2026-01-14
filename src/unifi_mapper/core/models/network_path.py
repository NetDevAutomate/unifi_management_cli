"""Network path models for traceroute results."""

from pydantic import BaseModel, Field
from typing import Literal
from unifi_mapper.core.models.firewall import FirewallRule


class PathHop(BaseModel):
    """Single hop in a network path."""

    hop_number: int = Field(description='Hop sequence number (1-based)')
    device_mac: str = Field(description='Device MAC at this hop')
    device_name: str = Field(description='Device name at this hop')
    device_type: Literal['switch', 'ap', 'gateway', 'client'] = Field(description='Device type')
    interface: str = Field(description='Interface name (e.g., "port24", "eth0")')
    vlan: int | None = Field(default=None, description='VLAN at this hop')
    latency_ms: float | None = Field(default=None, description='Latency to this hop (ms)')

    # Firewall check at this hop
    firewall_checked: bool = Field(
        default=False,
        description='Whether firewall rules were checked at this hop',
    )
    firewall_result: Literal['allow', 'deny', 'unknown'] | None = Field(
        default=None,
        description='Firewall verdict at this hop',
    )
    blocking_rule: str | None = Field(
        default=None,
        description='Name of blocking rule if denied',
    )

    @property
    def is_blocked(self) -> bool:
        """Check if traffic is blocked at this hop."""
        return self.firewall_result == 'deny'

    @property
    def display_label(self) -> str:
        """Get display label for this hop."""
        vlan_info = f' [VLAN {self.vlan}]' if self.vlan else ''
        return f'{self.device_name}:{self.interface}{vlan_info}'


class NetworkPath(BaseModel):
    """Complete network path between two endpoints."""

    source: str = Field(description='Source identifier (IP, MAC, or name)')
    source_resolved: str = Field(description='Resolved source MAC')
    source_name: str = Field(default='', description='Resolved source device name')
    destination: str = Field(description='Destination identifier')
    destination_resolved: str = Field(description='Resolved destination MAC')
    destination_name: str = Field(default='', description='Resolved destination device name')

    hops: list[PathHop] = Field(
        default_factory=list, description='Path hops from source to destination'
    )
    total_latency_ms: float | None = Field(
        default=None,
        description='Total path latency (ms)',
    )

    # Overall firewall verdict
    firewall_verdict: Literal['allow', 'deny', 'unknown'] = Field(
        default='unknown', description='Overall firewall verdict for this path'
    )
    blocking_rules: list[FirewallRule] = Field(
        default_factory=list,
        description='Rules blocking this path (if denied)',
    )

    # Path characteristics
    crosses_vlans: bool = Field(default=False, description='Path crosses VLAN boundaries')
    vlans_traversed: list[int] = Field(
        default_factory=list,
        description='VLANs traversed in order',
    )
    is_l2_only: bool = Field(default=True, description='Path is L2 only (same VLAN)')
    is_l3_routed: bool = Field(default=False, description='Path requires L3 routing')

    @property
    def hop_count(self) -> int:
        """Get number of hops in path."""
        return len(self.hops)

    @property
    def is_blocked(self) -> bool:
        """Check if path is blocked by firewall."""
        return self.firewall_verdict == 'deny'

    @property
    def vlan_crossing_count(self) -> int:
        """Count number of VLAN boundary crossings."""
        if len(self.vlans_traversed) <= 1:
            return 0
        crossings = 0
        for i in range(1, len(self.vlans_traversed)):
            if self.vlans_traversed[i] != self.vlans_traversed[i - 1]:
                crossings += 1
        return crossings
