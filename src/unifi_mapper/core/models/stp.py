"""Pydantic models for STP (Spanning Tree Protocol) topology analysis."""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class STPPortState(str, Enum):
    """STP port states per IEEE 802.1D/802.1w.

    RSTP (802.1w) reduced the original 5 states to 3 operational states,
    but we track all for compatibility with different switch firmware.
    """

    FORWARDING = 'forwarding'  # Active, passing traffic
    BLOCKING = 'blocking'  # STP blocking state (classic STP)
    DISCARDING = 'discarding'  # RSTP discarding state (blocks traffic)
    LEARNING = 'learning'  # Learning MACs, not yet forwarding
    LISTENING = 'listening'  # Transitional state in classic STP
    DISABLED = 'disabled'  # Port administratively disabled


class STPRole(str, Enum):
    """STP port roles per IEEE 802.1w (RSTP).

    Understanding roles is crucial for STP optimization:
    - Root ports point toward the root bridge
    - Designated ports point away from the root bridge
    - Alternate/Backup ports are blocked redundant paths
    """

    ROOT = 'root'  # Best path to root bridge
    DESIGNATED = 'designated'  # Best path from root for this segment
    ALTERNATE = 'alternate'  # Backup path to root (RSTP)
    BACKUP = 'backup'  # Backup path on same segment (RSTP)
    DISABLED = 'disabled'  # Not participating in STP


class STPPortConfig(BaseModel):
    """STP configuration and state for a single switch port."""

    port_idx: int = Field(description='Port index on the switch')
    port_name: str = Field(default='', description='Port name/alias')
    stp_state: STPPortState = Field(
        default=STPPortState.FORWARDING, description='Current STP port state'
    )
    stp_role: STPRole = Field(default=STPRole.DESIGNATED, description='Current STP port role')
    path_cost: int = Field(default=0, description='STP path cost for this port (lower = better)')
    connected_device: str | None = Field(
        default=None, description='Name or MAC of connected device (from LLDP)'
    )
    connected_device_id: str | None = Field(
        default=None, description='Device ID of connected device'
    )
    is_uplink: bool = Field(
        default=False, description='Whether this port connects to a higher-tier switch'
    )
    is_up: bool = Field(default=False, description='Whether the physical link is up')
    enabled: bool = Field(default=True, description='Whether the port is administratively enabled')
    link_speed_mbps: int = Field(default=0, description='Current negotiated speed in Mbps')
    full_duplex: bool = Field(default=True, description='Whether the link is full duplex')
    rx_errors: int = Field(default=0, description='Receive error counter')
    tx_errors: int = Field(default=0, description='Transmit error counter')
    rx_dropped: int = Field(default=0, description='Receive dropped packet counter')
    tx_dropped: int = Field(default=0, description='Transmit dropped packet counter')
    crc_errors: int = Field(default=0, description='CRC error counter')
    stp_tc_count: int = Field(default=0, description='STP topology-change counter')


def _empty_port_configs() -> list[STPPortConfig]:
    return []


def _empty_port_indices() -> list[int]:
    return []


class SwitchSTPConfig(BaseModel):
    """STP configuration for a single switch."""

    device_id: str = Field(description='UniFi device ID')
    name: str = Field(description='Switch name')
    mac: str = Field(description='Switch MAC address')
    model: str = Field(default='', description='Switch model')
    current_priority: int = Field(
        default=32768, description='Current bridge priority (lower = more likely to be root)'
    )
    optimal_priority: int | None = Field(
        default=None, description='Recommended optimal priority based on topology'
    )
    hierarchy_tier: int = Field(
        default=2, description='Network tier: 0=Core, 1=Distribution, 2=Access'
    )
    is_root_bridge: bool = Field(
        default=False, description='Whether this switch is currently the STP root'
    )
    root_port_idx: int | None = Field(
        default=None, description='Port index pointing toward root bridge'
    )
    root_eligible: bool = Field(
        default=True, description='Whether switch may be elected STP root'
    )
    root_preference: int = Field(
        default=100, description='Lower value is preferred among eligible roots'
    )
    root_eligibility_reason: str = Field(
        default='', description='Why the switch is or is not root eligible'
    )
    port_states: list[STPPortConfig] = Field(
        default_factory=_empty_port_configs, description='STP state for each port'
    )
    uplink_ports: list[int] = Field(
        default_factory=_empty_port_indices,
        description='Port indices that are uplinks to higher tiers',
    )
    connected_to_gateway: bool = Field(
        default=False, description='Whether directly connected to gateway/router'
    )


class STPConnection(BaseModel):
    """Represents a connection between two switches in STP topology."""

    from_device_id: str = Field(description='Source device ID')
    from_device_name: str = Field(description='Source device name')
    from_port_idx: int = Field(description='Source port index')
    to_device_id: str = Field(description='Destination device ID')
    to_device_name: str = Field(description='Destination device name')
    to_port_idx: int | None = Field(default=None, description='Destination port index (if known)')
    stp_state: STPPortState = Field(
        default=STPPortState.FORWARDING,
        description='STP state of the connection (from source port)',
    )
    path_cost: int = Field(default=0, description='Path cost of this link')
    is_blocked: bool = Field(default=False, description='Whether this link is blocked by STP')


def _empty_switch_configs() -> list[SwitchSTPConfig]:
    return []


def _empty_stp_connections() -> list[STPConnection]:
    return []


class STPTopology(BaseModel):
    """Complete STP topology for the network."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description='When topology was discovered',
    )
    root_bridge_id: str | None = Field(
        default=None, description='Device ID of current root bridge'
    )
    root_bridge_name: str | None = Field(default=None, description='Name of current root bridge')
    root_bridge_priority: int = Field(default=32768, description='Priority of current root bridge')
    gateway_id: str | None = Field(default=None, description='Device ID of the network gateway')
    gateway_name: str | None = Field(default=None, description='Name of the network gateway')
    switches: list[SwitchSTPConfig] = Field(
        default_factory=_empty_switch_configs,
        description='All switches with their STP configuration',
    )
    connections: list[STPConnection] = Field(
        default_factory=_empty_stp_connections,
        description='All inter-switch connections',
    )
    loops_detected: bool = Field(
        default=False, description='Whether potential STP loops were detected'
    )
    blocked_ports_count: int = Field(
        default=0, description='Number of ports in blocking/discarding state'
    )


class STPChange(BaseModel):
    """A recommended STP configuration change."""

    device_id: str = Field(description='Device ID to change')
    device_name: str = Field(description='Device name')
    current_priority: int = Field(description='Current bridge priority')
    new_priority: int = Field(description='Recommended new priority')
    hierarchy_tier: int = Field(description='Network tier (0=Core, 1=Dist, 2=Access)')
    reason: str = Field(description='Explanation for the change')


def _empty_stp_changes() -> list[STPChange]:
    return []


def _empty_strings() -> list[str]:
    return []


class STPOptimizationReport(BaseModel):
    """Complete STP optimization report with diagrams and recommendations."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(), description='When report was generated'
    )
    switches_analyzed: int = Field(description='Number of switches analyzed')
    current_root: str | None = Field(default=None, description='Current root bridge name')
    current_root_priority: int = Field(default=32768, description='Current root bridge priority')
    optimal_root: str | None = Field(default=None, description='Recommended root bridge name')
    optimal_root_reason: str = Field(default='', description='Why this switch should be root')
    changes_required: int = Field(description='Number of priority changes needed')
    changes: list[STPChange] = Field(
        default_factory=_empty_stp_changes, description='List of recommended changes'
    )
    topology: STPTopology = Field(description='Current STP topology')
    issues: list[str] = Field(
        default_factory=_empty_strings, description='Issues found in current configuration'
    )
    recommendations: list[str] = Field(
        default_factory=_empty_strings, description='General recommendations'
    )
    current_diagram: str = Field(default='', description='Mermaid diagram of current topology')
    optimal_diagram: str = Field(default='', description='Mermaid diagram of optimal topology')


class STPValidationFinding(BaseModel):
    """A validation finding for STP and 10G expansion readiness."""

    severity: str = Field(description='INFO, WARNING, or CRITICAL')
    category: str = Field(description='Finding category')
    message: str = Field(description='Human-readable finding')
    recommendation: str = Field(description='Recommended action')
    device_name: str | None = Field(default=None, description='Related device name')
    port_idx: int | None = Field(default=None, description='Related port index')


class STPPathCostFinding(BaseModel):
    """A finding from STP path-cost sanity checks."""

    severity: str = Field(description='INFO, WARNING, or CRITICAL')
    device_name: str = Field(description='Switch name')
    port_idx: int = Field(description='Port index on the switch')
    link_speed_mbps: int = Field(description='Negotiated link speed in Mbps')
    path_cost: int = Field(description='Configured or reported STP path cost')
    expected_long_cost: int = Field(description='Expected IEEE long path cost')
    message: str = Field(description='Human-readable finding')
    recommendation: str = Field(description='Recommended action')


def _empty_validation_findings() -> list[STPValidationFinding]:
    return []


class STPNetworkValidationReport(BaseModel):
    """Validation report for local UniFi STP health and 10G expansion readiness."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(), description='When report was generated'
    )
    planned_flex_xg_switches: int = Field(description='Number of USW Flex XG switches planned')
    target_speed_mbps: int = Field(default=10000, description='Target uplink speed in Mbps')
    switches_analyzed: int = Field(description='Number of switches analyzed')
    inter_switch_links: int = Field(description='Number of discovered switch-to-switch links')
    ten_gig_links: int = Field(description='Number of discovered 10G switch-to-switch links')
    blocked_ports_count: int = Field(description='Number of blocked/discarding STP ports')
    stp_changes_required: int = Field(description='Number of recommended STP priority changes')
    validation_passed: bool = Field(description='True when no critical findings exist')
    readiness: str = Field(description='READY, READY_WITH_WARNINGS, or NOT_READY')
    findings: list[STPValidationFinding] = Field(default_factory=_empty_validation_findings)
    stp_changes: list[STPChange] = Field(default_factory=_empty_stp_changes)


# STP Priority Standards
STP_PRIORITY_CORE = 4096  # Directly connected to gateway
STP_PRIORITY_DISTRIBUTION = 8192  # One hop from core
STP_PRIORITY_ACCESS_BASE = 16384  # Two+ hops from core
STP_PRIORITY_DEFAULT = 32768  # UniFi default
STP_PRIORITY_INCREMENT = 4096  # Standard increment between tiers
