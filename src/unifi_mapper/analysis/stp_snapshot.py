"""STP topology snapshot and diff helpers."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from unifi_mapper.core.models.stp import STPTopology


class STPSnapshot(BaseModel):
    """Serializable STP topology snapshot."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    root_bridge_id: str | None = None
    root_bridge_name: str | None = None
    switches: dict[str, dict[str, object]] = Field(default_factory=dict)
    ports: dict[str, dict[str, object]] = Field(default_factory=dict)
    connections: set[str] = Field(default_factory=set)


class STPSnapshotChange(BaseModel):
    """A change detected between STP snapshots."""

    change_type: str
    subject: str
    before: object = None
    after: object = None


class STPSnapshotDiff(BaseModel):
    """Diff between two STP snapshots."""

    changes: list[STPSnapshotChange] = Field(default_factory=lambda: [])


def snapshot_stp_topology(topology: STPTopology) -> STPSnapshot:
    """Build a compact serializable snapshot from an STP topology."""
    switches: dict[str, dict[str, object]] = {}
    ports: dict[str, dict[str, object]] = {}
    for switch in topology.switches:
        switches[switch.device_id] = {
            'name': switch.name,
            'priority': switch.current_priority,
        }
        for port in switch.port_states:
            ports[f'{switch.device_id}:{port.port_idx}'] = {
                'state': port.stp_state.value,
                'path_cost': port.path_cost,
                'link_speed_mbps': port.link_speed_mbps,
            }
    connections = {
        f'{conn.from_device_id}:{conn.from_port_idx}->{conn.to_device_id}:{conn.to_port_idx or ""}'
        for conn in topology.connections
    }
    return STPSnapshot(
        root_bridge_id=topology.root_bridge_id,
        root_bridge_name=topology.root_bridge_name,
        switches=switches,
        ports=ports,
        connections=connections,
    )


def diff_stp_snapshots(before: STPSnapshot, after: STPSnapshot) -> STPSnapshotDiff:
    """Diff two STP snapshots."""
    changes: list[STPSnapshotChange] = []
    if before.root_bridge_id != after.root_bridge_id:
        changes.append(
            STPSnapshotChange(
                change_type='root_bridge_changed',
                subject='root_bridge',
                before=before.root_bridge_name,
                after=after.root_bridge_name,
            )
        )
    for switch_id in sorted(set(before.switches) | set(after.switches)):
        old = before.switches.get(switch_id)
        new = after.switches.get(switch_id)
        if old is None or new is None:
            changes.append(
                STPSnapshotChange(
                    change_type='switch_presence_changed', subject=switch_id, before=old, after=new
                )
            )
            continue
        if old.get('priority') != new.get('priority'):
            changes.append(
                STPSnapshotChange(
                    change_type='priority_changed',
                    subject=switch_id,
                    before=old.get('priority'),
                    after=new.get('priority'),
                )
            )
    for port_id in sorted(set(before.ports) | set(after.ports)):
        old = before.ports.get(port_id)
        new = after.ports.get(port_id)
        if old is None or new is None:
            changes.append(
                STPSnapshotChange(
                    change_type='port_presence_changed', subject=port_id, before=old, after=new
                )
            )
            continue
        for key, change_type in (
            ('state', 'port_state_changed'),
            ('path_cost', 'path_cost_changed'),
            ('link_speed_mbps', 'link_speed_changed'),
        ):
            if old.get(key) != new.get(key):
                changes.append(
                    STPSnapshotChange(
                        change_type=change_type,
                        subject=port_id,
                        before=old.get(key),
                        after=new.get(key),
                    )
                )
    if before.connections != after.connections:
        changes.append(
            STPSnapshotChange(
                change_type='connections_changed',
                subject='connections',
                before=sorted(before.connections),
                after=sorted(after.connections),
            )
        )
    return STPSnapshotDiff(changes=changes)
