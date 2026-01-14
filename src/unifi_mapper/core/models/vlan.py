"""VLAN model for virtual LAN configuration."""

from pydantic import BaseModel, Field


class VLAN(BaseModel):
    """Virtual LAN configuration."""

    id: int = Field(description='VLAN ID (1-4094)')
    name: str = Field(description='VLAN name')
    subnet: str | None = Field(default=None, description='Subnet CIDR (e.g., 192.168.1.0/24)')
    gateway: str | None = Field(default=None, description='Default gateway IP')
    dhcp_enabled: bool = Field(default=False, description='DHCP server enabled')
    dhcp_start: str | None = Field(default=None, description='DHCP range start')
    dhcp_end: str | None = Field(default=None, description='DHCP range end')
    purpose: str | None = Field(
        default=None,
        description='VLAN purpose (corporate, guest, iot, voip, etc.)',
    )
    domain_name: str | None = Field(default=None, description='Domain name for DHCP')
    igmp_snooping: bool = Field(default=False, description='IGMP snooping enabled')
    network_id: str | None = Field(default=None, description='UniFi network ID')

    # Computed stats
    port_count: int = Field(default=0, description='Number of ports using this VLAN')
    client_count: int = Field(default=0, description='Number of clients on this VLAN')

    @property
    def is_default(self) -> bool:
        """Check if this is the default VLAN."""
        return self.id == 1

    @property
    def display_name(self) -> str:
        """Get display name with VLAN ID."""
        return f'{self.name} (VLAN {self.id})'
