"""Port model for switch ports."""

from pydantic import BaseModel, Field
from typing import Literal


class Port(BaseModel):
    """Switch port with configuration and status."""

    port_idx: int = Field(description='Port index (1-based)')
    name: str | None = Field(default=None, description='Port name/label')
    enabled: bool = Field(default=True, description='Port administratively enabled')
    up: bool = Field(default=False, description='Port link status (up/down)')
    speed: int = Field(default=0, description='Link speed in Mbps (10, 100, 1000, 10000)')
    duplex: Literal['full', 'half', 'unknown'] = Field(
        default='unknown', description='Duplex mode'
    )
    poe_mode: str | None = Field(
        default=None, description='PoE mode (off, auto, pasv24, passthrough)'
    )
    poe_power: float | None = Field(default=None, description='PoE power draw in watts')
    vlan: int = Field(default=1, description='Native/untagged VLAN ID')
    tagged_vlans: list[int] = Field(
        default_factory=list,
        description='Tagged VLANs (trunk mode)',
    )
    is_trunk: bool = Field(default=False, description='True if port carries multiple VLANs')
    connected_mac: str | None = Field(
        default=None,
        description='MAC of connected device',
    )
    connected_device_name: str | None = Field(
        default=None,
        description='Name of connected device',
    )

    # Parent device info
    device_mac: str | None = Field(default=None, description='MAC of switch this port belongs to')
    device_name: str | None = Field(default=None, description='Name of switch')

    # Statistics
    rx_bytes: int = Field(default=0, description='Received bytes')
    tx_bytes: int = Field(default=0, description='Transmitted bytes')
    rx_errors: int = Field(default=0, description='Receive errors')
    tx_errors: int = Field(default=0, description='Transmit errors')
    rx_dropped: int = Field(default=0, description='Receive dropped packets')
    tx_dropped: int = Field(default=0, description='Transmit dropped packets')

    @property
    def has_errors(self) -> bool:
        """Check if port has any errors."""
        return (self.rx_errors + self.tx_errors + self.rx_dropped + self.tx_dropped) > 0

    @property
    def is_half_duplex(self) -> bool:
        """Check if port is running in half duplex (problematic)."""
        return self.duplex == 'half' and self.up

    @property
    def display_label(self) -> str:
        """Get display label for port."""
        if self.name:
            return f'{self.name} (port {self.port_idx})'
        return f'Port {self.port_idx}'
