"""Async UniFi controller API client.

Provides authenticated access to UniFi Controller API with support for:
- Device management and monitoring
- Port configuration and mirroring (SPAN)
- LLDP topology discovery
- Network statistics and diagnostics

Supports both UniFi OS (UDM/UDR) and legacy controllers with:
- Token-based authentication (X-API-KEY header) - preferred
- Username/password authentication - fallback
"""

import httpx
from loguru import logger
from typing import Any
from unifi_mapper.core.utils.auth import Credentials, get_credentials
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


class UniFiClient:
    """Async UniFi Controller API client.

    Supports both UniFi OS (UDM/UDR) and legacy controllers with automatic
    detection and endpoint routing.
    """

    def __init__(self, credentials: Credentials | None = None):
        """Initialize UniFi client.

        Args:
            credentials: Optional credentials (will auto-fetch if not provided)
        """
        self._credentials = credentials
        self._client: httpx.AsyncClient | None = None
        self._session_token: str | None = None
        self._site_name: str = 'default'
        self._authenticated = False
        self._is_unifi_os: bool = False
        self._auth_method: str | None = None

    async def __aenter__(self) -> 'UniFiClient':
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def connect(self) -> None:
        """Establish connection to UniFi controller."""
        if self._authenticated:
            return

        # Get credentials if not provided
        if not self._credentials:
            self._credentials = await get_credentials()

        # Create HTTP client
        base_url = f'https://{self._credentials.host}:{self._credentials.port}'
        self._client = httpx.AsyncClient(
            base_url=base_url,
            verify=self._credentials.verify_ssl,
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

        # Detect UniFi OS type first
        await self._detect_unifi_os()

        # Authenticate
        await self._authenticate()

        # Set site name
        self._site_name = self._credentials.site

        logger.info(
            'Connected to UniFi controller',
            host=self._credentials.host,
            site=self._site_name,
            is_unifi_os=self._is_unifi_os,
            auth_method=self._auth_method,
        )

    async def disconnect(self) -> None:
        """Disconnect from UniFi controller."""
        if self._client:
            try:
                if self._authenticated and self._auth_method == 'password':
                    # Only logout for password-based sessions
                    logout_endpoint = '/api/auth/logout' if self._is_unifi_os else '/api/logout'
                    await self._client.post(logout_endpoint)
            except Exception:
                pass  # Best effort logout
            finally:
                await self._client.aclose()
                self._client = None
                self._authenticated = False
                self._session_token = None
                self._auth_method = None

    async def _detect_unifi_os(self) -> None:
        """Detect if controller is UniFi OS device (UDM/UDR).

        UniFi OS controllers return 200 on /api/system endpoint.
        Legacy controllers return 401/404.
        """
        if not self._client:
            return

        try:
            response = await self._client.get('/api/system', timeout=10.0)
            self._is_unifi_os = response.status_code == 200
            logger.debug(
                f'UniFi OS detection: {self._is_unifi_os} (status: {response.status_code})'
            )
        except Exception as e:
            logger.debug(f'UniFi OS detection failed, assuming legacy controller: {e}')
            self._is_unifi_os = False

    async def _authenticate(self) -> None:
        """Authenticate with UniFi controller.

        Tries token-based auth first (if available), then falls back to password.
        """
        if not self._client or not self._credentials:
            raise ToolError(
                message='Client not initialized',
                error_code=ErrorCodes.API_ERROR,
            )

        # Try token authentication first (preferred for UniFi OS)
        if self._credentials.has_token:
            logger.debug('Attempting token-based authentication')
            if await self._try_token_auth():
                return

        # Fall back to password authentication
        if self._credentials.has_password:
            logger.debug('Attempting password-based authentication')
            if await self._try_password_auth():
                return

        # All methods failed
        raise ToolError(
            message='Authentication failed - all methods exhausted',
            error_code=ErrorCodes.AUTHENTICATION_FAILED,
            suggestion='Check API token or username/password credentials',
        )

    async def _try_token_auth(self) -> bool:
        """Attempt token-based authentication using X-API-KEY header.

        Returns:
            True if authentication successful, False otherwise
        """
        if not self._client or not self._credentials or not self._credentials.api_token:
            return False

        # Set token header
        self._client.headers['X-API-KEY'] = self._credentials.api_token

        try:
            # Verify token by checking self endpoint
            verify_endpoint = self.build_path('self')
            response = await self._client.get(verify_endpoint, timeout=10.0)

            if response.status_code == 200:
                self._authenticated = True
                self._auth_method = 'token'
                logger.info('Token authentication successful')
                return True

            logger.debug(f'Token auth failed with status {response.status_code}')

        except Exception as e:
            logger.debug(f'Token authentication failed: {e}')

        # Clean up failed token header
        self._client.headers.pop('X-API-KEY', None)
        return False

    async def _try_password_auth(self) -> bool:
        """Attempt username/password authentication.

        Uses different endpoints for UniFi OS vs legacy controllers.

        Returns:
            True if authentication successful, False otherwise
        """
        if not self._client or not self._credentials:
            return False

        if not self._credentials.username or not self._credentials.password:
            return False

        login_data = {
            'username': self._credentials.username,
            'password': self._credentials.password,
            'remember': False,
        }

        # Use correct endpoint based on controller type
        login_endpoint = '/api/auth/login' if self._is_unifi_os else '/api/login'

        try:
            response = await self._client.post(login_endpoint, json=login_data)

            if response.status_code == 200:
                # Extract session token from cookies
                for cookie in response.cookies:
                    if cookie.name in ('unifises', 'TOKEN'):
                        self._session_token = cookie.value
                        break

                self._authenticated = True
                self._auth_method = 'password'
                logger.info(f'Password authentication successful (endpoint: {login_endpoint})')
                return True

            logger.debug(f'Password auth failed with status {response.status_code}')

        except httpx.HTTPStatusError as e:
            logger.debug(f'Password authentication HTTP error: {e.response.status_code}')
        except Exception as e:
            logger.debug(f'Password authentication failed: {e}')

        return False

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        """Make authenticated GET request to UniFi API.

        Args:
            path: API path (e.g., '/proxy/network/api/s/default/stat/device')
            **params: Query parameters

        Returns:
            JSON response data

        Raises:
            ToolError: For API errors, authentication issues, or network problems
        """
        if not self._authenticated:
            await self.connect()

        return await self._request('GET', path, params=params)

    async def post(self, path: str, data: Any = None, **params: Any) -> dict[str, Any]:
        """Make authenticated POST request to UniFi API.

        Args:
            path: API path
            data: POST data (JSON serializable)
            **params: Query parameters

        Returns:
            JSON response data
        """
        if not self._authenticated:
            await self.connect()

        return await self._request('POST', path, json=data, params=params)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Make authenticated request to UniFi API."""
        if not self._client:
            raise ToolError(
                message='Client not connected',
                error_code=ErrorCodes.API_ERROR,
            )

        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()

            data = response.json()

            # Check UniFi API response format
            if isinstance(data, dict) and 'meta' in data:
                if data['meta'].get('rc') == 'error':
                    error_msg = data['meta'].get('msg', 'Unknown API error')
                    raise ToolError(
                        message=f'UniFi API error: {error_msg}',
                        error_code=ErrorCodes.API_ERROR,
                    )

                # Return data payload
                return data.get('data', [])

            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # Re-authenticate and retry once
                self._authenticated = False
                await self._authenticate()
                return await self._request(method, path, **kwargs)
            else:
                raise ToolError(
                    message=f'HTTP {e.response.status_code}: {e.response.text}',
                    error_code=ErrorCodes.API_ERROR,
                )
        except httpx.RequestError as e:
            raise ToolError(
                message=f'Request failed: {e}',
                error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                suggestion='Check network connectivity and controller status',
            )

    async def put(self, path: str, data: Any = None, **params: Any) -> dict[str, Any]:
        """Make authenticated PUT request to UniFi API.

        Args:
            path: API path
            data: PUT data (JSON serializable)
            **params: Query parameters

        Returns:
            JSON response data
        """
        if not self._authenticated:
            await self.connect()

        return await self._request('PUT', path, json=data, params=params)

    def build_path(self, endpoint: str) -> str:
        """Build full API path with site.

        Args:
            endpoint: API endpoint (e.g., 'stat/device')

        Returns:
            Full path (e.g., '/proxy/network/api/s/default/stat/device')
        """
        return f'/proxy/network/api/s/{self._site_name}/{endpoint}'

    # =========================================================================
    # Device & Port Methods (for port mirroring and topology)
    # =========================================================================

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get all devices from the UniFi controller.

        Returns:
            List of device dictionaries with full details
        """
        path = self.build_path('stat/device')
        return await self.get(path)

    async def get_device(self, device_id: str) -> dict[str, Any] | None:
        """Get a specific device by ID.

        Args:
            device_id: UniFi device ID (MAC or _id)

        Returns:
            Device dictionary or None if not found
        """
        devices = await self.get_devices()
        for device in devices:
            if device.get('_id') == device_id or device.get('mac') == device_id:
                return device
        return None

    async def get_device_ports(self, device_id: str) -> list[dict[str, Any]]:
        """Get port table for a specific device.

        Args:
            device_id: UniFi device ID

        Returns:
            List of port configurations
        """
        device = await self.get_device(device_id)
        if device:
            return device.get('port_table', [])
        return []

    async def get_clients(self) -> list[dict[str, Any]]:
        """Get all connected clients from the UniFi controller.

        Returns:
            List of client dictionaries with connection details
        """
        path = self.build_path('stat/sta')
        return await self.get(path)

    async def get_networks(self) -> list[dict[str, Any]]:
        """Get all network configurations from the UniFi controller.

        Returns:
            List of network configuration dictionaries
        """
        path = self.build_path('rest/networkconf')
        return await self.get(path)

    # Valid speeds per UniFi API validation pattern
    VALID_SPEEDS = {10, 100, 1000, 2500, 5000, 10000, 20000, 25000, 40000, 50000, 100000}

    async def update_device_port(
        self,
        device_id: str,
        port_overrides: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update port configuration on a device with persistence fix.

        IMPORTANT: This method uses port_overrides (writeable) not port_table (read-only).
        It includes device identifiers and config versions for proper persistence.

        Args:
            device_id: UniFi device ID
            port_overrides: List of port override configurations

        Returns:
            API response
        """
        # Get current device for identifiers and existing overrides
        device = await self.get_device(device_id)
        if not device:
            raise ToolError(
                message=f'Device {device_id} not found',
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
            )

        # Get existing port_overrides to merge with
        existing_overrides = device.get('port_overrides', [])
        existing_map = {po['port_idx']: po for po in existing_overrides if 'port_idx' in po}

        # Get port_table for reference (speed, autoneg status)
        port_table = device.get('port_table', [])
        port_table_map = {p['port_idx']: p for p in port_table if 'port_idx' in p}

        # Validate and clean port_overrides
        validated_overrides = []
        updated_port_idxs = set()

        for override in port_overrides:
            port_idx = override.get('port_idx')
            if port_idx is None:
                continue

            updated_port_idxs.add(port_idx)

            # Start with existing override or new dict
            if port_idx in existing_map:
                clean_override = existing_map[port_idx].copy()
            else:
                clean_override = {'port_idx': port_idx}

            # Update with new values
            for key, value in override.items():
                if key == 'speed':
                    # Only include valid speed values
                    if value in self.VALID_SPEEDS:
                        clean_override['speed'] = value
                    # Skip invalid speeds (0, None, etc.)
                else:
                    clean_override[key] = value

            # If autoneg is enabled, don't set explicit speed
            port_data = port_table_map.get(port_idx, {})
            if port_data.get('autoneg', False) and 'speed' in clean_override:
                del clean_override['speed']

            validated_overrides.append(clean_override)

        # Add unchanged existing overrides (also validate their speeds)
        for port_idx, existing in existing_map.items():
            if port_idx not in updated_port_idxs:
                cleaned = {
                    k: v for k, v in existing.items() if k != 'speed' or v in self.VALID_SPEEDS
                }
                if 'port_idx' in cleaned:
                    validated_overrides.append(cleaned)

        # Build payload with device identifiers (REQUIRED for persistence)
        update_payload = {
            '_id': device['_id'],
            'mac': device['mac'],
            'port_overrides': validated_overrides,
        }

        # Include config version fields for proper persistence
        for field in ['config_version', 'cfgversion', 'config_revision']:
            if field in device:
                update_payload[field] = device[field]

        # Send update
        path = self.build_path(f'rest/device/{device_id}')
        result = await self.put(path, update_payload)

        # Force provision to apply changes without restart
        await self.force_provision(device['mac'])

        return result

    async def force_provision(self, device_mac: str) -> bool:
        """Force device to apply configuration changes without restart.

        Args:
            device_mac: Device MAC address

        Returns:
            True if provision command succeeded
        """
        try:
            path = self.build_path('cmd/devmgr')
            await self.post(path, {'cmd': 'force-provision', 'mac': device_mac})
            logger.debug(f'Force provision triggered for {device_mac}')
            return True
        except Exception as e:
            logger.warning(f'Force provision failed for {device_mac}: {e}')
            return False

    async def update_port_names(
        self,
        device_id: str,
        port_updates: dict[int, str],
    ) -> bool:
        """Update port names with persistence guarantee.

        Convenience method that builds proper port_overrides from name updates.

        Args:
            device_id: Device _id to update
            port_updates: Mapping of port_idx to new name

        Returns:
            True if update succeeded
        """
        port_overrides = [
            {'port_idx': port_idx, 'name': name} for port_idx, name in port_updates.items()
        ]

        try:
            await self.update_device_port(device_id, port_overrides)
            return True
        except Exception as e:
            logger.error(f'Port name update failed: {e}')
            return False

    async def get_lldp_table(self, device_id: str) -> list[dict[str, Any]]:
        """Get LLDP neighbor table for a device.

        Args:
            device_id: UniFi device ID

        Returns:
            List of LLDP neighbor entries
        """
        device = await self.get_device(device_id)
        if device:
            return device.get('lldp_table', [])
        return []

    async def get_network_topology(self) -> dict[str, Any]:
        """Discover network topology using LLDP data from all devices.

        Returns:
            Dictionary containing topology information:
            - devices: List of all devices with their details
            - connections: List of device-to-device connections via LLDP
            - switches: List of switch devices only
        """
        devices = await self.get_devices()

        topology = {
            'devices': [],
            'connections': [],
            'switches': [],
        }

        # Build MAC to device mapping for LLDP resolution
        mac_to_device: dict[str, dict[str, Any]] = {}
        for device in devices:
            mac = device.get('mac', '').lower()
            if mac:
                mac_to_device[mac] = device
                # Also store without colons for flexible matching
                mac_to_device[mac.replace(':', '')] = device

        for device in devices:
            device_info = {
                'id': device.get('_id'),
                'mac': device.get('mac'),
                'name': device.get('name', 'Unknown'),
                'model': device.get('model', 'Unknown'),
                'type': device.get('type', 'Unknown'),
                'ip': device.get('ip', ''),
                'adopted': device.get('adopted', False),
                'state': device.get('state', 0),
            }
            topology['devices'].append(device_info)

            # Track switches
            if device.get('type') in ('usw', 'switch'):
                topology['switches'].append(device_info)

                # Process LLDP neighbors for topology
                lldp_table = device.get('lldp_table', [])
                for neighbor in lldp_table:
                    chassis_id = neighbor.get('chassis_id', '').lower()
                    # Also try without colons for matching
                    chassis_id_clean = chassis_id.replace(':', '')
                    remote_device = mac_to_device.get(chassis_id) or mac_to_device.get(
                        chassis_id_clean
                    )

                    # Try multiple field names for port index (UniFi versions may differ)
                    local_port = (
                        neighbor.get('local_port_idx')
                        or neighbor.get('port_idx')
                        or neighbor.get('lldp_local_port_idx')
                    )

                    if remote_device:
                        connection = {
                            'local_device_id': device.get('_id'),
                            'local_device_name': device.get('name'),
                            'local_port': local_port,
                            'local_port_name': neighbor.get('local_port_name', ''),
                            'remote_device_id': remote_device.get('_id'),
                            'remote_device_name': remote_device.get('name'),
                            'remote_port_name': neighbor.get('port_id', ''),
                            'chassis_id': chassis_id,
                            'is_unifi_device': True,
                        }
                        topology['connections'].append(connection)

        return topology

    @property
    def site_name(self) -> str:
        """Get the current site name."""
        return self._site_name

    @property
    def is_connected(self) -> bool:
        """Check if client is connected and authenticated."""
        return self._authenticated and self._client is not None
