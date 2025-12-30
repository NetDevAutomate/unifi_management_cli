#!/usr/bin/env python3
"""
UniFi Device Capability Detection System.
Determines which devices support reliable port naming based on model and firmware.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)


class PortNamingSupport(Enum):
    """Port naming capability levels for UniFi devices."""
    FULL_SUPPORT = "full"           # Reliable port naming via API
    UI_ONLY = "ui_only"             # Only works via UI, API fails
    LIMITED = "limited"             # Partial support with restrictions
    RESETS_AUTOMATICALLY = "resets"  # Accepts changes but reverts them
    NOT_SUPPORTED = "none"          # No custom port naming support


@dataclass
class DeviceCapability:
    """Device capability information."""
    model: str
    firmware_version: str
    port_naming_support: PortNamingSupport
    known_issues: List[str]
    workarounds: List[str]
    api_endpoint_restrictions: List[str]
    max_port_name_length: Optional[int] = 32
    supports_port_profiles: bool = True


class DeviceCapabilityDetector:
    """Detects device capabilities based on model and firmware."""

    # Based on community research and documentation
    KNOWN_DEVICE_ISSUES = {
        # US 8 60W - Critical firmware 7.2.123 issues
        ("US8P60", "7.2.123"): DeviceCapability(
            model="US-8-60W",
            firmware_version="7.2.123",
            port_naming_support=PortNamingSupport.RESETS_AUTOMATICALLY,
            known_issues=[
                "Automatically resets port profiles to 'All' after minutes/hours",
                "Continuous disconnection/re-adoption cycles",
                "Connected access points power cycle repeatedly",
                "Port state transitions may cause device hang",
            ],
            workarounds=[
                "Defer firmware upgrade from 7.2.123",
                "Use UI-based configuration instead of API",
                "Factory reset and re-adopt if in error state",
                "Monitor for automatic profile resets"
            ],
            api_endpoint_restrictions=[
                "port_overrides updates may be rejected",
                "Profile changes trigger connectivity loss"
            ]
        ),

        # USW Lite 8 PoE - Hardware/firmware limitations
        ("USL8LP", "*"): DeviceCapability(
            model="USW-Lite-8-PoE",
            firmware_version="*",
            port_naming_support=PortNamingSupport.LIMITED,
            known_issues=[
                "Cannot select VLAN options through port configuration",
                "Port naming changes may not persist",
                "Supports only 4 PoE ports out of 8 total"
            ],
            workarounds=[
                "Use network-level VLAN configuration",
                "Verify port names persist after configuration",
                "Consider upgrading to higher-end switch for full features"
            ],
            api_endpoint_restrictions=[
                "VLAN selection API may be restricted",
                "Limited to 128 IPv4 and 128 MAC ACLs"
            ]
        ),

        # USW Flex 2.5G 5 - Documented network override limitation
        ("USWED35", "*"): DeviceCapability(
            model="USW-Flex-2.5G-5",
            firmware_version="*",
            port_naming_support=PortNamingSupport.LIMITED,
            known_issues=[
                "Network override option hidden on device ports",
                "port_overrides API calls may be rejected",
                "2.5G speed settings can cause validation failures"
            ],
            workarounds=[
                "Use manual UI configuration when possible",
                "Test port naming in staging before production",
                "Verify speed settings compatibility"
            ],
            api_endpoint_restrictions=[
                "Network override API limited",
                "Speed validation more strict than 1G models"
            ]
        ),

        # USW Flex Mini 2.5G - Confirmed working
        ("USMINI2P5G", "*"): DeviceCapability(
            model="USW-Flex-Mini-2.5G",
            firmware_version="*",
            port_naming_support=PortNamingSupport.FULL_SUPPORT,
            known_issues=[],
            workarounds=[],
            api_endpoint_restrictions=[]
        ),
    }

    # Problematic firmware versions
    PROBLEMATIC_FIRMWARE = {
        "7.2.123": [
            "Automatic port profile reset",
            "Device hang during port state transitions",
            "Connectivity instability",
            "API rejection errors"
        ],
        "6.5.59": [
            "Adoption failures",
            "SSH connectivity issues",
            "Firmware update failures"
        ]
    }

    # Models known to have port naming restrictions
    RESTRICTED_MODELS = {
        "US8P60",    # US-8-60W
        "USL8LP",    # USW-Lite-8-PoE
        "USWED35",   # USW-Flex-2.5G-5
        "USFLEX",    # USW-Flex (original)
    }

    def detect_capabilities(
        self,
        device_model: str,
        firmware_version: str
    ) -> DeviceCapability:
        """
        Detect device capabilities based on model and firmware.

        Args:
            device_model: UniFi device model code
            firmware_version: Device firmware version

        Returns:
            DeviceCapability object with support level and restrictions
        """
        # Check for exact model/firmware match first
        key = (device_model.upper(), firmware_version)
        if key in self.KNOWN_DEVICE_ISSUES:
            return self.KNOWN_DEVICE_ISSUES[key]

        # Check for model with any firmware version
        key = (device_model.upper(), "*")
        if key in self.KNOWN_DEVICE_ISSUES:
            return self.KNOWN_DEVICE_ISSUES[key]

        # Check for problematic firmware version
        if firmware_version in self.PROBLEMATIC_FIRMWARE:
            return DeviceCapability(
                model=device_model,
                firmware_version=firmware_version,
                port_naming_support=PortNamingSupport.RESETS_AUTOMATICALLY,
                known_issues=self.PROBLEMATIC_FIRMWARE[firmware_version],
                workarounds=["Defer firmware upgrade", "Use UI-based configuration"],
                api_endpoint_restrictions=["port_overrides may fail"]
            )

        # Check for restricted model families
        if any(model in device_model.upper() for model in self.RESTRICTED_MODELS):
            return DeviceCapability(
                model=device_model,
                firmware_version=firmware_version,
                port_naming_support=PortNamingSupport.LIMITED,
                known_issues=["May have port naming restrictions"],
                workarounds=["Test in staging environment", "Use UI when possible"],
                api_endpoint_restrictions=["Unverified port_overrides support"]
            )

        # Default - assume full support for newer/unknown models
        return DeviceCapability(
            model=device_model,
            firmware_version=firmware_version,
            port_naming_support=PortNamingSupport.FULL_SUPPORT,
            known_issues=[],
            workarounds=[],
            api_endpoint_restrictions=[]
        )

    def should_attempt_port_naming(
        self,
        device_model: str,
        firmware_version: str
    ) -> Tuple[bool, str]:
        """
        Determine if port naming should be attempted on this device.

        Returns:
            Tuple of (should_attempt, reason_if_not)
        """
        capability = self.detect_capabilities(device_model, firmware_version)

        if capability.port_naming_support == PortNamingSupport.NOT_SUPPORTED:
            return False, f"Model {device_model} does not support custom port names"

        elif capability.port_naming_support == PortNamingSupport.RESETS_AUTOMATICALLY:
            return False, f"Firmware {firmware_version} automatically resets port configurations"

        elif capability.port_naming_support == PortNamingSupport.UI_ONLY:
            return False, f"Model {device_model} only supports UI-based port naming, not API"

        elif capability.port_naming_support == PortNamingSupport.LIMITED:
            return True, f"Model {device_model} has limited port naming support - proceed with caution"

        else:  # FULL_SUPPORT
            return True, "Device supports reliable port naming"

    def get_recommended_strategy(
        self,
        device_model: str,
        firmware_version: str
    ) -> Dict[str, any]:
        """
        Get recommended update strategy for this device.

        Returns:
            Dict with strategy recommendations
        """
        capability = self.detect_capabilities(device_model, firmware_version)

        if capability.port_naming_support == PortNamingSupport.RESETS_AUTOMATICALLY:
            return {
                "strategy": "AVOID",
                "reason": "Device automatically resets configurations",
                "alternatives": [
                    "Use network documentation instead of device port names",
                    "Defer firmware upgrade to avoid reset behavior",
                    "Monitor for automatic resets if changes attempted"
                ]
            }

        elif capability.port_naming_support == PortNamingSupport.UI_ONLY:
            return {
                "strategy": "MANUAL_ONLY",
                "reason": "API port naming unreliable on this model",
                "alternatives": [
                    "Use UniFi controller UI for port name changes",
                    "Document manual changes in external system",
                    "Consider model upgrade for API compatibility"
                ]
            }

        elif capability.port_naming_support == PortNamingSupport.LIMITED:
            return {
                "strategy": "CAUTIOUS_API",
                "reason": "Limited API support - test before production use",
                "recommendations": [
                    "Test port naming in staging environment",
                    "Verify changes persist across device reboots",
                    "Use minimal port_overrides payload",
                    "Implement enhanced verification"
                ]
            }

        else:  # FULL_SUPPORT
            return {
                "strategy": "STANDARD_API",
                "reason": "Device supports reliable API-based port naming",
                "recommendations": [
                    "Use standard port_overrides API",
                    "Standard verification should be sufficient"
                ]
            }

    def generate_compatibility_report(
        self,
        devices: List[Dict[str, any]]
    ) -> str:
        """Generate device compatibility report for port naming."""
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("UNIFI DEVICE PORT NAMING COMPATIBILITY REPORT")
        report_lines.append("=" * 80)

        compatible_devices = 0
        problematic_devices = 0
        unsupported_devices = 0

        for device in devices:
            model = device.get("model", "Unknown")
            firmware = device.get("version", "Unknown")
            name = device.get("name", "Unknown")

            capability = self.detect_capabilities(model, firmware)

            report_lines.append(f"\n📍 {name} ({model}) - Firmware {firmware}")

            if capability.port_naming_support == PortNamingSupport.FULL_SUPPORT:
                report_lines.append("  ✅ FULL SUPPORT - Reliable API port naming")
                compatible_devices += 1
            elif capability.port_naming_support == PortNamingSupport.RESETS_AUTOMATICALLY:
                report_lines.append("  🚨 AUTO-RESETS - Changes don't persist")
                problematic_devices += 1
            elif capability.port_naming_support == PortNamingSupport.UI_ONLY:
                report_lines.append("  ⚠️  UI ONLY - API unreliable")
                problematic_devices += 1
            elif capability.port_naming_support == PortNamingSupport.LIMITED:
                report_lines.append("  ⚠️  LIMITED - Partial support")
                problematic_devices += 1
            else:
                report_lines.append("  ❌ NOT SUPPORTED")
                unsupported_devices += 1

            if capability.known_issues:
                for issue in capability.known_issues:
                    report_lines.append(f"    • {issue}")

            if capability.workarounds:
                report_lines.append("    Workarounds:")
                for workaround in capability.workarounds:
                    report_lines.append(f"      - {workaround}")

        # Summary
        total_devices = len(devices)
        report_lines.append(f"\n{'='*80}")
        report_lines.append("COMPATIBILITY SUMMARY")
        report_lines.append("=" * 80)
        report_lines.append(f"Total devices analyzed: {total_devices}")
        report_lines.append(f"✅ Compatible devices: {compatible_devices}")
        report_lines.append(f"⚠️  Problematic devices: {problematic_devices}")
        report_lines.append(f"❌ Unsupported devices: {unsupported_devices}")

        if problematic_devices > 0 or unsupported_devices > 0:
            report_lines.append(f"\n🚨 CRITICAL: {problematic_devices + unsupported_devices} devices have port naming issues")
            report_lines.append("Automated port naming not recommended for this network.")
            report_lines.append("Consider manual UI-based configuration or device upgrades.")

        return "\n".join(report_lines)