#!/usr/bin/env python3
"""
AXIS Device Provisioning Script

Reads configuration from ~/.config/axiscam/config.yaml and ensures all devices have:
- ataylor admin account
- ONVIF user account
- MQTT settings configured

Usage:
    python scripts/axis_provision.py [--dry-run] [--device NAME]
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml


@dataclass
class Device:
    name: str
    address: str
    port: int
    username: str
    password: str
    serial: str
    mqtt_topic: str
    model: str = ""
    vendor: str = "AXIS"


@dataclass
class UserConfig:
    name: str
    password: str
    role: str = "administrator"


@dataclass
class OnvifUser:
    name: str
    password: str


@dataclass
class MqttConfig:
    broker: str
    username: str
    password: str


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def parse_devices(config: dict) -> list[Device]:
    """Parse device configurations."""
    devices = []
    for dev in config.get("devices", []):
        mqtt_topic = dev.get("mqtt", {}).get("topic", f"axis/{dev.get('serial', 'unknown')}")
        devices.append(
            Device(
                name=dev["name"],
                address=dev["address"],
                port=dev.get("port", 80),
                username=dev["username"],
                password=dev["password"],
                serial=dev.get("serial", ""),
                mqtt_topic=mqtt_topic,
                model=dev.get("model", ""),
                vendor=dev.get("vendor", "AXIS"),
            )
        )
    return devices


class AxisProvisioner:
    """Provision AXIS devices with user accounts and MQTT settings."""

    def __init__(self, device: Device, dry_run: bool = False):
        self.device = device
        self.dry_run = dry_run
        self.base_url = f"http://{device.address}:{device.port}"
        self.auth = httpx.DigestAuth(device.username, device.password)

    async def check_connection(self, client: httpx.AsyncClient) -> bool:
        """Verify device is reachable and credentials work."""
        try:
            r = await client.post(
                f"{self.base_url}/axis-cgi/basicdeviceinfo.cgi",
                auth=self.auth,
                json={"apiVersion": "1.0", "method": "getAllProperties"},
                timeout=10.0,
            )
            return r.status_code == 200
        except Exception:
            return False

    async def get_users(self, client: httpx.AsyncClient) -> list[str]:
        """Get list of existing users."""
        try:
            # Try newer API first
            r = await client.post(
                f"{self.base_url}/axis-cgi/pwdgrp.cgi",
                auth=self.auth,
                json={"apiVersion": "1.0", "method": "getUsers"},
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                if "data" in data and "users" in data["data"]:
                    return [u["name"] for u in data["data"]["users"]]

            # Fallback to legacy API
            r = await client.get(
                f"{self.base_url}/axis-cgi/pwdgrp.cgi?action=get",
                auth=self.auth,
                timeout=10.0,
            )
            if r.status_code == 200:
                # Parse response like: admin="user1,user2"\noperator="user1,user3"
                # All users appear in one of these groups
                users = set()
                for line in r.text.split('\n'):
                    if '=' in line and not line.startswith('#'):
                        group_name, user_list = line.split('=', 1)
                        user_list = user_list.strip('"')
                        for user in user_list.split(','):
                            if user.strip():
                                users.add(user.strip())
                return list(users)
        except Exception:
            pass
        return []

    async def get_onvif_users(self, client: httpx.AsyncClient) -> tuple[list[str], bool]:
        """Get list of existing ONVIF users. Returns (users, onvif_supported)."""
        try:
            # Try the ONVIF user API
            r = await client.post(
                f"{self.base_url}/axis-cgi/onvifuser.cgi",
                auth=self.auth,
                json={"apiVersion": "1.0", "method": "getUsers"},
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                if "data" in data and "users" in data["data"]:
                    return [u["name"] for u in data["data"]["users"]], True
                return [], True
            elif r.status_code == 404:
                # ONVIF API not available - check if ONVIF is supported at all
                r2 = await client.get(
                    f"{self.base_url}/axis-cgi/param.cgi?action=list&group=root.ONVIF",
                    auth=self.auth,
                    timeout=10.0,
                )
                if r2.status_code == 200 and "Error" not in r2.text:
                    # ONVIF exists but different API - check digusers for onvif users
                    r3 = await client.get(
                        f"{self.base_url}/axis-cgi/pwdgrp.cgi?action=get",
                        auth=self.auth,
                        timeout=10.0,
                    )
                    if r3.status_code == 200:
                        # Look for digusers which contains encoded ONVIF users
                        for line in r3.text.split('\n'):
                            if line.startswith('digusers='):
                                users = line.split('=', 1)[1].strip('"').split(',')
                                # ONVIF users often have 'onvif' in the name or are base64-encoded
                                onvif_users = [u for u in users if 'onvif' in u.lower()]
                                return onvif_users, True
                    return [], True
                # ONVIF not supported on this device
                return [], False
        except Exception:
            pass
        return [], False

    async def get_mqtt_config(self, client: httpx.AsyncClient) -> dict:
        """Get current MQTT configuration."""
        mqtt_config = {}
        try:
            # Try MQTT client API
            r = await client.post(
                f"{self.base_url}/axis-cgi/mqtt/client.cgi",
                auth=self.auth,
                json={"apiVersion": "1.0", "method": "getClientStatus"},
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                if "data" in data:
                    mqtt_config = data["data"]
                    return mqtt_config

            # Fallback to param.cgi
            r = await client.get(
                f"{self.base_url}/axis-cgi/param.cgi?action=list&group=root.MQTT",
                auth=self.auth,
                timeout=10.0,
            )
            if r.status_code == 200:
                for line in r.text.split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.replace('root.MQTT.', '').lower()
                        mqtt_config[key] = value
        except Exception:
            pass
        return mqtt_config

    async def create_user(
        self, client: httpx.AsyncClient, username: str, password: str, role: str = "admin"
    ) -> tuple[bool, str]:
        """Create or update a user account."""
        if self.dry_run:
            return True, f"[DRY-RUN] Would create user '{username}' with role '{role}'"

        # Map role to AXIS privilege level
        # admin = full access, operator = PTZ + view, viewer = view only
        privilege_map = {"administrator": "admin", "operator": "operator", "viewer": "viewer"}
        privilege = privilege_map.get(role, "admin")

        try:
            # Try the user-management API first (newer devices)
            payload = {
                "apiVersion": "1.0",
                "method": "createUser",
                "params": {"user": {"name": username, "password": password, "privileges": {"admin": privilege == "admin"}}},
            }
            r = await client.post(
                f"{self.base_url}/axis-cgi/user/management.cgi",
                auth=self.auth,
                json=payload,
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                if "error" not in data:
                    return True, f"Created user '{username}'"
                # User might already exist, try update
                if data.get("error", {}).get("code") == 2100:  # Already exists
                    payload["method"] = "updateUser"
                    r = await client.post(
                        f"{self.base_url}/axis-cgi/user/management.cgi",
                        auth=self.auth,
                        json=payload,
                        timeout=10.0,
                    )
                    if r.status_code == 200 and "error" not in r.json():
                        return True, f"Updated user '{username}'"

            # Fallback to legacy pwdgrp.cgi
            r = await client.get(
                f"{self.base_url}/axis-cgi/pwdgrp.cgi?action=add&user={username}&pwd={password}&grp=users&sgrp={privilege}",
                auth=self.auth,
                timeout=10.0,
            )
            if r.status_code == 200 and "Error" not in r.text:
                return True, f"Created user '{username}' (legacy API)"

            # Try update if add failed
            r = await client.get(
                f"{self.base_url}/axis-cgi/pwdgrp.cgi?action=update&user={username}&pwd={password}",
                auth=self.auth,
                timeout=10.0,
            )
            if r.status_code == 200:
                return True, f"Updated user '{username}' (legacy API)"

            return False, f"Failed to create/update user '{username}'"

        except Exception as e:
            return False, f"Error creating user '{username}': {e}"

    async def configure_onvif_user(
        self, client: httpx.AsyncClient, username: str, password: str
    ) -> tuple[bool, str]:
        """Configure ONVIF user account."""
        if self.dry_run:
            return True, f"[DRY-RUN] Would configure ONVIF user '{username}'"

        try:
            # ONVIF users are typically configured via param.cgi
            # Check if ONVIF is enabled first
            r = await client.get(
                f"{self.base_url}/axis-cgi/param.cgi?action=list&group=root.ONVIF",
                auth=self.auth,
                timeout=10.0,
            )

            if r.status_code == 200:
                # Enable ONVIF if not enabled
                await client.get(
                    f"{self.base_url}/axis-cgi/param.cgi?action=update&root.ONVIF.Enable=yes",
                    auth=self.auth,
                    timeout=10.0,
                )

            # Try the ONVIF user management API
            payload = {
                "apiVersion": "1.0",
                "method": "addUser",
                "params": {
                    "user": username,
                    "password": password,
                    "userLevel": "Operator",  # Administrator, Operator, User, Anonymous
                },
            }
            r = await client.post(
                f"{self.base_url}/axis-cgi/onvifuser.cgi",
                auth=self.auth,
                json=payload,
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                if "error" not in data:
                    return True, f"Created ONVIF user '{username}'"
                # Try update if exists
                payload["method"] = "updateUser"
                r = await client.post(
                    f"{self.base_url}/axis-cgi/onvifuser.cgi",
                    auth=self.auth,
                    json=payload,
                    timeout=10.0,
                )
                if r.status_code == 200 and "error" not in r.json():
                    return True, f"Updated ONVIF user '{username}'"

            # Fallback - some devices use pwdgrp with onvif group
            r = await client.get(
                f"{self.base_url}/axis-cgi/pwdgrp.cgi?action=add&user={username}&pwd={password}&grp=onvif&comment=ONVIF+User",
                auth=self.auth,
                timeout=10.0,
            )
            if r.status_code == 200 and "Error" not in r.text:
                return True, f"Created ONVIF user '{username}' (legacy)"

            return False, f"Could not configure ONVIF user (device may not support ONVIF)"

        except Exception as e:
            return False, f"Error configuring ONVIF user: {e}"

    async def configure_mqtt(
        self, client: httpx.AsyncClient, broker: str, username: str, password: str, topic: str
    ) -> tuple[bool, str]:
        """Configure MQTT settings."""
        if self.dry_run:
            return True, f"[DRY-RUN] Would configure MQTT: broker={broker}, topic={topic}"

        try:
            # Parse broker URL
            broker_host = broker.replace("mqtt://", "").replace("mqtts://", "")
            broker_port = 1883
            if ":" in broker_host:
                broker_host, port_str = broker_host.rsplit(":", 1)
                broker_port = int(port_str)
            use_tls = broker.startswith("mqtts://")

            # Try the MQTT client API (newer devices)
            payload = {
                "apiVersion": "1.0",
                "method": "activateClient",
                "params": {
                    "server": {"protocol": "tcp", "host": broker_host, "port": broker_port},
                    "clientId": self.device.serial,
                    "baseTopic": topic,
                    "auth": {"username": username, "password": password},
                },
            }

            r = await client.post(
                f"{self.base_url}/axis-cgi/mqtt/client.cgi",
                auth=self.auth,
                json=payload,
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                if "error" not in data:
                    return True, f"Configured MQTT client: {broker} topic={topic}"

            # Fallback to param.cgi for older devices
            params = {
                "root.MQTT.Enable": "yes",
                "root.MQTT.Host": broker_host,
                "root.MQTT.Port": str(broker_port),
                "root.MQTT.Username": username,
                "root.MQTT.Password": password,
                "root.MQTT.BaseTopic": topic,
                "root.MQTT.ClientID": self.device.serial,
            }
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            r = await client.get(
                f"{self.base_url}/axis-cgi/param.cgi?action=update&{param_str}",
                auth=self.auth,
                timeout=10.0,
            )
            if r.status_code == 200 and "Error" not in r.text:
                return True, f"Configured MQTT via params: {broker} topic={topic}"

            return False, "MQTT configuration not supported on this device"

        except Exception as e:
            return False, f"Error configuring MQTT: {e}"

    async def provision(
        self, users: list[UserConfig], onvif_users: list[OnvifUser], mqtt: MqttConfig
    ) -> dict:
        """Run full provisioning for this device."""
        results = {"device": self.device.name, "address": self.device.address, "status": "unknown", "details": []}

        async with httpx.AsyncClient() as client:
            # Check connection
            if not await self.check_connection(client):
                results["status"] = "unreachable"
                results["details"].append({"task": "connect", "success": False, "message": "Could not connect to device"})
                return results

            results["status"] = "connected"

            # Get existing configuration
            existing_users = await self.get_users(client)
            existing_onvif, onvif_supported = await self.get_onvif_users(client)
            existing_mqtt = await self.get_mqtt_config(client)

            # Check/create user accounts
            for user in users:
                if user.name in existing_users:
                    results["details"].append({
                        "task": f"user:{user.name}",
                        "success": True,
                        "message": f"User '{user.name}' already exists",
                        "action": "none"
                    })
                else:
                    success, msg = await self.create_user(client, user.name, user.password, user.role)
                    results["details"].append({
                        "task": f"user:{user.name}",
                        "success": success,
                        "message": msg,
                        "action": "create"
                    })

            # Check/configure ONVIF users
            for onvif_user in onvif_users:
                if not onvif_supported:
                    results["details"].append({
                        "task": f"onvif:{onvif_user.name}",
                        "success": True,
                        "message": "ONVIF not supported on this device (skipped)",
                        "action": "skip"
                    })
                elif onvif_user.name in existing_onvif:
                    results["details"].append({
                        "task": f"onvif:{onvif_user.name}",
                        "success": True,
                        "message": f"ONVIF user '{onvif_user.name}' already exists",
                        "action": "none"
                    })
                else:
                    success, msg = await self.configure_onvif_user(client, onvif_user.name, onvif_user.password)
                    results["details"].append({
                        "task": f"onvif:{onvif_user.name}",
                        "success": success,
                        "message": msg,
                        "action": "create"
                    })

            # Check/configure MQTT
            mqtt_configured = False
            if existing_mqtt:
                # Check if MQTT is already configured with correct settings
                current_host = existing_mqtt.get("host", existing_mqtt.get("server", {}).get("host", ""))
                current_topic = existing_mqtt.get("basetopic", existing_mqtt.get("baseTopic", ""))
                expected_host = mqtt.broker.replace("mqtt://", "").replace("mqtts://", "").split(":")[0]

                if current_host == expected_host and current_topic == self.device.mqtt_topic:
                    mqtt_configured = True
                    results["details"].append({
                        "task": "mqtt",
                        "success": True,
                        "message": f"MQTT already configured: {mqtt.broker} topic={self.device.mqtt_topic}",
                        "action": "none"
                    })

            if not mqtt_configured:
                success, msg = await self.configure_mqtt(
                    client, mqtt.broker, mqtt.username, mqtt.password, self.device.mqtt_topic
                )
                results["details"].append({
                    "task": "mqtt",
                    "success": success,
                    "message": msg,
                    "action": "configure"
                })

            # Determine overall status
            all_success = all(d.get("success", False) for d in results["details"])
            any_changes = any(d.get("action") != "none" for d in results["details"])
            if all_success:
                results["status"] = "success" if any_changes else "up-to-date"
            else:
                results["status"] = "partial"

        return results


async def main():
    parser = argparse.ArgumentParser(description="Provision AXIS devices")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--device", type=str, help="Provision only the specified device by name")
    parser.add_argument(
        "--config", type=str, default="~/.config/axiscam/config.yaml", help="Path to config file"
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    print(f"Loading config from: {config_path}")
    config = load_config(config_path)

    # Parse configuration
    devices = parse_devices(config)
    users = [UserConfig(u["name"], u["password"], u.get("role", "administrator")) for u in config.get("users", [])]
    onvif_users = [OnvifUser(u["name"], u["password"]) for u in config.get("onvif", {}).get("users", [])]
    mqtt_config = MqttConfig(
        broker=config.get("mqtt", {}).get("broker", ""),
        username=config.get("mqtt", {}).get("username", ""),
        password=config.get("mqtt", {}).get("password", ""),
    )

    # Filter devices if specified
    if args.device:
        devices = [d for d in devices if d.name.lower() == args.device.lower()]
        if not devices:
            print(f"Error: Device '{args.device}' not found in config")
            sys.exit(1)

    print(f"\nProvisioning {len(devices)} device(s)...")
    print(f"  Users to create: {[u.name for u in users]}")
    print(f"  ONVIF users: {[u.name for u in onvif_users]}")
    print(f"  MQTT broker: {mqtt_config.broker}")
    if args.dry_run:
        print("\n[DRY-RUN MODE - No changes will be made]\n")
    print("-" * 60)

    # Provision each device
    for device in devices:
        print(f"\n{device.name} ({device.address}) - {device.model}")
        print(f"  Serial: {device.serial}")
        print(f"  MQTT Topic: {device.mqtt_topic}")

        provisioner = AxisProvisioner(device, dry_run=args.dry_run)
        results = await provisioner.provision(users, onvif_users, mqtt_config)

        for detail in results["details"]:
            action = detail.get("action", "")
            if action == "none":
                status_icon = "○"  # Already configured
            elif action == "skip":
                status_icon = "–"  # Skipped (not applicable)
            elif detail["success"]:
                status_icon = "✓"  # Created/configured
            else:
                status_icon = "✗"  # Failed
            print(f"  {status_icon} {detail['task']}: {detail['message']}")

        print(f"  Status: {results['status']}")

    print("\n" + "=" * 60)
    print("Provisioning complete")


if __name__ == "__main__":
    asyncio.run(main())
