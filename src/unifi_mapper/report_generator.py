#!/usr/bin/env python3
"""
Report generator module for the UniFi Port Mapper.
Contains functions for generating port mapping reports.
"""

import datetime
from typing import Dict

from .models import DeviceInfo


def generate_port_mapping_report(
    devices: Dict[str, DeviceInfo], output_path: str
) -> None:
    """
    Generate a port mapping report.

    Args:
        devices: Dictionary of devices
        output_path: Path to save the report
    """
    # Create the report
    report = []

    # Add the header
    report.append("# UniFi Port Mapping Report")
    report.append("")
    report.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")

    # Calculate summary statistics
    total_devices = len(devices)
    devices_with_lldp = 0
    total_ports = 0
    ports_with_lldp = 0
    ports_to_rename = 0

    for device_id, device in devices.items():
        if device.lldp_info:
            devices_with_lldp += 1

        total_ports += len(device.ports)

        for port in device.ports:
            if port.lldp_info:
                ports_with_lldp += 1

                # Check if the port should be renamed
                if port.name != port.lldp_info.get("remote_device_name", ""):
                    ports_to_rename += 1

    # Add the summary
    report.append("## Summary")
    report.append(f"- Total Devices: {total_devices}")
    report.append(f"- Devices with LLDP/CDP Information: {devices_with_lldp}")
    report.append(f"- Total Ports: {total_ports}")
    report.append(f"- Ports with LLDP/CDP Information: {ports_with_lldp}")
    report.append(f"- Ports to be Renamed: {ports_to_rename}")
    report.append("")

    # Add device details
    report.append("## Device Details")
    report.append("")

    for device_id, device in devices.items():
        # Count ports with LLDP/CDP information
        device_ports_with_lldp = 0
        device_ports_to_rename = 0

        for port in device.ports:
            if port.lldp_info:
                device_ports_with_lldp += 1

                # Check if the port should be renamed
                if port.name != port.lldp_info.get("remote_device_name", ""):
                    device_ports_to_rename += 1

        # Add device header
        report.append(f"### {device.name} ({device.model})")
        report.append(f"- Model: {device.model}")
        report.append(f"- IP: {device.ip}")
        report.append(f"- Ports with LLDP/CDP Information: {device_ports_with_lldp}")
        report.append(f"- Ports to be Renamed: {device_ports_to_rename}")
        report.append("")

        # Add port table
        report.append(
            "| Port | Status | Current Name | Proposed Name | Connected Device | PoE | Modified |"
        )
        report.append(
            "|------|--------|--------------|---------------|------------------|-----|----------|"
        )

        for port in device.ports:
            # Get port status
            status = "Up" if port.up else "Down"

            # Get current name
            current_name = port.name

            # Get proposed name
            proposed_name = port.name
            if port.lldp_info:
                remote_device_name = port.lldp_info.get("remote_device_name", "")
                remote_port_name = port.lldp_info.get("remote_port_name", "")

                if remote_device_name:
                    proposed_name = remote_device_name
                    if remote_port_name:
                        proposed_name += f" ({remote_port_name})"

            # Get connected device
            connected_device = ""
            if port.lldp_info:
                connected_device = port.lldp_info.get("remote_device_name", "")
                if not connected_device:
                    connected_device = port.lldp_info.get("remote_chassis_id", "")

            # Get PoE status
            poe_status = "Enabled" if port.poe else "Disabled"

            # Check if port was actually updated (requires tracking from update logic)
            # For now, show "⚠" for ports that need updating but haven't been verified
            # This prevents false positives where ✓ appears but update didn't persist
            if current_name != proposed_name:
                # Port needs updating but we don't know if it was actually applied/verified
                modified = "⚠"  # Warning: needs verification
            else:
                modified = ""  # No change needed

            # Add the port row
            report.append(
                f"| {port.idx} | {status} | {current_name} | {proposed_name} | {connected_device} | {poe_status} | {modified} |"
            )

        report.append("")

    # Write the report to the output file
    with open(output_path, "w") as f:
        f.write("\n".join(report))
