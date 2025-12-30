import json
import logging
import os

from .models import DeviceInfo, PortInfo
from .network_topology import NetworkTopology
from .report_generator import generate_port_mapping_report

log = logging.getLogger(__name__)


def infer_connections_from_clients(api_client, site_id, devices):
    """
    Infer connections between devices based on client information.

    Args:
        api_client: UnifiApiClient instance
        site_id: Site ID
        devices: Dictionary of devices

    Returns:
        List of inferred connections
    """
    inferred_connections = []

    try:
        # Get all clients
        clients_endpoint = (
            f"{api_client.base_url}/proxy/network/api/s/{site_id}/stat/sta"
            if api_client.is_unifi_os
            else f"{api_client.base_url}/api/s/{site_id}/stat/sta"
        )
        clients_response = api_client.session.get(
            clients_endpoint, timeout=api_client.timeout
        )

        if clients_response.status_code == 200:
            clients_data = clients_response.json()
            if "data" in clients_data:
                clients = clients_data["data"]

                # Create a map of MAC addresses to device IDs
                mac_to_device_id = {}
                for device_id, device in devices.items():
                    mac_to_device_id[device.mac.lower()] = device_id
                    # Also add without colons
                    mac_to_device_id[device.mac.lower().replace(":", "")] = device_id

                # Process each client
                for client in clients:
                    # Check if this client is a device we know about
                    client_mac = client.get("mac", "").lower()
                    if client_mac in mac_to_device_id:
                        target_device_id = mac_to_device_id[client_mac]

                        # Check if this client is connected to a switch
                        sw_mac = client.get("sw_mac", "").lower()
                        sw_port = client.get("sw_port")

                        if sw_mac and sw_port and sw_mac in mac_to_device_id:
                            source_device_id = mac_to_device_id[sw_mac]

                            # Create an inferred connection
                            inferred_connections.append(
                                {
                                    "source_device_id": source_device_id,
                                    "target_device_id": target_device_id,
                                    "source_port_idx": sw_port,
                                    "source_port_name": f"Port {sw_port}",
                                    "target_port_idx": 1,  # Assume port 1 for the target device
                                    "target_port_name": "Port 1",
                                    "inferred": True,
                                }
                            )
    except Exception as e:
        log.error(f"Error inferring connections from clients: {e}")

    return inferred_connections


def infer_device_connections(api_client, site_id, devices):
    """
    Infer connections between devices based on various data sources.

    Args:
        api_client: UnifiApiClient instance
        site_id: Site ID
        devices: Dictionary of devices

    Returns:
        List of inferred connections
    """
    inferred_connections = []

    # First, try to infer connections from client information
    client_connections = infer_connections_from_clients(api_client, site_id, devices)
    inferred_connections.extend(client_connections)

    # Next, try to infer connections from IP subnet relationships
    subnet_connections = infer_connections_from_subnets(devices)
    inferred_connections.extend(subnet_connections)

    # Finally, try to infer connections from device types and names
    type_connections = infer_connections_from_device_types(devices)
    inferred_connections.extend(type_connections)

    return inferred_connections


def infer_connections_from_subnets(devices):
    """
    Infer connections between devices based on IP subnet relationships.

    Args:
        devices: Dictionary of devices

    Returns:
        List of inferred connections
    """
    inferred_connections = []

    try:
        # Group devices by subnet
        subnet_devices = {}
        for device_id, device in devices.items():
            # Skip devices without IP addresses
            if not device.ip:
                continue

            # Extract the subnet (first 3 octets)
            ip_parts = device.ip.split(".")
            if len(ip_parts) == 4:
                subnet = ".".join(ip_parts[:3])
                if subnet not in subnet_devices:
                    subnet_devices[subnet] = []
                subnet_devices[subnet].append(device_id)

        # For each subnet, find potential routers/gateways and connect other devices to them
        for subnet, device_ids in subnet_devices.items():
            # Skip subnets with only one device
            if len(device_ids) <= 1:
                continue

            # Find potential routers/gateways in this subnet
            routers = []
            for device_id in device_ids:
                device = devices[device_id]
                if (
                    "udm" in device.model.lower()
                    or "usg" in device.model.lower()
                    or "gateway" in device.model.lower()
                    or "router" in device.model.lower()
                ):
                    routers.append(device_id)

            # If no routers found, look for switches
            if not routers:
                for device_id in device_ids:
                    device = devices[device_id]
                    if (
                        "usw" in device.model.lower()
                        or "switch" in device.model.lower()
                    ):
                        routers.append(device_id)

            # If still no routers found, use the first device
            if not routers and device_ids:
                routers.append(device_ids[0])

            # Connect other devices to the first router
            if routers:
                router_id = routers[0]
                for device_id in device_ids:
                    if device_id != router_id:
                        # Create an inferred connection
                        inferred_connections.append(
                            {
                                "source_device_id": router_id,
                                "target_device_id": device_id,
                                "source_port_idx": 1,  # Assume port 1 for the router
                                "source_port_name": "Port 1",
                                "target_port_idx": 1,  # Assume port 1 for the target device
                                "target_port_name": "Port 1",
                                "inferred": True,
                            }
                        )
    except Exception as e:
        log.error(f"Error inferring connections from subnets: {e}")

    return inferred_connections


def infer_connections_from_device_types(devices):
    """
    Infer connections between devices based on device types and names.

    Args:
        devices: Dictionary of devices

    Returns:
        List of inferred connections
    """
    inferred_connections = []

    try:
        # Find routers/gateways
        routers = []
        switches = []
        aps = []
        others = []

        for device_id, device in devices.items():
            if (
                "udm" in device.model.lower()
                or "usg" in device.model.lower()
                or "gateway" in device.model.lower()
                or "router" in device.model.lower()
            ):
                routers.append(device_id)
            elif (
                "usw" in device.model.lower()
                or "switch" in device.model.lower()
                or "us-" in device.model.lower()
                or "usl" in device.model.lower()
            ):
                switches.append(device_id)
            elif (
                "uap" in device.model.lower()
                or "ap" in device.model.lower()
                or "u6" in device.model.lower()
                or "u7" in device.model.lower()
                or "ac" in device.model.lower()
            ):
                aps.append(device_id)
            else:
                others.append(device_id)

        # Connect switches to routers
        if routers and switches:
            router_id = routers[0]
            for switch_id in switches:
                # Create an inferred connection
                inferred_connections.append(
                    {
                        "source_device_id": router_id,
                        "target_device_id": switch_id,
                        "source_port_idx": 1,  # Assume port 1 for the router
                        "source_port_name": "Port 1",
                        "target_port_idx": 1,  # Assume port 1 for the switch
                        "target_port_name": "Port 1",
                        "inferred": True,
                    }
                )

        # Connect APs to switches or routers
        if aps:
            if switches:
                # Connect APs to switches
                switch_id = switches[0]
                for ap_id in aps:
                    # Create an inferred connection
                    inferred_connections.append(
                        {
                            "source_device_id": switch_id,
                            "target_device_id": ap_id,
                            "source_port_idx": 1,  # Assume port 1 for the switch
                            "source_port_name": "Port 1",
                            "target_port_idx": 1,  # Assume port 1 for the AP
                            "target_port_name": "Port 1",
                            "inferred": True,
                        }
                    )
            elif routers:
                # Connect APs to routers
                router_id = routers[0]
                for ap_id in aps:
                    # Create an inferred connection
                    inferred_connections.append(
                        {
                            "source_device_id": router_id,
                            "target_device_id": ap_id,
                            "source_port_idx": 1,  # Assume port 1 for the router
                            "source_port_name": "Port 1",
                            "target_port_idx": 1,  # Assume port 1 for the AP
                            "target_port_name": "Port 1",
                            "inferred": True,
                        }
                    )

        # Connect other devices to switches or routers
        if others:
            if switches:
                # Connect other devices to switches
                switch_id = switches[0]
                for other_id in others:
                    # Create an inferred connection
                    inferred_connections.append(
                        {
                            "source_device_id": switch_id,
                            "target_device_id": other_id,
                            "source_port_idx": 1,  # Assume port 1 for the switch
                            "source_port_name": "Port 1",
                            "target_port_idx": 1,  # Assume port 1 for the other device
                            "target_port_name": "Port 1",
                            "inferred": True,
                        }
                    )
            elif routers:
                # Connect other devices to routers
                router_id = routers[0]
                for other_id in others:
                    # Create an inferred connection
                    inferred_connections.append(
                        {
                            "source_device_id": router_id,
                            "target_device_id": other_id,
                            "source_port_idx": 1,  # Assume port 1 for the router
                            "source_port_name": "Port 1",
                            "target_port_idx": 1,  # Assume port 1 for the other device
                            "target_port_name": "Port 1",
                            "inferred": True,
                        }
                    )
    except Exception as e:
        log.error(f"Error inferring connections from device types: {e}")

    return inferred_connections


def run_port_mapper(
    port_mapper,
    site_id,
    dry_run=False,
    output_path=None,
    diagram_path=None,
    diagram_format="png",
    debug=False,
    show_connected_devices=False,
    verify_updates=False,
):
    """
    Run the port mapper.

    Args:
        port_mapper: UnifiPortMapper instance
        site_id: Site ID
        dry_run: Whether to run in dry run mode (default: False)
        output_path: Path to the output report file (default: None)
        diagram_path: Path to the output diagram file (default: None)
        diagram_format: Format of the diagram (default: 'png')
        debug: Whether to enable debug output (default: False)
        show_connected_devices: Whether to show non-UniFi connected devices (default: False)
        verify_updates: Whether to verify port name updates (default: False, disabled due to UniFi controller behavior)

    Returns:
        Tuple of (devices, connections)
    """
    # Get the API client from port_mapper
    api_client = port_mapper.api_client

    # Ensure we're authenticated
    if not api_client.is_authenticated and not api_client.login():
        log.error("Failed to authenticate with the UniFi Controller")
        return {}, []

    log.info("Successfully authenticated with the UniFi Controller")

    # Get all devices
    log.info("Fetching devices from the UniFi Controller...")
    devices_response = api_client.get_devices(site_id)

    if not devices_response or "data" not in devices_response:
        log.error("Failed to get devices from the UniFi Controller")
        return {}, []

    all_devices = devices_response["data"]
    log.info(f"Found {len(all_devices)} devices")

    # Filter for routers, switches, and APs
    network_devices = [
        d for d in all_devices if d.get("type") in ["ugw", "usg", "udm", "usw", "uap"]
    ]
    routers_and_switches = [
        d for d in all_devices if d.get("type") in ["ugw", "usg", "udm", "usw"]
    ]
    adopted_access_points = [d for d in all_devices if d.get("type") == "uap"]
    log.info(f"Found {len(routers_and_switches)} routers and switches")
    log.info(f"Found {len(adopted_access_points)} adopted access points")

    # Create device objects
    devices = {}
    for device in network_devices:
        device_id = device.get("_id")
        if not device_id:
            log.warning(
                f"Device has None ID, skipping: {device.get('name')} ({device.get('model')})"
            )
            continue

        device_name = device.get("name", "Unknown")
        device_model = device.get("model", "Unknown")
        device_mac = device.get("mac", "")
        device_ip = device.get("ip", "")
        device_type = device.get("type", "")

        # Get ports for this device (only for routers and switches)
        ports = []
        lldp_info = {}
        client_port_mapping = {}
        if device_type in ["ugw", "usg", "udm", "usw"]:
            ports = api_client.get_device_ports(site_id, device_id)
            # Get LLDP/CDP information for this device
            lldp_info = api_client.get_lldp_info(site_id, device_id)
            # Get client-to-port mapping if we want to show connected devices
            if show_connected_devices:
                client_port_mapping = port_mapper.get_client_port_mapping(device_mac)

        # Create a DeviceInfo object
        device_info = DeviceInfo(
            id=device_id,
            name=device_name,
            model=device_model,
            mac=device_mac,
            ip=device_ip,
            ports=[],
            lldp_info=lldp_info,
        )

        # Collect port updates for batch processing
        # Format: {port_idx: {"name": str, "source": "lldp"|"client"}}
        port_updates = {}

        # Add ports to the device
        for port in ports:
            port_idx = port.get("port_idx")
            if port_idx is None:
                continue

            port_name = port.get("name", f"Port {port_idx}")
            port_up = port.get("up", False)
            port_enabled = port.get("enable", True)
            port_poe = port.get("poe_enable", False)
            port_media = port.get("media", "RJ45")
            port_speed = port.get("speed", 0)

            # Get LLDP/CDP information for this port
            port_lldp = lldp_info.get(str(port_idx), {})

            # Enhanced port naming logic:
            # Priority: 1) LLDP/CDP device name, 2) Client names, 3) Keep existing
            enhanced_port_name = port_name

            # Check current port state
            is_default_name = (
                port_name == f"Port {port_idx}" or port_name.startswith("Port ")
            )
            is_uplink = (
                port.get("is_uplink", False)
                or "uplink" in port_name.lower()
                or "trunk" in port_name.lower()
            )

            # Get LLDP/CDP connected device name - try multiple fields
            lldp_device_name = (
                port_lldp.get("remote_device_name")
                or port_lldp.get("system_name")
                or port_lldp.get("chassis_name")
            )

            # Debug logging for LLDP processing
            if port_lldp:
                log.debug(
                    f"Port {port_idx} LLDP data: remote_device_name='{port_lldp.get('remote_device_name', '')}', "
                    f"system_name='{port_lldp.get('system_name', '')}', chassis_name='{port_lldp.get('chassis_name', '')}', "
                    f"chassis_id='{port_lldp.get('chassis_id', '')}'"
                )

            # CRITICAL FIX: Don't trust API port names - they can be stale/cached
            # Always attempt LLDP-based updates when LLDP data is available
            # The API verification will determine if update is actually needed

            # Check if LLDP name is a useful name (not just a MAC address)
            lldp_name_is_valid = (
                lldp_device_name
                and not lldp_device_name.replace(":", "").replace("-", "").isalnum()  # Not a pure MAC
                or (lldp_device_name and len(lldp_device_name) > 17)  # Longer than MAC format
                or (lldp_device_name and not all(c in "0123456789abcdefABCDEF:-" for c in lldp_device_name))  # Contains non-MAC chars
            )

            # Process LLDP-based updates (don't check is_default_name - API can lie)
            if lldp_device_name and lldp_name_is_valid and not is_uplink:
                # Use LLDP/CDP device name (highest priority)
                enhanced_port_name = lldp_device_name
                port_updates[port_idx] = {"name": enhanced_port_name, "source": "lldp"}
                if not dry_run:
                    log.info(
                        f"Will update port {port_idx} name to '{enhanced_port_name}' (from LLDP) on device {device_name}"
                    )
                else:
                    log.info(
                        f"[DRY RUN] Would update port {port_idx} name to '{enhanced_port_name}' (from LLDP) on device {device_name}"
                    )
            elif lldp_device_name and not lldp_name_is_valid:
                log.debug(
                    f"Port {port_idx}: LLDP name '{lldp_device_name}' appears to be a MAC address, skipping"
                )
                # Still try client names as fallback
                if show_connected_devices and port_idx in client_port_mapping:
                    clients = client_port_mapping[port_idx]
                    client_names = port_mapper.format_client_names(clients)
                    if client_names:
                        enhanced_port_name = client_names
                        port_updates[port_idx] = {"name": enhanced_port_name, "source": "client"}
                        if not dry_run:
                            log.info(
                                f"Will update port {port_idx} name to '{enhanced_port_name}' (from clients, LLDP was MAC) on device {device_name}"
                            )
                        else:
                            log.info(
                                f"[DRY RUN] Would update port {port_idx} name to '{enhanced_port_name}' (from clients, LLDP was MAC) on device {device_name}"
                            )
                elif show_connected_devices and port_idx in client_port_mapping:
                    # Fall back to client names if no LLDP info
                    clients = client_port_mapping[port_idx]
                    client_names = port_mapper.format_client_names(clients)
                    if client_names:
                        enhanced_port_name = client_names
                        port_updates[port_idx] = {"name": enhanced_port_name, "source": "client"}
                        if not dry_run:
                            log.info(
                                f"Will update port {port_idx} name to '{enhanced_port_name}' (from clients) on device {device_name}"
                            )
                        else:
                            log.info(
                                f"[DRY RUN] Would update port {port_idx} name to '{enhanced_port_name}' (from clients) on device {device_name}"
                            )
                else:
                    log.debug(
                        f"Port {port_idx}: No LLDP name and no client mapping available"
                    )
            elif is_uplink:
                log.debug(
                    f"Skipping port {port_idx} - appears to be uplink/trunk port: {port_name}"
                )
            elif not lldp_device_name:
                log.debug(
                    f"Skipping port {port_idx} - no LLDP device detected"
                )
            else:
                log.debug(
                    f"Port {port_idx}: LLDP device '{lldp_device_name}' not considered valid name (appears to be MAC or too short)"
                )

            # Create a PortInfo object
            port_info = PortInfo(
                idx=port_idx,
                name=enhanced_port_name,
                up=port_up,
                enabled=port_enabled,
                poe=port_poe,
                media=port_media,
                speed=port_speed,
                lldp_info=port_lldp,
            )

            device_info.ports.append(port_info)

        # Apply batch port name updates if any
        if port_updates and not dry_run:
            # Separate LLDP-based updates (always apply) from client-based updates (need verification)
            lldp_updates = {
                idx: info["name"]
                for idx, info in port_updates.items()
                if info["source"] == "lldp"
            }
            client_updates = {
                idx: info["name"]
                for idx, info in port_updates.items()
                if info["source"] == "client"
            }

            # LLDP updates don't need verification - the device is connected if LLDP info exists
            verified_updates = dict(lldp_updates)
            if lldp_updates:
                log.info(
                    f"Will apply {len(lldp_updates)} LLDP-based port name updates (no verification needed)"
                )

            # Client-based updates need verification to ensure clients are still connected
            if client_updates:
                log.info(
                    f"Re-verifying connectivity for {len(client_updates)} client-based ports..."
                )
                current_client_mapping = port_mapper.get_client_port_mapping(device_mac)

                disconnected_ports = []
                for port_idx, port_name in client_updates.items():
                    if (
                        port_idx in current_client_mapping
                        and current_client_mapping[port_idx]
                    ):
                        verified_updates[port_idx] = port_name
                        log.info(
                            f"Port {port_idx} still has {len(current_client_mapping[port_idx])} connected client(s)"
                        )
                    else:
                        disconnected_ports.append((port_idx, port_name))
                        log.warning(
                            f"Skipping port {port_idx} - no longer has connected clients (would be named '{port_name}')"
                        )

                if disconnected_ports:
                    log.info(
                        f"Skipped {len(disconnected_ports)} client-based ports due to disconnection"
                    )

            if verified_updates:
                log.info(
                    f"Proceeding with {len(verified_updates)} port name updates"
                )
                # Use verification setting from command line (default is False due to UniFi controller behavior)
                success = port_mapper.batch_update_port_names(
                    device_id, verified_updates, verify_updates=verify_updates
                )
                if success:
                    if verify_updates:
                        log.info("Port updates applied and verified successfully")
                    else:
                        log.info(
                            "Port updates applied successfully (verification disabled due to UniFi controller behavior)"
                        )
            else:
                log.info("No ports to update")
                success = True  # Consider it successful if there's nothing to update
            if success:
                if verified_updates:
                    log.info(
                        f"Successfully batch updated {len(verified_updates)} port names for device {device_name}"
                    )
                else:
                    log.info(
                        f"No port updates needed for device {device_name}"
                    )
            else:
                log.error(
                    f"Failed to batch update or verify port names for device {device_name}"
                )
                # Log detailed information about the failure
                log.error(
                    f"Failed updates for device {device_name} ({device_model}) - MAC: {device_mac}"
                )
                for port_idx, port_name in verified_updates.items():
                    log.error(f"  Port {port_idx}: '{port_name}'")

                # Suggest using the fix script (extract just port_idx: name for JSON)
                simple_updates = {idx: info["name"] for idx, info in port_updates.items()}
                port_updates_json = json.dumps(simple_updates)
                log.error("To debug this issue, run:")
                log.error(f"  ./tools/debug_port_updates --env --device-id {device_id}")
                log.error("To force fix this issue, run:")
                log.error(
                    f"  ./tools/fix_port_persistence --env --device-id {device_id} --port-updates '{port_updates_json}'"
                )

        devices[device_id] = device_info

    # Get all clients
    log.info("Fetching clients from the UniFi Controller...")
    clients_response = api_client.get_clients(site_id)

    if not clients_response or "data" not in clients_response:
        log.error("Failed to get clients from the UniFi Controller")
        clients = []
    else:
        clients = clients_response["data"]
        log.info(f"Found {len(clients)} clients")

    # Process each client to find unadopted APs and wired endpoint devices
    # Note: Adopted APs are already counted above in 'adopted_access_points'
    unadopted_aps = []
    wired_devices = []

    for client in clients:
        # Check if this is a wired client
        is_wired = client.get("is_wired", False)

        # Get device information
        client_name = client.get("name", client.get("hostname", "Unknown Client"))
        client_mac = client.get("mac", "Unknown MAC")
        client_ip = client.get("ip", "Unknown IP")
        client_device_type = client.get("dev_cat_name", "Unknown")

        # Handle potential type issues with dev_vendor and dev_id
        dev_vendor = client.get("dev_vendor", "Unknown")
        dev_id = client.get("dev_id", "")

        # Convert to string if needed
        if not isinstance(dev_vendor, str):
            dev_vendor = str(dev_vendor)
        if not isinstance(dev_id, str):
            dev_id = str(dev_id)

        client_model = dev_vendor + " " + dev_id

        # Check if this is an unadopted access point appearing as a client
        # (based on device category or name patterns)
        if (
            client_device_type == "AP"
            or "AP" in client_name
            or "UAP" in client_name
            or "U6" in client_name
            or "U7" in client_name
            or "AC" in client_name
            or "IW" in client_name
        ):
            unadopted_aps.append(client)
        elif is_wired:
            wired_devices.append(client)

    if unadopted_aps:
        log.info(
            f"Found {len(unadopted_aps)} unadopted/rogue APs in client list"
        )
    log.info(f"Found {len(wired_devices)} wired endpoint devices")

    # Create a network topology
    topology = NetworkTopology(devices)

    # Add unadopted/rogue APs (from client list) to the topology
    for ap in unadopted_aps:
        ap_name = ap.get("name", ap.get("hostname", "Unknown AP"))
        ap_mac = ap.get("mac", "Unknown MAC")
        ap_ip = ap.get("ip", "Unknown IP")
        ap_model = ap.get("dev_cat_name", "Unadopted AP")

        # Check if this AP is connected to a switch
        sw_mac = ap.get("sw_mac")
        sw_port = ap.get("sw_port")

        if sw_mac and sw_port:
            # Find the switch in our devices
            for device_id, device in devices.items():
                if (
                    device.mac.lower() == sw_mac.lower()
                    or device.mac.lower().replace(":", "") == sw_mac.lower()
                ):
                    # Add the AP to the topology
                    ap_id = ap_mac.replace(":", "")
                    topology.add_device(ap_id, ap_name, ap_model, ap_mac, ap_ip)

                    # Add the connection
                    topology.add_connection(device_id, ap_id, sw_port, 1)
                    break

    # Add wired devices to the topology if they're connected to a switch
    for device in wired_devices:
        device_name = device.get("name", device.get("hostname", "Unknown Device"))
        device_mac = device.get("mac", "Unknown MAC")
        device_ip = device.get("ip", "Unknown IP")
        device_model = device.get("dev_cat_name", "Wired Device")

        # Check if this device is connected to a switch
        sw_mac = device.get("sw_mac")
        sw_port = device.get("sw_port")

        if sw_mac and sw_port:
            # Find the switch in our devices
            for device_id, d in devices.items():
                if (
                    d.mac.lower() == sw_mac.lower()
                    or d.mac.lower().replace(":", "") == sw_mac.lower()
                ):
                    # Add the device to the topology
                    wired_id = device_mac.replace(":", "")
                    topology.add_device(
                        wired_id, device_name, device_model, device_mac, device_ip
                    )

                    # Add the connection
                    topology.add_connection(device_id, wired_id, sw_port, 1)
                    break

    # Infer connections between devices
    inferred_connections = infer_device_connections(api_client, site_id, devices)
    for connection in inferred_connections:
        source_id = connection.get("source_device_id")
        target_id = connection.get("target_device_id")
        source_port = connection.get("source_port_idx")
        target_port = connection.get("target_port_idx")

        # Add the connection if both devices exist and the connection doesn't already exist
        if source_id in devices and target_id in devices:
            # Check if this connection already exists
            exists = False
            for conn in topology.connections:
                if (
                    conn["source_device_id"] == source_id
                    and conn["target_device_id"] == target_id
                ):
                    exists = True
                    break

            if not exists:
                topology.add_connection(source_id, target_id, source_port, target_port)

    # Generate the network diagram
    if diagram_path:
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(diagram_path), exist_ok=True)

        # Generate the diagram based on the format
        if diagram_format.lower() == "png":
            topology.generate_png_diagram(diagram_path)
        elif diagram_format.lower() == "svg":
            topology.generate_svg_diagram(diagram_path)
        elif diagram_format.lower() == "dot":
            topology.generate_dot_diagram(diagram_path)
        elif diagram_format.lower() == "mermaid":
            topology.generate_mermaid_diagram(diagram_path)
        elif diagram_format.lower() == "html":
            topology.generate_html_diagram(diagram_path, show_connected_devices)
        else:
            log.warning(f"Unsupported diagram format: {diagram_format}")

    # Generate the port mapping report
    if output_path:
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Generate the report
        generate_port_mapping_report(devices, output_path)

    # Return the devices and connections
    return devices, topology.connections
