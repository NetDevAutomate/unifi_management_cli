#!/usr/bin/env python3
"""
Smart Port Mapper with Device-Aware Capabilities.
Respects device limitations and provides appropriate strategies per device model.
"""

import logging
from typing import Dict, List, Tuple

from .device_capabilities import DeviceCapabilityDetector, PortNamingSupport
from .ground_truth_verification import verify_with_ground_truth

log = logging.getLogger(__name__)


class SmartPortMapper:
    """Port mapper that respects device-specific capabilities and limitations."""

    def __init__(self, api_client):
        """Initialize smart port mapper with API client."""
        self.api_client = api_client
        self.capability_detector = DeviceCapabilityDetector()

    def smart_update_ports(
        self,
        devices_data: List[Dict],
        lldp_data: Dict[str, Dict],
        verify_updates: bool = True,
        dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Update port names using device-aware strategies.

        Args:
            devices_data: List of device information
            lldp_data: LLDP discovery data mapping device_id to port LLDP info
            verify_updates: Whether to perform ground truth verification
            dry_run: Whether to simulate updates without applying changes

        Returns:
            Dict with detailed results per device
        """
        results = {
            "summary": {
                "total_devices": len(devices_data),
                "attempted_updates": 0,
                "successful_updates": 0,
                "skipped_incompatible": 0,
                "failed_verification": 0
            },
            "device_results": {},
            "incompatible_devices": [],
            "verification_failures": []
        }

        for device in devices_data:
            device_id = device.get("_id")
            device_name = device.get("name", "Unknown")
            device_model = device.get("model", "Unknown")
            firmware_version = device.get("version", "Unknown")
            device_ip = device.get("ip", "Unknown")

            log.info(f"Processing {device_name} ({device_model}) - Firmware {firmware_version}")

            # Check device capabilities
            capability = self.capability_detector.detect_capabilities(device_model, firmware_version)
            should_attempt, reason = self.capability_detector.should_attempt_port_naming(
                device_model, firmware_version
            )

            device_result = {
                "device_name": device_name,
                "device_model": device_model,
                "firmware_version": firmware_version,
                "capability": capability.port_naming_support.value,
                "should_attempt": should_attempt,
                "reason": reason,
                "ports_attempted": {},
                "ports_verified": {}
            }

            if not should_attempt:
                log.warning(f"⚠️  Skipping {device_name}: {reason}")
                results["summary"]["skipped_incompatible"] += 1
                results["incompatible_devices"].append({
                    "device_name": device_name,
                    "model": device_model,
                    "firmware": firmware_version,
                    "reason": reason,
                    "workarounds": capability.workarounds
                })
                results["device_results"][device_id] = device_result
                continue

            # Get LLDP data for this device
            device_lldp = lldp_data.get(device_id, {})
            if not device_lldp:
                log.info(f"No LLDP data for {device_name} - skipping")
                results["device_results"][device_id] = device_result
                continue

            # Determine update strategy
            strategy = self.capability_detector.get_recommended_strategy(device_model, firmware_version)

            # Build port updates based on strategy
            port_updates = {}
            for port_idx_str, lldp_info in device_lldp.items():
                port_idx = int(port_idx_str)
                remote_device_name = lldp_info.get("remote_device_name")

                if remote_device_name and len(remote_device_name) > 3:
                    if strategy["strategy"] == "CAUTIOUS_API":
                        # Use minimal payload for problematic devices
                        port_updates[port_idx] = remote_device_name
                    elif strategy["strategy"] == "STANDARD_API":
                        # Use full payload for compatible devices
                        port_updates[port_idx] = remote_device_name

            if not port_updates:
                log.info(f"No port updates needed for {device_name}")
                results["device_results"][device_id] = device_result
                continue

            log.info(f"📝 {device_name}: Will attempt {len(port_updates)} port updates")
            device_result["ports_attempted"] = port_updates.copy()

            # Apply updates based on device capability
            if not dry_run:
                update_success = self._apply_device_aware_updates(
                    device_id, device_name, port_updates, capability
                )

                if update_success:
                    results["summary"]["attempted_updates"] += 1
                    log.info(f"✅ Applied updates to {device_name}")
                else:
                    log.error(f"❌ Failed to update {device_name}")
            else:
                log.info(f"[DRY RUN] Would update {len(port_updates)} ports on {device_name}")

            results["device_results"][device_id] = device_result

        # Perform ground truth verification if requested
        if verify_updates and not dry_run and results["summary"]["attempted_updates"] > 0:
            log.info("🔍 Performing ground truth verification...")
            verification_results = self._perform_ground_truth_verification(results)
            results["verification_results"] = verification_results

        return results

    def _apply_device_aware_updates(
        self,
        device_id: str,
        device_name: str,
        port_updates: Dict[int, str],
        capability: object
    ) -> bool:
        """Apply port updates using device-appropriate strategy."""

        if capability.port_naming_support == PortNamingSupport.RESETS_AUTOMATICALLY:
            log.warning(f"⚠️  {device_name}: Device auto-resets configurations - update likely to fail")
            # Still attempt but warn user

        elif capability.port_naming_support == PortNamingSupport.UI_ONLY:
            log.warning(f"⚠️  {device_name}: API unreliable - recommend manual UI configuration")
            return False  # Don't attempt API updates

        # Get current device details
        device_details = self.api_client.get_device_details(self.api_client.site, device_id)
        if not device_details:
            log.error(f"Failed to get device details for {device_name}")
            return False

        # Build minimal port_table for problematic devices
        port_table = device_details.get("port_table", [])

        # Update only the name field to minimize rejection risk
        for port in port_table:
            port_idx = port.get("port_idx")
            if port_idx in port_updates:
                old_name = port.get("name", f"Port {port_idx}")
                new_name = port_updates[port_idx]
                port["name"] = new_name
                log.info(f"  Port {port_idx}: '{old_name}' -> '{new_name}'")

        # Use the most compatible update method
        try:
            # Try the port_overrides approach (most reliable when it works)
            success = self.api_client.update_device_port_table(device_id, port_table)

            if success:
                # Force provisioning for devices that support it
                device_mac = device_details.get("mac")
                if device_mac:
                    from .port_mapper import UnifiPortMapper
                    # Create temporary port mapper for provisioning
                    temp_mapper = UnifiPortMapper(
                        self.api_client.base_url,
                        self.api_client.site,
                        api_token=getattr(self.api_client, '_api_token', None)
                    )
                    temp_mapper.api_client = self.api_client
                    provision_success = temp_mapper._force_device_provision(device_id, device_mac)

                    if provision_success:
                        log.info(f"✅ Provisioning successful for {device_name}")
                    else:
                        log.warning(f"⚠️  Provisioning may have failed for {device_name}")

            return success

        except Exception as e:
            log.error(f"Failed to update {device_name}: {e}")
            return False

    def _perform_ground_truth_verification(
        self,
        results: Dict[str, any]
    ) -> Dict[str, any]:
        """Perform ground truth verification on attempted updates."""

        # Build device_updates dict for verification
        device_updates = {}

        for device_id, device_result in results["device_results"].items():
            ports_attempted = device_result.get("ports_attempted")
            if ports_attempted:
                device_updates[device_id] = ports_attempted

        if not device_updates:
            log.info("No devices to verify")
            return {}

        # Use enhanced API verification (not browser for now)
        verification_results, verification_report = verify_with_ground_truth(
            self.api_client, device_updates, browser_credentials=None
        )

        # Log verification report
        print("\n" + verification_report)

        # Update results with verification status
        for device_id, device_ports in verification_results.items():
            if device_id in results["device_results"]:
                results["device_results"][device_id]["ports_verified"] = device_ports

                # Count verification failures
                for port_idx, verified in device_ports.items():
                    if not verified:
                        results["summary"]["failed_verification"] += 1
                        results["verification_failures"].append({
                            "device_id": device_id,
                            "device_name": results["device_results"][device_id]["device_name"],
                            "port_idx": port_idx,
                            "expected_name": device_updates[device_id][port_idx]
                        })
                    else:
                        results["summary"]["successful_updates"] += 1

        return verification_results

    def generate_smart_mapping_report(
        self,
        results: Dict[str, any]
    ) -> str:
        """Generate comprehensive report with device-aware recommendations."""

        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("SMART PORT MAPPING REPORT")
        report_lines.append("=" * 80)

        summary = results["summary"]
        report_lines.append(f"Total devices analyzed: {summary['total_devices']}")
        report_lines.append(f"Updates attempted: {summary['attempted_updates']}")
        report_lines.append(f"Successful updates: {summary['successful_updates']}")
        report_lines.append(f"Skipped (incompatible): {summary['skipped_incompatible']}")
        report_lines.append(f"Failed verification: {summary['failed_verification']}")

        # Incompatible devices section
        if results["incompatible_devices"]:
            report_lines.append(f"\n🚨 INCOMPATIBLE DEVICES ({len(results['incompatible_devices'])})")
            report_lines.append("=" * 50)

            for device in results["incompatible_devices"]:
                report_lines.append(f"\n❌ {device['device_name']} ({device['model']})")
                report_lines.append(f"   Firmware: {device['firmware']}")
                report_lines.append(f"   Issue: {device['reason']}")
                report_lines.append("   Recommended Workarounds:")
                for workaround in device['workarounds']:
                    report_lines.append(f"     - {workaround}")

        # Verification failures section
        if results["verification_failures"]:
            report_lines.append(f"\n⚠️  VERIFICATION FAILURES ({len(results['verification_failures'])})")
            report_lines.append("=" * 50)
            report_lines.append("These devices accepted updates but changes didn't persist:")

            for failure in results["verification_failures"]:
                report_lines.append(f"   • {failure['device_name']} Port {failure['port_idx']}: Expected '{failure['expected_name']}'")

        # Recommendations section
        report_lines.append(f"\n💡 RECOMMENDATIONS")
        report_lines.append("=" * 50)

        if summary["skipped_incompatible"] > 0:
            report_lines.append(f"• {summary['skipped_incompatible']} devices have known port naming limitations")
            report_lines.append("  Consider manual UI-based configuration for these devices")

        if summary["failed_verification"] > 0:
            report_lines.append(f"• {summary['failed_verification']} port updates failed verification")
            report_lines.append("  These devices may need firmware updates or manual configuration")

        if summary["successful_updates"] > 0:
            report_lines.append(f"• {summary['successful_updates']} port updates verified successfully")
            report_lines.append("  These devices support reliable automated port naming")

        return "\n".join(report_lines)