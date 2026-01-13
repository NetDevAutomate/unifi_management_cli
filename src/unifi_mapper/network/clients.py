"""Client management and fingerprinting.

This module provides tools for managing network clients including
device fingerprinting for automatic device type identification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING
from unifi_mapper.network.models import (
    ClientFingerprint,
    ClientInfo,
    ClientType,
)


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


class DeviceCategory(str, Enum):
    """Device category based on fingerprinting."""

    COMPUTER = 'computer'
    MOBILE = 'mobile'
    TABLET = 'tablet'
    SMART_TV = 'smart_tv'
    GAMING = 'gaming'
    IOT = 'iot'
    NETWORK = 'network'
    PRINTER = 'printer'
    VOIP = 'voip'
    CAMERA = 'camera'
    SMART_HOME = 'smart_home'
    MEDIA_PLAYER = 'media_player'
    WEARABLE = 'wearable'
    UNKNOWN = 'unknown'


@dataclass
class FingerprintResult:
    """Result of device fingerprinting analysis."""

    client_id: str
    mac_address: str
    category: DeviceCategory
    vendor: str | None = None
    os_name: str | None = None
    device_family: str | None = None
    confidence: float = 0.0  # 0.0 to 1.0
    raw_fingerprint: ClientFingerprint | None = None

    @property
    def description(self) -> str:
        """Human-readable device description."""
        parts = []
        if self.vendor:
            parts.append(self.vendor)
        if self.device_family:
            parts.append(self.device_family)
        if self.os_name:
            parts.append(f"({self.os_name})")
        return ' '.join(parts) if parts else f"Unknown {self.category.value}"


@dataclass
class ClientStats:
    """Statistics about connected clients."""

    total_clients: int = 0
    wired_clients: int = 0
    wireless_clients: int = 0
    vpn_clients: int = 0
    guest_clients: int = 0
    by_category: dict[DeviceCategory, int] = field(default_factory=dict)
    by_vendor: dict[str, int] = field(default_factory=dict)
    by_os: dict[str, int] = field(default_factory=dict)
    total_tx_bytes: int = 0
    total_rx_bytes: int = 0


# Common vendor prefixes for OUI lookup
_VENDOR_OUI_MAP = {
    '00:50:56': 'VMware',
    '00:0C:29': 'VMware',
    '00:1A:11': 'Google',
    '00:1B:63': 'Apple',
    '00:03:93': 'Apple',
    '00:05:02': 'Apple',
    '00:0A:27': 'Apple',
    '00:0A:95': 'Apple',
    '00:0D:93': 'Apple',
    '00:10:FA': 'Apple',
    '00:11:24': 'Apple',
    '00:14:51': 'Apple',
    '00:16:CB': 'Apple',
    '00:17:F2': 'Apple',
    '00:19:E3': 'Apple',
    '00:1C:B3': 'Apple',
    '00:1D:4F': 'Apple',
    '00:1E:52': 'Apple',
    '00:1E:C2': 'Apple',
    '00:1F:5B': 'Apple',
    '00:1F:F3': 'Apple',
    '00:21:E9': 'Apple',
    '00:22:41': 'Apple',
    '00:23:12': 'Apple',
    '00:23:32': 'Apple',
    '00:23:6C': 'Apple',
    '00:23:DF': 'Apple',
    '00:24:36': 'Apple',
    '00:25:00': 'Apple',
    '00:25:4B': 'Apple',
    '00:25:BC': 'Apple',
    '00:26:08': 'Apple',
    '00:26:4A': 'Apple',
    '00:26:B0': 'Apple',
    '00:26:BB': 'Apple',
    '30:9C:23': 'Apple',
    '34:36:3B': 'Apple',
    '38:C9:86': 'Apple',
    '3C:07:54': 'Apple',
    '40:6C:8F': 'Apple',
    '44:2A:60': 'Apple',
    '48:60:BC': 'Apple',
    '4C:57:CA': 'Apple',
    '54:26:96': 'Apple',
    '58:55:CA': 'Apple',
    '5C:59:48': 'Apple',
    '60:03:08': 'Apple',
    '64:20:0C': 'Apple',
    '68:5B:35': 'Apple',
    '6C:40:08': 'Apple',
    '70:DE:E2': 'Apple',
    '74:E1:B6': 'Apple',
    '78:31:C1': 'Apple',
    '7C:6D:62': 'Apple',
    '80:E6:50': 'Apple',
    '84:38:35': 'Apple',
    '88:63:DF': 'Apple',
    '8C:2D:AA': 'Apple',
    '90:72:40': 'Apple',
    '94:94:26': 'Apple',
    '98:FE:94': 'Apple',
    '9C:20:7B': 'Apple',
    'A0:ED:CD': 'Apple',
    'A4:67:06': 'Apple',
    'A8:5B:78': 'Apple',
    'AC:87:A3': 'Apple',
    'B0:34:95': 'Apple',
    'B4:18:D1': 'Apple',
    'B8:17:C2': 'Apple',
    'BC:52:B7': 'Apple',
    'C0:63:94': 'Apple',
    'C4:2C:03': 'Apple',
    'C8:69:CD': 'Apple',
    'CC:08:E0': 'Apple',
    'D0:25:98': 'Apple',
    'D4:9A:20': 'Apple',
    'D8:00:4D': 'Apple',
    'DC:2B:2A': 'Apple',
    'E0:B9:BA': 'Apple',
    'E4:98:D1': 'Apple',
    'E8:06:88': 'Apple',
    'EC:35:86': 'Apple',
    'F0:99:BF': 'Apple',
    'F4:5C:89': 'Apple',
    'F8:1E:DF': 'Apple',
    'FC:25:3F': 'Apple',
    '00:15:5D': 'Microsoft',
    '00:0D:3A': 'Microsoft',
    '00:17:FA': 'Microsoft',
    '00:1D:D8': 'Microsoft',
    '00:22:48': 'Microsoft',
    '28:18:78': 'Microsoft',
    '00:14:22': 'Dell',
    '00:06:5B': 'Dell',
    '00:08:74': 'Dell',
    '00:0B:DB': 'Dell',
    '00:0D:56': 'Dell',
    '00:0F:1F': 'Dell',
    '00:11:43': 'Dell',
    '00:12:3F': 'Dell',
    '00:13:72': 'Dell',
    '00:15:C5': 'Dell',
    '00:18:8B': 'Dell',
    '00:19:B9': 'Dell',
    '00:1A:A0': 'Dell',
    '00:1C:23': 'Dell',
    '00:1D:09': 'Dell',
    '00:1E:4F': 'Dell',
    '00:1E:C9': 'Dell',
    '00:21:70': 'Dell',
    '00:21:9B': 'Dell',
    '00:22:19': 'Dell',
    '00:23:AE': 'Dell',
    '00:24:E8': 'Dell',
    '00:25:64': 'Dell',
    '00:26:B9': 'Dell',
    '14:FE:B5': 'Dell',
    '18:03:73': 'Dell',
    '18:A9:9B': 'Dell',
    '18:DB:F2': 'Dell',
    '1C:40:24': 'Dell',
    '20:47:47': 'Dell',
    '24:B6:FD': 'Dell',
    'B0:83:FE': 'Dell',
    'B4:E1:0F': 'Dell',
    '00:26:57': 'Samsung',
    '00:12:47': 'Samsung',
    '00:15:B9': 'Samsung',
    '00:16:32': 'Samsung',
    '00:17:D5': 'Samsung',
    '00:18:AF': 'Samsung',
    '00:1A:8A': 'Samsung',
    '00:1B:98': 'Samsung',
    '00:1C:43': 'Samsung',
    '00:1D:25': 'Samsung',
    '00:1D:F6': 'Samsung',
    '00:1E:7D': 'Samsung',
    '00:1F:CC': 'Samsung',
    '00:21:19': 'Samsung',
    '00:21:D1': 'Samsung',
    '00:23:39': 'Samsung',
    '00:23:99': 'Samsung',
    '00:23:D6': 'Samsung',
    '00:24:54': 'Samsung',
    '00:24:90': 'Samsung',
    '00:24:91': 'Samsung',
    '00:24:E9': 'Samsung',
    '00:25:66': 'Samsung',
    '00:25:67': 'Samsung',
    '00:26:37': 'Samsung',
    'AC:5F:3E': 'Samsung',
    'B4:EF:39': 'Samsung',
    'B8:57:D8': 'Samsung',
    'B8:C6:8E': 'Samsung',
    'BC:20:A4': 'Samsung',
    'BC:44:86': 'Samsung',
    'C4:73:1E': 'Samsung',
    '00:50:F2': 'Intel',
    '00:02:B3': 'Intel',
    '00:03:47': 'Intel',
    '00:04:23': 'Intel',
    '00:07:E9': 'Intel',
    '00:0E:0C': 'Intel',
    '00:0E:35': 'Intel',
    '00:11:11': 'Intel',
    '00:12:F0': 'Intel',
    '00:13:02': 'Intel',
    '00:13:20': 'Intel',
    '00:13:CE': 'Intel',
    '00:13:E8': 'Intel',
    '00:15:00': 'Intel',
    '00:15:17': 'Intel',
    '00:16:6F': 'Intel',
    '00:16:76': 'Intel',
    '00:16:EA': 'Intel',
    '00:16:EB': 'Intel',
    '00:18:DE': 'Intel',
    '00:19:D1': 'Intel',
    '00:19:D2': 'Intel',
    '00:1B:21': 'Intel',
    '00:1B:77': 'Intel',
    '00:1C:BF': 'Intel',
    '00:1C:C0': 'Intel',
    '00:1D:E0': 'Intel',
    '00:1D:E1': 'Intel',
    '00:1E:64': 'Intel',
    '00:1E:65': 'Intel',
    '00:1E:67': 'Intel',
    '00:1F:3B': 'Intel',
    '00:1F:3C': 'Intel',
    '00:20:E0': 'Intel',
    '00:21:5C': 'Intel',
    '00:21:5D': 'Intel',
    '00:21:6A': 'Intel',
    '00:21:6B': 'Intel',
    '00:22:FA': 'Intel',
    '00:22:FB': 'Intel',
    '00:23:14': 'Intel',
    '00:23:15': 'Intel',
    '00:24:D6': 'Intel',
    '00:24:D7': 'Intel',
    '00:26:C6': 'Intel',
    '00:26:C7': 'Intel',
    '00:27:10': 'Intel',
    '3C:A9:F4': 'Intel',
    '54:EE:75': 'Intel',
    '5C:51:4F': 'Intel',
    '5C:C5:D4': 'Intel',
    '68:05:CA': 'Intel',
    '78:0C:B8': 'Intel',
    '80:86:F2': 'Intel',
    '98:4F:EE': 'Intel',
    'A4:4E:31': 'Intel',
    'A4:C4:94': 'Intel',
    'B4:B5:2F': 'Intel',
    'C8:0A:A9': 'Intel',
    'D8:FC:93': 'Intel',
    'DC:53:60': 'Intel',
    'E8:B1:FC': 'Intel',
    'F4:6D:04': 'Intel',
}

# Device category patterns based on fingerprint data
_CATEGORY_PATTERNS = {
    DeviceCategory.COMPUTER: ['Windows', 'macOS', 'Linux', 'Chrome OS', 'Ubuntu', 'Fedora', 'Debian'],
    DeviceCategory.MOBILE: ['iOS', 'Android', 'iPhone', 'iPad', 'Galaxy'],
    DeviceCategory.TABLET: ['iPad', 'Android Tablet', 'Surface', 'Fire Tablet'],
    DeviceCategory.SMART_TV: ['Smart TV', 'Roku', 'Fire TV', 'Chromecast', 'Apple TV', 'LG TV', 'Samsung TV'],
    DeviceCategory.GAMING: ['PlayStation', 'Xbox', 'Nintendo', 'Steam Deck'],
    DeviceCategory.IOT: ['IoT', 'Sensor', 'Smart', 'ESP32', 'ESP8266', 'Arduino'],
    DeviceCategory.PRINTER: ['Printer', 'Print', 'HP Printer', 'Canon', 'Epson', 'Brother'],
    DeviceCategory.VOIP: ['VoIP', 'Phone', 'Cisco Phone', 'Polycom', 'Yealink'],
    DeviceCategory.CAMERA: ['Camera', 'IP Cam', 'Security Camera', 'Ring', 'Nest Cam', 'UniFi Protect'],
    DeviceCategory.SMART_HOME: ['Nest', 'Ring', 'Hue', 'SmartThings', 'Home Assistant', 'Echo', 'HomePod'],
    DeviceCategory.MEDIA_PLAYER: ['Sonos', 'Roku', 'Apple TV', 'Shield', 'Plex'],
    DeviceCategory.WEARABLE: ['Watch', 'Fitbit', 'Garmin'],
    DeviceCategory.NETWORK: ['Router', 'Switch', 'Access Point', 'Gateway', 'UniFi'],
}


class ClientManager:
    """Manage network clients with fingerprinting.

    This class provides tools for managing and analyzing connected
    network clients including automatic device fingerprinting.

    Example:
        >>> manager = ClientManager(client)
        >>> clients = await manager.get_all_clients()
        >>> fingerprints = await manager.fingerprint_all_clients()
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the client manager.

        Args:
            client: Network API client.
        """
        self._client = client
        self._clients_cache: dict[str, ClientInfo] = {}

    async def refresh_cache(self) -> None:
        """Refresh the clients cache."""
        clients = await self._client.list_clients()
        self._clients_cache = {c.id: c for c in clients}
        log.debug(f"Cached {len(self._clients_cache)} clients")

    async def get_all_clients(self, refresh: bool = False) -> list[ClientInfo]:
        """Get all connected clients.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of connected clients.
        """
        if refresh or not self._clients_cache:
            await self.refresh_cache()
        return list(self._clients_cache.values())

    async def get_client_by_mac(self, mac_address: str) -> ClientInfo | None:
        """Get a client by MAC address.

        Args:
            mac_address: Client MAC address.

        Returns:
            Client info or None.
        """
        clients = await self.get_all_clients()
        mac_lower = mac_address.lower().replace('-', ':')
        for client in clients:
            if client.mac_address and client.mac_address.lower() == mac_lower:
                return client
        return None

    async def get_client_by_ip(self, ip_address: str) -> ClientInfo | None:
        """Get a client by IP address.

        Args:
            ip_address: Client IP address.

        Returns:
            Client info or None.
        """
        clients = await self.get_all_clients()
        for client in clients:
            if client.ip_address == ip_address:
                return client
        return None

    async def get_clients_by_type(self, client_type: ClientType) -> list[ClientInfo]:
        """Get clients by connection type.

        Args:
            client_type: Wired, wireless, or VPN.

        Returns:
            List of matching clients.
        """
        clients = await self.get_all_clients()
        return [c for c in clients if c.type == client_type]

    async def get_guest_clients(self) -> list[ClientInfo]:
        """Get all guest clients.

        Returns:
            List of guest clients.
        """
        clients = await self.get_all_clients()
        return [c for c in clients if c.is_guest]

    def fingerprint_client(self, client: ClientInfo) -> FingerprintResult:
        """Analyze a client's fingerprint.

        Args:
            client: Client information.

        Returns:
            Fingerprint analysis result.
        """
        category = DeviceCategory.UNKNOWN
        vendor = None
        os_name = None
        device_family = None
        confidence = 0.0

        # Try to get vendor from OUI
        if client.mac_address:
            vendor = self._lookup_vendor(client.mac_address)
            if vendor:
                confidence += 0.2

        # Analyze fingerprint data if available
        if client.fingerprint:
            fp = client.fingerprint

            if fp.dev_vendor:
                vendor = fp.dev_vendor
                confidence += 0.2

            if fp.os_name:
                os_name = fp.os_name
                confidence += 0.2

            if fp.dev_family:
                device_family = fp.dev_family
                confidence += 0.2

            # Determine category from fingerprint
            category = self._categorize_device(fp, client)
            if category != DeviceCategory.UNKNOWN:
                confidence += 0.2

        # Fallback categorization
        if category == DeviceCategory.UNKNOWN:
            category = self._fallback_categorization(client, vendor, os_name)

        return FingerprintResult(
            client_id=client.id,
            mac_address=client.mac_address or '',
            category=category,
            vendor=vendor,
            os_name=os_name,
            device_family=device_family,
            confidence=min(confidence, 1.0),
            raw_fingerprint=client.fingerprint,
        )

    async def fingerprint_all_clients(self) -> list[FingerprintResult]:
        """Fingerprint all connected clients.

        Returns:
            List of fingerprint results.
        """
        clients = await self.get_all_clients()
        return [self.fingerprint_client(c) for c in clients]

    async def get_client_stats(self) -> ClientStats:
        """Get statistics about connected clients.

        Returns:
            Client statistics.
        """
        clients = await self.get_all_clients()
        fingerprints = [self.fingerprint_client(c) for c in clients]

        stats = ClientStats(total_clients=len(clients))

        for client in clients:
            # Count by connection type
            if client.type == ClientType.WIRED:
                stats.wired_clients += 1
            elif client.type == ClientType.WIRELESS:
                stats.wireless_clients += 1
            elif client.type == ClientType.VPN:
                stats.vpn_clients += 1

            # Count guests
            if client.is_guest:
                stats.guest_clients += 1

            # Sum traffic
            stats.total_tx_bytes += client.tx_bytes
            stats.total_rx_bytes += client.rx_bytes

        # Count by category, vendor, OS
        for fp in fingerprints:
            stats.by_category[fp.category] = stats.by_category.get(fp.category, 0) + 1

            if fp.vendor:
                stats.by_vendor[fp.vendor] = stats.by_vendor.get(fp.vendor, 0) + 1

            if fp.os_name:
                stats.by_os[fp.os_name] = stats.by_os.get(fp.os_name, 0) + 1

        return stats

    async def authorize_guest(
        self,
        client_id: str,
        minutes: int = 60,
        down_kbps: int | None = None,
        up_kbps: int | None = None,
        bytes_quota: int | None = None,
    ) -> dict:
        """Authorize a guest client.

        Args:
            client_id: Client UUID.
            minutes: Access duration in minutes.
            down_kbps: Download rate limit in kbps.
            up_kbps: Upload rate limit in kbps.
            bytes_quota: Data usage limit in bytes.

        Returns:
            Authorization response.
        """
        return await self._client.authorize_guest(
            client_id=client_id,
            time_limit_minutes=minutes,
            rx_rate_limit_kbps=down_kbps,
            tx_rate_limit_kbps=up_kbps,
            data_usage_limit_mbytes=bytes_quota // (1024 * 1024) if bytes_quota else None,
        )

    async def unauthorize_guest(self, client_id: str) -> dict:
        """Revoke guest authorization.

        Args:
            client_id: Client UUID.

        Returns:
            Response.
        """
        return await self._client.unauthorize_guest(client_id)

    def _lookup_vendor(self, mac_address: str) -> str | None:
        """Look up vendor from MAC address OUI."""
        if not mac_address:
            return None

        # Normalize MAC address
        mac = mac_address.upper().replace('-', ':')
        oui = mac[:8]

        return _VENDOR_OUI_MAP.get(oui)

    def _categorize_device(
        self,
        fingerprint: ClientFingerprint,
        client: ClientInfo,
    ) -> DeviceCategory:
        """Categorize device based on fingerprint."""
        # Check dev_cat first (if provided by UniFi)
        if fingerprint.dev_cat:
            cat_lower = fingerprint.dev_cat.lower()
            for category, patterns in _CATEGORY_PATTERNS.items():
                for pattern in patterns:
                    if pattern.lower() in cat_lower:
                        return category

        # Check OS name
        if fingerprint.os_name:
            os_lower = fingerprint.os_name.lower()
            if 'windows' in os_lower or 'macos' in os_lower or 'linux' in os_lower:
                return DeviceCategory.COMPUTER
            if 'ios' in os_lower or 'android' in os_lower:
                # Distinguish tablet from phone
                if fingerprint.dev_family and 'ipad' in fingerprint.dev_family.lower():
                    return DeviceCategory.TABLET
                return DeviceCategory.MOBILE

        # Check device family
        if fingerprint.dev_family:
            family_lower = fingerprint.dev_family.lower()
            for category, patterns in _CATEGORY_PATTERNS.items():
                for pattern in patterns:
                    if pattern.lower() in family_lower:
                        return category

        return DeviceCategory.UNKNOWN

    def _fallback_categorization(
        self,
        client: ClientInfo,
        vendor: str | None,
        os_name: str | None,
    ) -> DeviceCategory:
        """Fallback categorization based on available data."""
        # Check name/hostname patterns
        name = (client.name or client.hostname or '').lower()

        name_patterns = {
            DeviceCategory.COMPUTER: ['desktop', 'laptop', 'pc', 'mac', 'workstation'],
            DeviceCategory.MOBILE: ['iphone', 'android', 'phone', 'mobile'],
            DeviceCategory.TABLET: ['ipad', 'tablet', 'surface'],
            DeviceCategory.SMART_TV: ['tv', 'roku', 'firetv', 'chromecast', 'appletv'],
            DeviceCategory.GAMING: ['playstation', 'ps4', 'ps5', 'xbox', 'switch', 'nintendo'],
            DeviceCategory.PRINTER: ['printer', 'print'],
            DeviceCategory.CAMERA: ['cam', 'camera', 'nvr', 'dvr'],
            DeviceCategory.SMART_HOME: ['nest', 'ring', 'echo', 'alexa', 'homepod', 'hue'],
        }

        for category, patterns in name_patterns.items():
            for pattern in patterns:
                if pattern in name:
                    return category

        # Vendor-based categorization
        if vendor:
            vendor_lower = vendor.lower()
            if vendor_lower in ['apple', 'microsoft', 'dell', 'hp', 'lenovo', 'asus']:
                return DeviceCategory.COMPUTER
            if vendor_lower in ['samsung', 'google', 'oneplus', 'xiaomi']:
                return DeviceCategory.MOBILE
            if vendor_lower in ['roku', 'amazon', 'google']:
                return DeviceCategory.MEDIA_PLAYER

        return DeviceCategory.UNKNOWN
