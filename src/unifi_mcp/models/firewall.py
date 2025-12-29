"""Firewall rule model."""

from pydantic import BaseModel, Field
from typing import Literal


class FirewallRule(BaseModel):
    """Firewall rule definition."""

    id: str = Field(description='Rule unique identifier')
    name: str = Field(description='Rule name/description')
    action: Literal['allow', 'deny', 'reject'] = Field(description='Rule action')
    enabled: bool = Field(default=True, description='Rule is active')

    # Source
    source_type: Literal['any', 'network', 'ip', 'port_group', 'address_group'] = Field(
        default='any', description='Source specification type'
    )
    source: str = Field(default='any', description='Source (VLAN name, IP/CIDR, or "any")')
    source_port: str | None = Field(default=None, description='Source port or range')

    # Destination
    dest_type: Literal['any', 'network', 'ip', 'port_group', 'address_group'] = Field(
        default='any', description='Destination specification type'
    )
    destination: str = Field(
        default='any', description='Destination (VLAN name, IP/CIDR, or "any")'
    )
    dest_port: str | None = Field(
        default=None,
        description='Destination port or range (e.g., "80", "443", "1000-2000")',
    )

    # Protocol
    protocol: Literal['all', 'tcp', 'udp', 'icmp', 'tcp_udp'] = Field(
        default='all',
        description='Protocol',
    )

    # Metadata
    order: int = Field(default=0, description='Rule order/priority (lower = higher priority)')
    hit_count: int | None = Field(default=None, description='Number of rule matches')
    rule_set: str = Field(
        default='LAN_IN',
        description='Rule set (LAN_IN, LAN_OUT, WAN_IN, WAN_OUT, GUEST_IN, etc.)',
    )
    site_id: str | None = Field(default=None, description='Site identifier')

    @property
    def is_blocking(self) -> bool:
        """Check if rule blocks traffic."""
        return self.action in ('deny', 'reject')

    @property
    def display_summary(self) -> str:
        """Get human-readable summary of the rule."""
        action_icon = '✅' if self.action == 'allow' else '❌'
        proto = self.protocol if self.protocol != 'all' else ''
        port = f':{self.dest_port}' if self.dest_port else ''
        return f'{action_icon} {self.name}: {self.source} → {self.destination}{port} ({proto})'
