"""Device model for UniFi network devices."""

from pydantic import BaseModel, Field
from typing import Literal


class Device(BaseModel):
    """UniFi network device.

    Represents switches, access points, gateways, and clients.
    """

    mac: str = Field(description='MAC address (primary identifier)')
    name: str = Field(description='Device name/hostname')
    model: str = Field(description='Hardware model (e.g., USW-Pro-48-PoE)')
    ip: str | None = Field(default=None, description='IP address if assigned')
    type: Literal['switch', 'ap', 'gateway', 'client'] = Field(description='Device type')
    uptime: int = Field(default=0, description='Uptime in seconds')
    connected_to: str | None = Field(
        default=None,
        description='MAC of parent device (switch/AP this connects to)',
    )
    port_idx: int | None = Field(
        default=None,
        description='Port index on parent device',
    )
    site_id: str | None = Field(default=None, description='Site identifier')

    # System metrics (optional, populated by system_load tool)
    cpu_percent: float | None = Field(default=None, description='CPU usage %')
    memory_percent: float | None = Field(default=None, description='Memory usage %')
    load_average: float | None = Field(default=None, description='1-min load average')

    @property
    def is_infrastructure(self) -> bool:
        """Check if device is network infrastructure (not a client)."""
        return self.type in ('switch', 'ap', 'gateway')

    @property
    def display_name(self) -> str:
        """Get display name, falling back to MAC if name is empty."""
        return self.name if self.name else self.mac
