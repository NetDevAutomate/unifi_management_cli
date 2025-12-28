#!/usr/bin/env python3
"""
Configuration Backup & Diff for UniFi Networks.

Provides configuration management capabilities:
- Automated configuration snapshots
- Config diff between snapshots
- Export/import configuration profiles
- Golden config comparison
- Rollback capability
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BackupMetadata:
    """Metadata for a configuration backup."""

    backup_id: str
    timestamp: datetime
    description: str = ""
    site: str = "default"
    devices_count: int = 0
    networks_count: int = 0
    port_profiles_count: int = 0
    file_path: Optional[Path] = None
    checksum: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "backup_id": self.backup_id,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "site": self.site,
            "devices_count": self.devices_count,
            "networks_count": self.networks_count,
            "port_profiles_count": self.port_profiles_count,
            "file_path": str(self.file_path) if self.file_path else None,
            "checksum": self.checksum,
        }


@dataclass
class ConfigChange:
    """A single configuration change."""

    change_type: str  # added, removed, modified
    path: str  # Configuration path (e.g., "devices.Switch1.port_overrides.5")
    old_value: Any = None
    new_value: Any = None
    device_name: str = ""
    severity: str = "info"  # info, warning, critical

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "change_type": self.change_type,
            "path": self.path,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "device_name": self.device_name,
            "severity": self.severity,
        }


@dataclass
class ConfigDiff:
    """Configuration difference between two backups."""

    baseline_id: str
    compare_id: str
    baseline_timestamp: datetime = field(default_factory=datetime.now)
    compare_timestamp: datetime = field(default_factory=datetime.now)

    # Changes
    changes: List[ConfigChange] = field(default_factory=list)
    devices_added: List[str] = field(default_factory=list)
    devices_removed: List[str] = field(default_factory=list)
    devices_modified: List[str] = field(default_factory=list)

    # Summary
    total_changes: int = 0
    critical_changes: int = 0
    warning_changes: int = 0

    def add_change(self, change: ConfigChange) -> None:
        """Add a change."""
        self.changes.append(change)
        self.total_changes += 1

        if change.severity == "critical":
            self.critical_changes += 1
        elif change.severity == "warning":
            self.warning_changes += 1

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return self.total_changes > 0

    def summary(self) -> Dict[str, Any]:
        """Get diff summary."""
        return {
            "baseline_id": self.baseline_id,
            "compare_id": self.compare_id,
            "baseline_timestamp": self.baseline_timestamp.isoformat(),
            "compare_timestamp": self.compare_timestamp.isoformat(),
            "has_changes": self.has_changes,
            "total_changes": self.total_changes,
            "critical_changes": self.critical_changes,
            "warning_changes": self.warning_changes,
            "devices_added": len(self.devices_added),
            "devices_removed": len(self.devices_removed),
            "devices_modified": len(self.devices_modified),
        }


class ConfigBackup:
    """
    Configuration Backup Manager for UniFi networks.

    Provides:
    - Point-in-time configuration snapshots
    - Configuration comparison (diff)
    - Export/import functionality
    - Change tracking
    """

    def __init__(
        self,
        api_client,
        site: str = "default",
        backup_dir: Optional[Path] = None,
    ):
        """
        Initialize Config Backup manager.

        Args:
            api_client: UniFi API client
            site: UniFi site name
            backup_dir: Directory for storing backups
        """
        self.api_client = api_client
        self.site = site
        self.backup_dir = backup_dir or Path.home() / ".unifi_mapper" / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self._backups_index: Dict[str, BackupMetadata] = {}
        self._load_backup_index()

    def _load_backup_index(self) -> None:
        """Load backup index from disk."""
        index_file = self.backup_dir / "index.json"
        if index_file.exists():
            try:
                with open(index_file, "r") as f:
                    data = json.load(f)
                    for entry in data.get("backups", []):
                        metadata = BackupMetadata(
                            backup_id=entry["backup_id"],
                            timestamp=datetime.fromisoformat(entry["timestamp"]),
                            description=entry.get("description", ""),
                            site=entry.get("site", "default"),
                            devices_count=entry.get("devices_count", 0),
                            networks_count=entry.get("networks_count", 0),
                            port_profiles_count=entry.get("port_profiles_count", 0),
                            file_path=Path(entry["file_path"]) if entry.get("file_path") else None,
                            checksum=entry.get("checksum", ""),
                        )
                        self._backups_index[metadata.backup_id] = metadata
            except Exception as e:
                logger.error(f"Failed to load backup index: {e}")

    def _save_backup_index(self) -> None:
        """Save backup index to disk."""
        index_file = self.backup_dir / "index.json"
        try:
            data = {
                "backups": [m.to_dict() for m in self._backups_index.values()]
            }
            with open(index_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save backup index: {e}")

    def _get_full_config(self) -> Dict[str, Any]:
        """Get full network configuration."""
        config = {
            "timestamp": datetime.now().isoformat(),
            "site": self.site,
            "devices": {},
            "networks": [],
            "port_profiles": [],
            "firewall_rules": [],
        }

        try:
            # Get devices
            result = self.api_client.get_devices(self.site)
            if result and "data" in result:
                for device in result["data"]:
                    device_name = device.get("name", device.get("model", device["_id"]))
                    config["devices"][device_name] = {
                        "_id": device["_id"],
                        "name": device_name,
                        "model": device.get("model", ""),
                        "mac": device.get("mac", ""),
                        "ip": device.get("ip", ""),
                        "version": device.get("version", ""),
                        "type": device.get("type", ""),
                        "port_overrides": device.get("port_overrides", []),
                        "stp_priority": device.get("stp_priority"),
                        "config": device.get("config", {}),
                    }

            # Get networks
            if self.api_client.is_unifi_os:
                net_endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/networkconf"
            else:
                net_endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/networkconf"

            def _fetch_networks():
                return self.api_client.session.get(net_endpoint, timeout=self.api_client.timeout)

            response = self.api_client._retry_request(_fetch_networks)
            if response and response.status_code == 200:
                config["networks"] = response.json().get("data", [])

            # Get port profiles
            if self.api_client.is_unifi_os:
                profile_endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/portconf"
            else:
                profile_endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/portconf"

            def _fetch_profiles():
                return self.api_client.session.get(profile_endpoint, timeout=self.api_client.timeout)

            response = self.api_client._retry_request(_fetch_profiles)
            if response and response.status_code == 200:
                config["port_profiles"] = response.json().get("data", [])

        except Exception as e:
            logger.error(f"Failed to get full config: {e}")

        return config

    def _calculate_checksum(self, config: Dict[str, Any]) -> str:
        """Calculate checksum for configuration."""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    def create_backup(self, description: str = "") -> BackupMetadata:
        """
        Create a new configuration backup.

        Args:
            description: Optional description for the backup

        Returns:
            BackupMetadata for the created backup
        """
        logger.info("Creating configuration backup...")

        # Get full configuration
        config = self._get_full_config()

        # Generate backup ID and metadata
        timestamp = datetime.now()
        backup_id = f"backup_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        checksum = self._calculate_checksum(config)

        # Save to file
        backup_file = self.backup_dir / f"{backup_id}.json"
        with open(backup_file, "w") as f:
            json.dump(config, f, indent=2, default=str)

        # Create metadata
        metadata = BackupMetadata(
            backup_id=backup_id,
            timestamp=timestamp,
            description=description or f"Automatic backup at {timestamp.strftime('%Y-%m-%d %H:%M')}",
            site=self.site,
            devices_count=len(config.get("devices", {})),
            networks_count=len(config.get("networks", [])),
            port_profiles_count=len(config.get("port_profiles", [])),
            file_path=backup_file,
            checksum=checksum,
        )

        # Update index
        self._backups_index[backup_id] = metadata
        self._save_backup_index()

        logger.info(
            f"Backup created: {backup_id} "
            f"({metadata.devices_count} devices, {metadata.networks_count} networks)"
        )

        return metadata

    def list_backups(self) -> List[BackupMetadata]:
        """List all available backups."""
        return sorted(
            self._backups_index.values(),
            key=lambda m: m.timestamp,
            reverse=True,
        )

    def get_backup(self, backup_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a backup by ID.

        Args:
            backup_id: Backup ID to load

        Returns:
            Configuration dictionary or None
        """
        metadata = self._backups_index.get(backup_id)
        if not metadata or not metadata.file_path:
            logger.error(f"Backup not found: {backup_id}")
            return None

        if not metadata.file_path.exists():
            logger.error(f"Backup file missing: {metadata.file_path}")
            return None

        try:
            with open(metadata.file_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load backup: {e}")
            return None

    def compare(
        self,
        baseline_id: str,
        compare_id: Optional[str] = None,
    ) -> ConfigDiff:
        """
        Compare two configurations.

        Args:
            baseline_id: Baseline backup ID
            compare_id: Comparison backup ID (or None for current config)

        Returns:
            ConfigDiff with differences
        """
        logger.info(f"Comparing configurations: {baseline_id} vs {compare_id or 'current'}")

        # Load baseline
        baseline_config = self.get_backup(baseline_id)
        if not baseline_config:
            raise ValueError(f"Baseline backup not found: {baseline_id}")

        baseline_metadata = self._backups_index[baseline_id]

        # Load comparison (current or backup)
        if compare_id:
            compare_config = self.get_backup(compare_id)
            if not compare_config:
                raise ValueError(f"Compare backup not found: {compare_id}")
            compare_metadata = self._backups_index[compare_id]
        else:
            compare_config = self._get_full_config()
            compare_id = "current"
            compare_metadata = BackupMetadata(
                backup_id="current",
                timestamp=datetime.now(),
            )

        # Create diff
        diff = ConfigDiff(
            baseline_id=baseline_id,
            compare_id=compare_id,
            baseline_timestamp=baseline_metadata.timestamp,
            compare_timestamp=compare_metadata.timestamp,
        )

        # Compare devices
        baseline_devices = set(baseline_config.get("devices", {}).keys())
        compare_devices = set(compare_config.get("devices", {}).keys())

        diff.devices_added = list(compare_devices - baseline_devices)
        diff.devices_removed = list(baseline_devices - compare_devices)

        for device_name in diff.devices_added:
            diff.add_change(ConfigChange(
                change_type="added",
                path=f"devices.{device_name}",
                new_value="Device added",
                device_name=device_name,
                severity="warning",
            ))

        for device_name in diff.devices_removed:
            diff.add_change(ConfigChange(
                change_type="removed",
                path=f"devices.{device_name}",
                old_value="Device removed",
                device_name=device_name,
                severity="critical",
            ))

        # Compare common devices
        common_devices = baseline_devices & compare_devices
        for device_name in common_devices:
            baseline_dev = baseline_config["devices"][device_name]
            compare_dev = compare_config["devices"][device_name]

            device_changes = self._compare_device_config(
                device_name, baseline_dev, compare_dev
            )

            if device_changes:
                diff.devices_modified.append(device_name)
                for change in device_changes:
                    diff.add_change(change)

        # Compare networks
        baseline_nets = {n["_id"]: n for n in baseline_config.get("networks", [])}
        compare_nets = {n["_id"]: n for n in compare_config.get("networks", [])}

        for net_id in set(compare_nets.keys()) - set(baseline_nets.keys()):
            net = compare_nets[net_id]
            diff.add_change(ConfigChange(
                change_type="added",
                path=f"networks.{net.get('name', net_id)}",
                new_value=f"Network added: {net.get('name', net_id)}",
                severity="info",
            ))

        for net_id in set(baseline_nets.keys()) - set(compare_nets.keys()):
            net = baseline_nets[net_id]
            diff.add_change(ConfigChange(
                change_type="removed",
                path=f"networks.{net.get('name', net_id)}",
                old_value=f"Network removed: {net.get('name', net_id)}",
                severity="warning",
            ))

        logger.info(
            f"Comparison complete: {diff.total_changes} changes "
            f"({diff.critical_changes} critical, {diff.warning_changes} warning)"
        )

        return diff

    def _compare_device_config(
        self,
        device_name: str,
        baseline: Dict[str, Any],
        compare: Dict[str, Any],
    ) -> List[ConfigChange]:
        """Compare device configurations."""
        changes = []

        # Compare version
        if baseline.get("version") != compare.get("version"):
            changes.append(ConfigChange(
                change_type="modified",
                path=f"devices.{device_name}.version",
                old_value=baseline.get("version"),
                new_value=compare.get("version"),
                device_name=device_name,
                severity="info",
            ))

        # Compare STP priority
        if baseline.get("stp_priority") != compare.get("stp_priority"):
            changes.append(ConfigChange(
                change_type="modified",
                path=f"devices.{device_name}.stp_priority",
                old_value=baseline.get("stp_priority"),
                new_value=compare.get("stp_priority"),
                device_name=device_name,
                severity="warning",
            ))

        # Compare port overrides
        baseline_ports = {p.get("port_idx"): p for p in baseline.get("port_overrides", [])}
        compare_ports = {p.get("port_idx"): p for p in compare.get("port_overrides", [])}

        for port_idx in set(compare_ports.keys()) | set(baseline_ports.keys()):
            baseline_port = baseline_ports.get(port_idx, {})
            compare_port = compare_ports.get(port_idx, {})

            # Check for significant changes
            for key in ["portconf_id", "native_networkconf_id", "forward", "tagged_vlan_mgmt"]:
                old_val = baseline_port.get(key)
                new_val = compare_port.get(key)

                if old_val != new_val:
                    severity = "warning" if key in ["forward", "tagged_vlan_mgmt"] else "info"
                    changes.append(ConfigChange(
                        change_type="modified",
                        path=f"devices.{device_name}.port_overrides.{port_idx}.{key}",
                        old_value=old_val,
                        new_value=new_val,
                        device_name=device_name,
                        severity=severity,
                    ))

        return changes

    def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup."""
        metadata = self._backups_index.get(backup_id)
        if not metadata:
            return False

        # Delete file
        if metadata.file_path and metadata.file_path.exists():
            metadata.file_path.unlink()

        # Remove from index
        del self._backups_index[backup_id]
        self._save_backup_index()

        logger.info(f"Deleted backup: {backup_id}")
        return True

    def generate_diff_report(self, diff: ConfigDiff) -> str:
        """Generate human-readable diff report."""
        report = [
            "# Configuration Diff Report",
            "",
            f"**Baseline**: {diff.baseline_id} ({diff.baseline_timestamp.strftime('%Y-%m-%d %H:%M')})",
            f"**Compare**: {diff.compare_id} ({diff.compare_timestamp.strftime('%Y-%m-%d %H:%M')})",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total Changes | {diff.total_changes} |",
            f"| 🔴 Critical | {diff.critical_changes} |",
            f"| 🟡 Warning | {diff.warning_changes} |",
            f"| Devices Added | {len(diff.devices_added)} |",
            f"| Devices Removed | {len(diff.devices_removed)} |",
            f"| Devices Modified | {len(diff.devices_modified)} |",
            "",
        ]

        if not diff.has_changes:
            report.append("**✅ No configuration changes detected**")
            report.append("")
            return "\n".join(report)

        # Devices added/removed
        if diff.devices_added:
            report.append("## Devices Added")
            report.append("")
            for device in diff.devices_added:
                report.append(f"- ➕ {device}")
            report.append("")

        if diff.devices_removed:
            report.append("## Devices Removed")
            report.append("")
            for device in diff.devices_removed:
                report.append(f"- ➖ {device}")
            report.append("")

        # Detailed changes
        if diff.changes:
            report.append("## Detailed Changes")
            report.append("")

            # Group by device
            changes_by_device: Dict[str, List[ConfigChange]] = {}
            for change in diff.changes:
                device = change.device_name or "Network"
                if device not in changes_by_device:
                    changes_by_device[device] = []
                changes_by_device[device].append(change)

            for device, changes in sorted(changes_by_device.items()):
                report.append(f"### {device}")
                report.append("")

                for change in changes:
                    severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(
                        change.severity, "⚪"
                    )
                    type_emoji = {"added": "➕", "removed": "➖", "modified": "📝"}.get(
                        change.change_type, "❓"
                    )

                    report.append(f"- {severity_emoji} {type_emoji} **{change.path}**")
                    if change.old_value is not None:
                        report.append(f"  - Old: `{change.old_value}`")
                    if change.new_value is not None:
                        report.append(f"  - New: `{change.new_value}`")

                report.append("")

        return "\n".join(report)
