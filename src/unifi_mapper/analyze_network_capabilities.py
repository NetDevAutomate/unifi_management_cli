#!/usr/bin/env python3
"""
Analyze network device capabilities for port naming support.
"""

import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.config import UnifiConfig
from unifi_mapper.device_capabilities import DeviceCapabilityDetector
from unifi_mapper.cli import load_env_from_config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main():
    """Analyze all devices in network for port naming capabilities."""
    # Load config
    config_path = "/Users/ataylor/.dotfiles/.config/unifi_network_mapper/prod.env"
    load_env_from_config(config_path)
    config = UnifiConfig.from_env()

    # Create API client
    api_client = UnifiApiClient(
        base_url=config.base_url,
        site=config.site,
        api_token=config.api_token,
        verify_ssl=config.verify_ssl,
    )

    if not api_client.login():
        log.error("Failed to authenticate")
        return

    # Get all devices
    devices_response = api_client.get_devices(config.site)
    if not devices_response or "data" not in devices_response:
        log.error("Failed to get devices")
        return

    # Filter network devices
    network_devices = [
        d for d in devices_response["data"]
        if d.get("type") in ["ugw", "usg", "udm", "usw"]
    ]

    log.info(f"Analyzing {len(network_devices)} network devices...")

    # Analyze capabilities
    detector = DeviceCapabilityDetector()
    report = detector.generate_compatibility_report(network_devices)

    print("\n" + report)

    # Identify specific problematic devices
    print(f"\n{'='*80}")
    print("DEVICE-SPECIFIC ANALYSIS")
    print("=" * 80)

    for device in network_devices:
        model = device.get("model", "Unknown")
        firmware = device.get("version", "Unknown")
        name = device.get("name", "Unknown")
        ip = device.get("ip", "Unknown")

        should_attempt, reason = detector.should_attempt_port_naming(model, firmware)
        strategy = detector.get_recommended_strategy(model, firmware)

        print(f"\n📍 {name} ({model}) - {ip}")
        print(f"   Firmware: {firmware}")
        print(f"   Port Naming: {'✅ ATTEMPT' if should_attempt else '❌ AVOID'}")
        print(f"   Reason: {reason}")
        print(f"   Strategy: {strategy['strategy']}")

        if "alternatives" in strategy:
            print("   Alternatives:")
            for alt in strategy["alternatives"]:
                print(f"     - {alt}")

        if "recommendations" in strategy:
            print("   Recommendations:")
            for rec in strategy["recommendations"]:
                print(f"     - {rec}")


if __name__ == "__main__":
    main()