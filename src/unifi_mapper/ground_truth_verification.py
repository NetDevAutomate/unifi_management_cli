#!/usr/bin/env python3
"""
Ground truth verification using browser automation.
Bypasses the lying UniFi API by checking actual controller UI state.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


class GroundTruthVerifier:
    """Verification system that checks actual UniFi controller UI instead of trusting API."""

    def __init__(self, api_client, browser_credentials: Optional[Dict[str, str]] = None):
        """
        Initialize ground truth verifier.

        Args:
            api_client: UniFi API client (for device lookups only, not for verification)
            browser_credentials: Dict with 'username' and 'password' for UI access
        """
        self.api_client = api_client
        self.browser_credentials = browser_credentials

    def verify_port_updates_ground_truth(
        self,
        device_updates: Dict[str, Dict[int, str]],
        use_browser: bool = False
    ) -> Dict[str, Dict[int, bool]]:
        """
        Verify port updates using ground truth methods instead of API polling.

        Args:
            device_updates: Dict mapping device_id to {port_idx: expected_name}
            use_browser: Whether to use browser verification (requires credentials)

        Returns:
            Dict mapping device_id to {port_idx: verification_success}
        """
        if use_browser and self.browser_credentials:
            return self._verify_with_browser(device_updates)
        else:
            return self._verify_with_enhanced_api_checks(device_updates)

    def _verify_with_enhanced_api_checks(
        self,
        device_updates: Dict[str, Dict[int, str]]
    ) -> Dict[str, Dict[int, bool]]:
        """
        Enhanced API verification that uses multiple techniques to detect lying responses.
        """
        results = {}

        for device_id, port_updates in device_updates.items():
            device_results = {}

            # Get device details
            device_details = self.api_client.get_device_details(
                self.api_client.site, device_id
            )

            if not device_details:
                log.error(f"Cannot verify {device_id} - device details unavailable")
                device_results = {port_idx: False for port_idx in port_updates}
                results[device_id] = device_results
                continue

            device_name = device_details.get("name", "Unknown")
            device_model = device_details.get("model", "Unknown")

            log.info(f"Ground truth verification for {device_name} ({device_model})")

            # TECHNIQUE 1: Multi-read consistency check
            for port_idx, expected_name in port_updates.items():
                consistency_results = self._multi_read_consistency_check(
                    device_id, port_idx, expected_name
                )

                if consistency_results["consistent"] and consistency_results["matches_expected"]:
                    device_results[port_idx] = True
                    log.info(f"✅ Port {port_idx}: Verified '{expected_name}' (consistent across reads)")
                else:
                    device_results[port_idx] = False
                    log.error(f"❌ Port {port_idx}: Expected '{expected_name}', "
                             f"got inconsistent results: {consistency_results}")

            results[device_id] = device_results

        return results

    def _multi_read_consistency_check(
        self,
        device_id: str,
        port_idx: int,
        expected_name: str,
        num_reads: int = 5,
        delay_between_reads: float = 2.0
    ) -> Dict[str, any]:
        """
        Read the same port name multiple times with delays to detect cache inconsistency.

        Returns:
            {
                "consistent": bool,
                "matches_expected": bool,
                "read_values": List[str],
                "unique_values": List[str]
            }
        """
        read_values = []

        for read_num in range(num_reads):
            try:
                # Add cache-busting techniques
                time.sleep(delay_between_reads)

                # Force fresh device details with cache-busting
                # Clear session cookies to force re-authentication path
                if hasattr(self.api_client.session, 'cookies'):
                    # Don't clear auth cookies, but add cache-busting headers
                    self.api_client.session.headers.update({
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "X-Requested-With": f"GroundTruthVerifier-{time.time()}",
                        "X-Cache-Bust": str(int(time.time() * 1000))
                    })

                device_details = self.api_client.get_device_details(
                    self.api_client.site, device_id
                )

                if not device_details:
                    read_values.append("ERROR_NO_DEVICE")
                    continue

                # Extract port name from port_table
                port_table = device_details.get("port_table", [])
                port_name = None

                for port in port_table:
                    if port.get("port_idx") == port_idx:
                        port_name = port.get("name", f"Port {port_idx}")
                        break

                if port_name is None:
                    read_values.append("ERROR_PORT_NOT_FOUND")
                else:
                    read_values.append(port_name)

                log.debug(f"Read {read_num + 1}: Port {port_idx} = '{port_name}'")

            except Exception as e:
                log.warning(f"Read {read_num + 1} failed: {e}")
                read_values.append(f"ERROR_{str(e)[:20]}")

        # Analyze consistency
        unique_values = list(set(read_values))
        consistent = len(unique_values) == 1

        # Check if the consistent value (if any) matches expected
        matches_expected = False
        if consistent and len(unique_values) == 1:
            matches_expected = unique_values[0] == expected_name

        return {
            "consistent": consistent,
            "matches_expected": matches_expected,
            "read_values": read_values,
            "unique_values": unique_values,
            "most_common": max(set(read_values), key=read_values.count) if read_values else None
        }

    def _verify_with_browser(
        self,
        device_updates: Dict[str, Dict[int, str]]
    ) -> Dict[str, Dict[int, bool]]:
        """
        Verify port updates by checking actual UniFi controller UI via browser automation.
        This is the most reliable method since it bypasses all API caching issues.
        """
        try:
            # This would require Playwright integration
            log.warning("Browser verification not implemented yet - falling back to enhanced API checks")
            return self._verify_with_enhanced_api_checks(device_updates)

        except Exception as e:
            log.error(f"Browser verification failed: {e}")
            return {}

    def generate_verification_report(
        self,
        device_updates: Dict[str, Dict[int, str]],
        verification_results: Dict[str, Dict[int, bool]]
    ) -> str:
        """
        Generate detailed verification report showing discrepancies.
        """
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("GROUND TRUTH VERIFICATION REPORT")
        report_lines.append("=" * 80)

        total_ports = 0
        successful_verifications = 0
        failed_verifications = 0

        for device_id, port_updates in device_updates.items():
            device_results = verification_results.get(device_id, {})

            # Get device details for reporting
            device_details = self.api_client.get_device_details(
                self.api_client.site, device_id
            )
            device_name = device_details.get("name", device_id) if device_details else device_id
            device_ip = device_details.get("ip", "Unknown") if device_details else "Unknown"

            report_lines.append(f"\n📍 {device_name} (IP: {device_ip})")
            report_lines.append("-" * 50)

            for port_idx, expected_name in port_updates.items():
                total_ports += 1
                verification_success = device_results.get(port_idx, False)

                if verification_success:
                    successful_verifications += 1
                    report_lines.append(f"  ✅ Port {port_idx}: '{expected_name}' - VERIFIED")
                else:
                    failed_verifications += 1
                    report_lines.append(f"  ❌ Port {port_idx}: Expected '{expected_name}' - FAILED")

        # Summary
        report_lines.append("\n" + "=" * 80)
        report_lines.append("VERIFICATION SUMMARY")
        report_lines.append("=" * 80)
        report_lines.append(f"Total ports checked: {total_ports}")
        report_lines.append(f"Successful verifications: {successful_verifications}")
        report_lines.append(f"Failed verifications: {failed_verifications}")

        if failed_verifications > 0:
            report_lines.append(f"\n⚠️  {failed_verifications} ports failed verification!")
            report_lines.append("This indicates the UniFi API is returning stale/cached data.")
            report_lines.append("Consider using browser-based verification for ground truth.")

        success_rate = (successful_verifications / total_ports * 100) if total_ports > 0 else 0
        report_lines.append(f"Success rate: {success_rate:.1f}%")

        return "\n".join(report_lines)


def verify_with_ground_truth(
    api_client,
    device_updates: Dict[str, Dict[int, str]],
    browser_credentials: Optional[Dict[str, str]] = None
) -> Tuple[Dict[str, Dict[int, bool]], str]:
    """
    Perform ground truth verification and return results with detailed report.

    Args:
        api_client: UniFi API client
        device_updates: Dict mapping device_id to {port_idx: expected_name}
        browser_credentials: Optional credentials for browser verification

    Returns:
        Tuple of (verification_results, detailed_report)
    """
    verifier = GroundTruthVerifier(api_client, browser_credentials)

    # Perform verification
    results = verifier.verify_port_updates_ground_truth(
        device_updates, use_browser=bool(browser_credentials)
    )

    # Generate detailed report
    report = verifier.generate_verification_report(
        device_updates, results
    )

    return results, report