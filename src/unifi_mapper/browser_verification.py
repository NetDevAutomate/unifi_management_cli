#!/usr/bin/env python3
"""
Browser-based verification for UniFi port name updates.
Uses Playwright to directly check the controller UI since the API lies about port names.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


class BrowserVerifier:
    """Browser-based verification that checks actual UniFi controller UI."""

    def __init__(self, controller_url: str, username: str, password: str):
        """Initialize browser verifier with UniFi controller credentials."""
        self.controller_url = controller_url.rstrip("/")
        self.username = username
        self.password = password
        self.browser = None
        self.page = None

    async def __aenter__(self):
        """Async context manager entry."""
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,  # Run in background
            args=['--ignore-certificate-errors', '--ignore-ssl-errors']
        )
        self.page = await self.browser.new_page()
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def login(self) -> bool:
        """Login to UniFi controller via browser."""
        try:
            # Navigate to controller
            login_url = f"{self.controller_url}/login" if self.controller_url.startswith("https") else f"https://{self.controller_url}/login"
            await self.page.goto(login_url, wait_until="networkidle")

            # Wait for login form
            await self.page.wait_for_selector('input[placeholder*="Username"], input[placeholder*="Email"]', timeout=10000)

            # Fill credentials
            await self.page.fill('input[placeholder*="Username"], input[placeholder*="Email"]', self.username)
            await self.page.fill('input[type="password"]', self.password)

            # Click sign in
            await self.page.click('button:has-text("Sign In")')

            # Wait for successful login (dashboard or network page)
            await self.page.wait_for_url("**/dashboard", timeout=15000)

            log.info("Successfully logged into UniFi controller via browser")
            return True

        except Exception as e:
            log.error(f"Browser login failed: {e}")
            return False

    async def verify_port_name_in_ui(
        self,
        device_name: str,
        device_ip: str,
        port_idx: int,
        expected_name: str,
        max_attempts: int = 3
    ) -> Tuple[bool, str]:
        """
        Verify port name by checking actual UniFi controller UI.

        Args:
            device_name: Device name to find
            device_ip: Device IP address for identification
            port_idx: Port index to check
            expected_name: Expected port name
            max_attempts: Maximum verification attempts

        Returns:
            Tuple of (verification_success, actual_name_in_ui)
        """
        for attempt in range(max_attempts):
            try:
                log.info(f"Browser verification attempt {attempt + 1}/{max_attempts} for {device_name} Port {port_idx}")

                # Navigate to ports page
                ports_url = f"{self.controller_url}/network/default/ports"
                await self.page.goto(ports_url, wait_until="networkidle")
                await self.page.wait_for_selector('table', timeout=10000)

                # Find device in device selector dropdown
                device_selector = self.page.locator('input[placeholder*="Select"], input:has-text("Office")')
                await device_selector.first.click()

                # Look for the device option
                device_option = self.page.locator(f'text="{device_name}"').first
                if await device_option.count() > 0:
                    await device_option.click()
                else:
                    # Fallback: search by IP in the devices list
                    await self.page.goto(f"{self.controller_url}/network/default/devices")
                    device_row = self.page.locator(f'text="{device_ip}"').first
                    if await device_row.count() > 0:
                        await device_row.click()
                        # Click Port Manager
                        await self.page.click('button:has-text("Port Manager")')
                    else:
                        log.warning(f"Device {device_name} not found in UI")
                        continue

                # Wait for port table to load
                await self.page.wait_for_selector('table', timeout=5000)

                # Find the specific port row
                port_row_selector = f'tr:has(td:has-text("{port_idx}"))'
                port_row = self.page.locator(port_row_selector).first

                if await port_row.count() == 0:
                    log.warning(f"Port {port_idx} not found in UI table")
                    continue

                # Extract the port name from the Name column
                name_cell = port_row.locator('td').nth(3)  # Assuming Name is 4th column (0-indexed)
                actual_name = await name_cell.inner_text()

                log.info(f"Browser UI shows Port {port_idx} name: '{actual_name}' (expected: '{expected_name}')")

                # Check if it matches expected
                if actual_name.strip() == expected_name.strip():
                    log.info(f"✅ Browser verification SUCCESS: Port {port_idx} = '{actual_name}'")
                    return True, actual_name
                else:
                    log.warning(f"❌ Browser verification FAILED: Port {port_idx} expected '{expected_name}', got '{actual_name}'")
                    if attempt < max_attempts - 1:
                        # Wait before retry - changes might still be propagating
                        await asyncio.sleep(10)
                    else:
                        return False, actual_name

            except Exception as e:
                log.error(f"Browser verification error (attempt {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(5)

        return False, "verification_failed"

    async def verify_multiple_ports(
        self,
        verifications: List[Dict[str, any]]
    ) -> Dict[str, Tuple[bool, str]]:
        """
        Verify multiple port names across different devices.

        Args:
            verifications: List of dicts with keys:
                - device_name: str
                - device_ip: str
                - port_idx: int
                - expected_name: str

        Returns:
            Dict mapping "device_name:port_idx" to (success, actual_name)
        """
        results = {}

        for verification in verifications:
            device_name = verification["device_name"]
            device_ip = verification["device_ip"]
            port_idx = verification["port_idx"]
            expected_name = verification["expected_name"]

            key = f"{device_name}:{port_idx}"
            success, actual_name = await self.verify_port_name_in_ui(
                device_name, device_ip, port_idx, expected_name
            )
            results[key] = (success, actual_name)

            # Brief pause between devices
            await asyncio.sleep(2)

        return results


def verify_ports_with_browser(
    controller_url: str,
    username: str,
    password: str,
    verifications: List[Dict[str, any]]
) -> Dict[str, Tuple[bool, str]]:
    """
    Synchronous wrapper for browser-based port verification.

    Args:
        controller_url: UniFi controller URL
        username: UniFi username
        password: UniFi password
        verifications: List of port verification requests

    Returns:
        Dict mapping "device_name:port_idx" to (success, actual_name)
    """
    async def _run_verification():
        async with BrowserVerifier(controller_url, username, password) as verifier:
            return await verifier.verify_multiple_ports(verifications)

    try:
        return asyncio.run(_run_verification())
    except Exception as e:
        log.error(f"Browser verification failed: {e}")
        return {}


def create_verification_list_from_updates(
    device_updates: Dict[str, Dict[str, any]]
) -> List[Dict[str, any]]:
    """
    Convert device updates to verification list format.

    Args:
        device_updates: Dict mapping device_id to device info and port updates

    Returns:
        List of verification requests for browser checking
    """
    verifications = []

    for device_id, device_info in device_updates.items():
        device_name = device_info.get("name", "Unknown")
        device_ip = device_info.get("ip", "")
        port_updates = device_info.get("port_updates", {})

        for port_idx, expected_name in port_updates.items():
            verifications.append({
                "device_name": device_name,
                "device_ip": device_ip,
                "port_idx": int(port_idx),
                "expected_name": expected_name
            })

    return verifications