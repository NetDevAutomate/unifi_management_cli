#!/usr/bin/env python3
"""
Enhanced API client combining improvements from both versions.
Provides better error handling, automatic provisioning, and reliable verification.
"""

import asyncio
import datetime
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Union

import httpx
import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from .exceptions import (
    UniFiApiError,
    UniFiAuthenticationError,
    UniFiConnectionError,
    UniFiPermissionError,
    UniFiTimeoutError,
    UniFiValidationError,
)

log = logging.getLogger(__name__)

# Valid port speeds for UniFi devices
VALID_SPEEDS = {10, 100, 1000, 2500, 5000, 10000, 20000, 25000, 40000, 50000, 100000}


class EnhancedUnifiApiClient:
    """Enhanced UniFi API client with improved reliability and verification."""

    def __init__(
        self,
        base_url: str,
        site: str = "default",
        verify_ssl: bool = False,
        username: str = None,
        password: str = None,
        api_token: str = None,
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """Initialize the Enhanced UniFi API client."""
        self.base_url = base_url.rstrip("/")
        self.site = site
        self.verify_ssl = verify_ssl
        self._username = username
        self._password = password
        self._api_token = api_token
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Initialize session
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.is_authenticated = False
        self.is_unifi_os = False

        # Setup headers
        self.session.headers.update({
            "User-Agent": "UnifiPortMapper/2.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def login(self) -> bool:
        """Login with enhanced error handling and meta.rc checking."""
        if self.is_authenticated:
            return True

        # Detect UniFi OS type
        self._detect_unifi_os()

        if self._api_token:
            return self._authenticate_token()
        elif self._username and self._password:
            return self._authenticate_password()
        else:
            raise UniFiValidationError("No credentials provided")

    def _detect_unifi_os(self) -> None:
        """Detect UniFi OS vs legacy controller."""
        try:
            response = self.session.get(f"{self.base_url}/api/system", timeout=self.timeout)
            self.is_unifi_os = response.status_code == 200
            log.debug(f"UniFi OS detection: {self.is_unifi_os}")
        except Exception:
            self.is_unifi_os = False

    def _authenticate_token(self) -> bool:
        """Authenticate using API token."""
        self.session.headers.update({"X-API-KEY": self._api_token})

        endpoint = self._build_api_path("self")
        try:
            response = self.session.get(endpoint, timeout=self.timeout)
            if response.status_code == 200:
                self.is_authenticated = True
                log.info("Successfully authenticated with API token")
                return True
        except Exception as e:
            log.error(f"Token authentication failed: {e}")

        return False

    def _authenticate_password(self) -> bool:
        """Authenticate using username/password."""
        login_endpoint = "/api/auth/login" if self.is_unifi_os else "/api/login"
        login_data = {
            "username": self._username,
            "password": self._password,
        }

        try:
            response = self.session.post(
                f"{self.base_url}{login_endpoint}",
                json=login_data,
                timeout=self.timeout
            )
            if response.status_code == 200:
                self.is_authenticated = True
                log.info("Successfully authenticated with username/password")
                return True
        except Exception as e:
            log.error(f"Password authentication failed: {e}")

        return False

    def _build_api_path(self, endpoint: str) -> str:
        """Build proper API path based on UniFi OS detection."""
        if self.is_unifi_os:
            return f"{self.base_url}/proxy/network/api/s/{self.site}/{endpoint}"
        else:
            return f"{self.base_url}/api/s/{self.site}/{endpoint}"

    def get_device_details(self, device_id: str) -> Dict[str, Any]:
        """Get device details with fallback logic."""
        if not self.is_authenticated and not self.login():
            return {}

        # Try direct device endpoint first
        endpoint = self._build_api_path(f"stat/device/{device_id}")
        try:
            response = self.session.get(endpoint, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                if "data" in data and data["data"]:
                    return data["data"][0]
        except Exception:
            pass

        # Fallback: Get from devices list
        devices_endpoint = self._build_api_path("stat/device")
        try:
            response = self.session.get(devices_endpoint, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    for device in data["data"]:
                        if device.get("_id") == device_id:
                            return device
        except Exception as e:
            log.error(f"Error getting device details: {e}")

        return {}

    def update_device_port_overrides(
        self,
        device_id: str,
        port_updates: Dict[int, str],
        auto_provision: bool = True
    ) -> bool:
        """Update port names using proper port_overrides field with automatic provisioning.

        This method uses the WRITEABLE port_overrides field (not read-only port_table)
        and automatically triggers device provisioning for reliable persistence.
        """
        if not self.is_authenticated and not self.login():
            return False

        # Get current device details
        device_details = self.get_device_details(device_id)
        if not device_details:
            log.error(f"Failed to get device details for {device_id}")
            return False

        # Build port_overrides from updates
        existing_overrides = device_details.get("port_overrides", [])
        existing_map = {po.get("port_idx"): po for po in existing_overrides if "port_idx" in po}

        new_overrides = []

        # Add/update overrides for changed ports
        for port_idx, new_name in port_updates.items():
            if port_idx in existing_map:
                override = existing_map[port_idx].copy()
                override["name"] = new_name
            else:
                override = {"port_idx": port_idx, "name": new_name}
            new_overrides.append(override)

        # Add unchanged existing overrides
        updated_port_idxs = set(port_updates.keys())
        for port_idx, existing in existing_map.items():
            if port_idx not in updated_port_idxs:
                # Clean speed values
                cleaned = {k: v for k, v in existing.items()
                          if k != "speed" or v in VALID_SPEEDS}
                if "port_idx" in cleaned:
                    new_overrides.append(cleaned)

        # Build update payload with required fields for persistence
        update_payload = {
            "_id": device_details["_id"],
            "mac": device_details["mac"],
            "port_overrides": new_overrides,
        }

        # Include config version fields (critical for persistence!)
        for field in ["config_version", "cfgversion", "config_revision"]:
            if field in device_details:
                update_payload[field] = device_details[field]

        # Send update
        endpoint = self._build_api_path(f"rest/device/{device_id}")
        try:
            response = self.session.put(
                endpoint,
                json=update_payload,
                timeout=self.timeout
            )

            if response.status_code == 200:
                # Check for UniFi meta.rc field
                try:
                    response_json = response.json()
                    meta = response_json.get("meta", {})
                    rc = meta.get("rc", "unknown")
                    if rc != "ok":
                        log.warning(f"UniFi API returned rc='{rc}': {meta.get('msg', '')}")
                        return False
                except Exception:
                    pass  # Fallback to HTTP status

                log.info(f"Successfully updated {len(port_updates)} port overrides for device {device_id}")

                # Automatic provisioning for reliable persistence
                if auto_provision:
                    device_mac = device_details.get("mac")
                    if device_mac:
                        provision_success = self.force_provision(device_mac)
                        if provision_success:
                            log.info("Device provisioning completed successfully")
                            time.sleep(3)  # Allow provisioning to complete
                        else:
                            log.warning("Device provisioning failed - changes may not persist")

                return True
            else:
                log.error(f"Port overrides update failed: {response.status_code} - {response.text[:200]}")
                return False

        except Exception as e:
            log.error(f"Error updating port overrides: {e}")
            return False

    def force_provision(self, device_mac: str) -> bool:
        """Force device provisioning to ensure config persistence."""
        endpoint = self._build_api_path("cmd/devmgr")
        provision_data = {"cmd": "force-provision", "mac": device_mac}

        try:
            response = self.session.post(
                endpoint,
                json=provision_data,
                timeout=self.timeout
            )

            if response.status_code == 200:
                # Check meta.rc for actual success
                try:
                    response_json = response.json()
                    meta = response_json.get("meta", {})
                    rc = meta.get("rc", "unknown")
                    if rc == "ok":
                        log.debug(f"Force provision successful for {device_mac}")
                        return True
                    else:
                        log.warning(f"Force provision returned rc='{rc}': {meta.get('msg', '')}")
                        return False
                except Exception:
                    # Fallback to HTTP status
                    return True
            else:
                log.warning(f"Force provision failed: {response.status_code}")
                return False

        except Exception as e:
            log.error(f"Force provision error: {e}")
            return False

    def verify_port_update_enhanced(
        self,
        device_id: str,
        port_updates: Dict[int, str],
        max_attempts: int = 5,
        wait_per_attempt: int = 5
    ) -> Dict[int, bool]:
        """Enhanced verification that checks each port individually.

        Returns:
            Dict mapping port_idx to verification success (True/False)
        """
        verification_results = {}

        for attempt in range(max_attempts):
            time.sleep(wait_per_attempt)

            # Get fresh device state
            device_details = self.get_device_details(device_id)
            if not device_details:
                continue

            port_table = device_details.get("port_table", [])

            # Check each port that needs verification
            for port_idx, expected_name in port_updates.items():
                if port_idx in verification_results and verification_results[port_idx]:
                    continue  # Already verified successfully

                # Find port in current state
                current_port = next(
                    (p for p in port_table if p.get("port_idx") == port_idx),
                    None
                )

                if current_port:
                    current_name = current_port.get("name", f"Port {port_idx}")
                    if current_name == expected_name:
                        verification_results[port_idx] = True
                        log.info(f"Port {port_idx} verified: '{current_name}'")
                    else:
                        verification_results[port_idx] = False
                        log.warning(
                            f"Port {port_idx} mismatch - Expected: '{expected_name}', "
                            f"Found: '{current_name}' (attempt {attempt + 1})"
                        )
                else:
                    verification_results[port_idx] = False
                    log.warning(f"Port {port_idx} not found in port_table (attempt {attempt + 1})")

            # If all ports verified, we can exit early
            if all(verification_results.get(p, False) for p in port_updates.keys()):
                log.info(f"All {len(port_updates)} ports verified successfully after {attempt + 1} attempts")
                break

        # Final check - any unverified ports?
        failed_ports = [p for p, success in verification_results.items() if not success]
        if failed_ports:
            log.error(f"Verification failed for ports: {failed_ports} after {max_attempts} attempts")

        return verification_results

    def get_devices(self, site_id: str) -> Dict[str, Any]:
        """Get devices with improved error handling."""
        if not self.is_authenticated and not self.login():
            return {}

        endpoint = self._build_api_path("stat/device")
        try:
            response = self.session.get(endpoint, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                # Check meta.rc for actual success
                if isinstance(data, dict) and "meta" in data:
                    meta = data.get("meta", {})
                    rc = meta.get("rc", "ok")
                    if rc != "ok":
                        log.warning(f"API returned rc='{rc}': {meta.get('msg', '')}")
                        return {}
                return data
            else:
                log.error(f"Failed to get devices: {response.status_code}")
                return {}
        except Exception as e:
            log.error(f"Error getting devices: {e}")
            return {}

    def get_clients(self, site_id: str) -> Dict[str, Any]:
        """Get clients with improved error handling."""
        if not self.is_authenticated and not self.login():
            return {}

        endpoint = self._build_api_path("stat/sta")
        try:
            response = self.session.get(endpoint, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                # Check meta.rc for actual success
                if isinstance(data, dict) and "meta" in data:
                    meta = data.get("meta", {})
                    rc = meta.get("rc", "ok")
                    if rc != "ok":
                        log.warning(f"Clients API returned rc='{rc}': {meta.get('msg', '')}")
                        return {}
                return data
            else:
                log.error(f"Failed to get clients: {response.status_code}")
                return {}
        except Exception as e:
            log.error(f"Error getting clients: {e}")
            return {}

    def batch_update_with_verification(
        self,
        device_id: str,
        port_updates: Dict[int, str],
        verify_updates: bool = True,
        auto_provision: bool = True
    ) -> tuple[bool, Dict[int, bool]]:
        """Update ports with automatic provisioning and enhanced verification.

        Returns:
            tuple of (overall_success, verification_results_per_port)
        """
        # Apply updates using proper port_overrides
        update_success = self.update_device_port_overrides(
            device_id, port_updates, auto_provision
        )

        verification_results = {}
        if update_success and verify_updates:
            # Enhanced verification checks each port individually
            verification_results = self.verify_port_update_enhanced(
                device_id, port_updates
            )

            # Overall verification success
            verification_success = all(verification_results.values())
            return verification_success, verification_results

        # If verification skipped, assume success based on API response
        if update_success and not verify_updates:
            log.warning(f"Verification SKIPPED for device {device_id} - changes may not persist!")
            # Return assumed success for all ports (unverified)
            verification_results = {p: None for p in port_updates.keys()}  # None = unverified

        return update_success, verification_results