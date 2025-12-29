"""Pydantic models for port mirroring (SPAN) operations."""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


class MirrorCapability(str, Enum):
    """Port mirroring capability levels based on device hardware."""

    NONE = 'none'
    BASIC = 'basic'  # Single source to destination
    ADVANCED = 'advanced'  # Multiple sources, VLAN mirroring
    ENTERPRISE = 'enterprise'  # All features


class MirrorSession(BaseModel):
    """Represents an active port mirroring (SPAN) session."""

    session_id: str = Field(description='Unique session identifier')
    device_id: str = Field(description='UniFi device ID')
    device_name: str = Field(description='Human-readable device name')
    source_port_idx: int = Field(description='Source port index to monitor')
    destination_port_idx: int = Field(description='Destination port for mirrored traffic')
    source_port_name: str = Field(default='', description='Source port name')
    destination_port_name: str = Field(default='', description='Destination port name')
    enabled: bool = Field(default=True, description='Whether session is active')
    description: Optional[str] = Field(default=None, description='Session description')


class DeviceMirrorCapabilities(BaseModel):
    """Hardware capabilities for port mirroring on a device."""

    device_id: str = Field(description='UniFi device ID')
    device_name: str = Field(description='Human-readable device name')
    model: str = Field(description='Device model')
    capability_level: MirrorCapability = Field(description='Mirroring capability level')
    max_sessions: int = Field(description='Maximum concurrent mirror sessions')
    supports_bidirectional: bool = Field(
        default=True, description='Supports bidirectional mirroring'
    )
    supports_vlan_mirror: bool = Field(default=False, description='Supports VLAN-based mirroring')
    available_ports: list[int] = Field(default_factory=list, description='Available port indices')
    restrictions: list[str] = Field(
        default_factory=list, description='Device-specific restrictions'
    )


class MirrorSessionResult(BaseModel):
    """Result of a mirror session operation."""

    success: bool = Field(description='Whether operation succeeded')
    message: str = Field(description='Result message')
    session: Optional[MirrorSession] = Field(
        default=None, description='Session details if successful'
    )
    errors: list[str] = Field(default_factory=list, description='Error messages')
    warnings: list[str] = Field(default_factory=list, description='Warning messages')


class MirrorReport(BaseModel):
    """Comprehensive port mirroring report for a device."""

    device_id: str = Field(description='UniFi device ID')
    device_name: str = Field(description='Human-readable device name')
    capabilities: DeviceMirrorCapabilities = Field(description='Device capabilities')
    active_sessions: list[MirrorSession] = Field(
        default_factory=list, description='Active sessions'
    )
    available_session_slots: int = Field(description='Remaining session slots')
    report_time: datetime = Field(
        default_factory=datetime.now, description='Report generation time'
    )
