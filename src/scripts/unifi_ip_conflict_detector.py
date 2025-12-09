#!/usr/bin/env python3
"""
UniFi IP Conflict Detector

A CLI tool that connects to the UniFi Controller and identifies duplicate IP addresses
in the network. The tool displays detailed information about conflicting devices including
their MAC addresses, hostnames, and connection points.
"""

import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import urllib3

# Add parent directory to path to import from unifi_mapper
sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.tree import Tree

from unifi_mapper.api_client import UnifiApiClient

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
log = logging.getLogger("unifi_ip_conflict")

# Create console for rich output
console = Console()


def load_env_file() -> bool:
    """
    Load environment variables from .env file.

    Returns:
        bool: True if .env file was loaded, False otherwise
    """
    # Try to load from .env file in the current directory
    if os.path.exists(".env"):
        load_dotenv(".env")
        return True

    # Try to load from .env file in the parent directory
    parent_env = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if os.path.exists(parent_env):
        load_dotenv(parent_env)
        return True

    # Try to load from .env file in the project root directory
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    project_env = os.path.join(project_root, ".env")
    if os.path.exists(project_env):
        load_dotenv(project_env)
        return True

    return False


def get_api_client(args) -> UnifiApiClient:
    """
    Create and initialize the UniFi API client.

    Args:
        args: Command line arguments

    Returns:
        UnifiApiClient: Initialized API client
    """
    # Get credentials from environment variables or command line arguments
    base_url = args.url or os.environ.get("UNIFI_URL")
    site = args.site or os.environ.get("UNIFI_SITE", "default")
    username = args.username or os.environ.get("UNIFI_USERNAME")
    password = args.password or os.environ.get("UNIFI_PASSWORD")
    api_token = args.token or os.environ.get("UNIFI_CONSOLE_API_TOKEN")
    verify_ssl = (
        args.verify_ssl
        if args.verify_ssl is not None
        else os.environ.get("UNIFI_VERIFY_SSL", "false").lower() == "true"
    )
    timeout = args.timeout or int(os.environ.get("UNIFI_TIMEOUT", "10"))

    # Debug log the credentials (without sensitive info)
    log.debug(f"URL: {base_url}")
    log.debug(f"Site: {site}")
    log.debug(f"Username: {'[SET]' if username else '[NOT SET]'}")
    log.debug(f"Password: {'[SET]' if password else '[NOT SET]'}")
    log.debug(f"API Token: {'[SET]' if api_token else '[NOT SET]'}")
    log.debug(f"Verify SSL: {verify_ssl}")
    log.debug(f"Timeout: {timeout}")

    # Check if we have enough information to connect
    if not base_url:
        console.print(
            "[bold red]Error:[/bold red] No UniFi Controller URL provided. Use --url or set UNIFI_URL environment variable."
        )
        sys.exit(1)

    if not api_token and not (username and password):
        console.print(
            "[bold red]Error:[/bold red] No authentication credentials provided. Use --token or --username/--password or set environment variables."
        )
        sys.exit(1)

    # Create API client
    api_client = UnifiApiClient(
        base_url=base_url,
        site=site,
        verify_ssl=verify_ssl,
        username=username,
        password=password,
        api_token=api_token,
        timeout=timeout,
    )

    # Try to login
    if not api_client.login():
        console.print(
            "[bold red]Error:[/bold red] Failed to authenticate with the UniFi Controller."
        )
        console.print(
            "[yellow]Debug info:[/yellow] Using URL: {}, Site: {}, Auth method: {}".format(
                base_url, site, "API token" if api_token else "Username/password"
            )
        )
        console.print(
            "[yellow]Tip:[/yellow] Check your credentials and make sure the UniFi Controller is accessible."
        )
        sys.exit(1)

    return api_client


def format_mac_address(mac: str) -> str:
    """
    Format MAC address with colons.

    Args:
        mac: MAC address

    Returns:
        str: Formatted MAC address
    """
    # Remove any non-hex characters
    mac = re.sub(r"[^0-9a-fA-F]", "", mac)

    # Format with colons
    if len(mac) == 12:
        return ":".join(mac[i : i + 2] for i in range(0, 12, 2))

    return mac


def get_device_name(api_client: UnifiApiClient, site: str, device_mac: str) -> str:
    """
    Get the name of a device by MAC address.

    Args:
        api_client: UniFi API client
        site: Site ID
        device_mac: Device MAC address

    Returns:
        str: Device name or MAC address if not found
    """
    # Get all devices
    devices_data = api_client.get_devices(site)

    if not devices_data or "data" not in devices_data:
        return device_mac

    devices = devices_data["data"]

    # Find device by MAC address
    for device in devices:
        if device.get("mac", "").lower() == device_mac.lower():
            return device.get("name", device_mac)

    return device_mac


def get_client_connection_info(
    client: Dict[str, Any], api_client: UnifiApiClient, site: str
) -> Tuple[str, str]:
    """
    Get connection information for a client.

    Args:
        client: Client data
        api_client: UniFi API client
        site: Site ID

    Returns:
        Tuple[str, str]: Connection device and port information
    """
    device_info = "Unknown"
    port_info = "N/A"

    if client.get("sw_mac"):
        # Client is connected to a switch
        device_info = get_device_name(api_client, site, client["sw_mac"])
        port_info = f"Port {client.get('sw_port', 'Unknown')}"
        return device_info, port_info
    elif client.get("ap_mac"):
        # Client is connected to an access point
        device_info = get_device_name(api_client, site, client["ap_mac"])
        port_info = "Wireless"
        return device_info, port_info
    else:
        return device_info, port_info


def get_client_status(client: Dict[str, Any]) -> Tuple[str, str]:
    """
    Get the status of a client.

    Args:
        client: Client data

    Returns:
        Tuple[str, str]: Status text and style
    """
    if client.get("is_wired", False):
        return "Wired", "green"
    elif client.get("is_guest", False) or client.get("_is_guest_by_uap", False):
        return "Guest", "yellow"
    elif client.get("last_seen", 0) > 0:
        return "Wireless", "blue"
    else:
        return "Offline", "red"


def find_ip_conflicts(
    api_client: UnifiApiClient, site: str, include_historical: bool = False
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Find IP address conflicts in the network.

    Args:
        api_client: UniFi API client
        site: Site ID
        include_historical: Whether to include historical clients

    Returns:
        Dict[str, List[Dict[str, Any]]]: Dictionary of IP addresses to lists of conflicting clients
    """
    # Get all clients
    with Progress(
        SpinnerColumn(),
        TextColumn(
            "[bold blue]Fetching client data from UniFi Controller...[/bold blue]"
        ),
        transient=True,
    ) as progress:
        progress.add_task("fetch", total=None)
        clients_data = api_client.get_clients(site)

    if not clients_data or "data" not in clients_data:
        console.print("[bold yellow]Warning:[/bold yellow] No clients found.")
        return {}

    clients = clients_data["data"]

    # Group clients by IP address
    ip_to_clients = defaultdict(list)

    for client in clients:
        ip = client.get("ip")
        if ip:
            # Skip clients with no IP address
            # Skip historical clients if not requested
            if not include_historical and client.get("last_seen", 0) == 0:
                continue

            ip_to_clients[ip].append(client)

    # Filter to only IP addresses with multiple clients
    conflicts = {
        ip: clients for ip, clients in ip_to_clients.items() if len(clients) > 1
    }

    return conflicts


def display_ip_conflicts(
    conflicts: Dict[str, List[Dict[str, Any]]], api_client: UnifiApiClient, site: str
) -> None:
    """
    Display IP address conflicts in a formatted table.

    Args:
        conflicts: Dictionary of IP addresses to lists of conflicting clients
        api_client: UniFi API client
        site: Site ID
    """
    if not conflicts:
        console.print(
            Panel(
                "[bold green]No IP address conflicts found.[/bold green]",
                title="UniFi IP Conflict Detector",
                border_style="green",
            )
        )
        return

    # Create a tree for displaying conflicts
    tree = Tree(
        f"[bold red]IP Conflicts Found: {len(conflicts)} conflicting IP addresses[/bold red]"
    )

    # Sort conflicts by IP address
    sorted_ips = sorted(
        conflicts.keys(), key=lambda ip: [int(octet) for octet in ip.split(".")]
    )

    # Add each conflict to the tree
    for ip in sorted_ips:
        clients = conflicts[ip]
        ip_branch = tree.add(
            f"[bold yellow]IP: {ip}[/bold yellow] ({len(clients)} devices)"
        )

        # Add each client to the IP branch
        for client in clients:
            # Get client name (use hostname if name is not available)
            client_name = client.get("name", client.get("hostname", "Unknown"))

            # Get MAC address
            mac_address = format_mac_address(client.get("mac", ""))

            # Get connection info
            device_info, port_info = get_client_connection_info(
                client, api_client, site
            )

            # Get status
            status_text, status_style = get_client_status(client)

            # Add client to the tree with more prominent MAC address
            client_text = f"[bold magenta]MAC: {mac_address}[/bold magenta] - [cyan]{client_name}[/cyan]"
            client_branch = ip_branch.add(client_text)

            # Add connection details as sub-items
            client_branch.add(f"[green]Connected to: {device_info}[/green]")
            client_branch.add(f"[blue]Interface: {port_info}[/blue]")
            client_branch.add(f"[{status_style}]Status: {status_text}[/{status_style}]")

    # Display the tree
    console.print(tree)

    # Also display a summary table
    table = Table(title="IP Conflict Summary")
    table.add_column("IP Address", style="yellow")
    table.add_column("# of Devices", style="red")
    table.add_column("MAC Addresses", style="magenta")
    table.add_column("Device Names", style="cyan")

    for ip in sorted_ips:
        clients = conflicts[ip]
        mac_addresses = ", ".join(
            [format_mac_address(client.get("mac", "")) for client in clients]
        )
        device_names = ", ".join(
            [
                client.get("name", client.get("hostname", "Unknown"))
                for client in clients
            ]
        )
        table.add_row(ip, str(len(clients)), mac_addresses, device_names)
        table.add_row(ip, str(len(clients)), mac_addresses, device_names)

    console.print(table)

    # Display a detailed table with connection information
    detailed_table = Table(title="IP Conflict Details")
    detailed_table.add_column("IP Address", style="yellow")
    detailed_table.add_column("Device Name", style="cyan")
    detailed_table.add_column("MAC Address", style="magenta", no_wrap=True)
    detailed_table.add_column("Connected To", style="green")
    detailed_table.add_column("Interface", style="blue")
    detailed_table.add_column("Status", style="white")

    for ip in sorted_ips:
        clients = conflicts[ip]
        for client in clients:
            # Get client name (use hostname if name is not available)
            client_name = client.get("name", client.get("hostname", "Unknown"))

            # Get MAC address
            mac_address = format_mac_address(client.get("mac", ""))

            # Get connection info
            device_info, port_info = get_client_connection_info(
                client, api_client, site
            )

            # Get status
            status_text, status_style = get_client_status(client)
            status_display = f"[{status_style}]{status_text}[/{status_style}]"

            detailed_table.add_row(
                ip, client_name, mac_address, device_info, port_info, status_display
            )

    console.print(detailed_table)


def main():
    """Main function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="UniFi IP Conflict Detector")

    # UniFi Controller connection arguments
    parser.add_argument(
        "--url", help="UniFi Controller URL (e.g., https://unifi.local:8443)"
    )
    parser.add_argument("--site", help="UniFi site name (default: default)")
    parser.add_argument("--username", help="UniFi Controller username")
    parser.add_argument("--password", help="UniFi Controller password")
    parser.add_argument("--token", help="UniFi Controller API token")
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Verify SSL certificates (default: disabled)",
    )
    parser.add_argument("--timeout", type=int, help="Connection timeout in seconds")
    parser.add_argument(
        "--env", action="store_true", help="Load credentials from .env file"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--include-historical",
        action="store_true",
        help="Include historical clients (may include stale data)",
    )

    args = parser.parse_args()

    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        log.debug("Debug logging enabled")

    # Suppress SSL warnings by default
    if not args.verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Load environment variables if requested
    if args.env:
        if load_env_file():
            log.debug("Loaded environment variables from .env file")
        else:
            console.print("[bold yellow]Warning:[/bold yellow] No .env file found.")

    # Create API client
    api_client = get_api_client(args)

    # Get site
    site = args.site or os.environ.get("UNIFI_SITE", "default")

    # Find IP conflicts
    console.print("[bold]Scanning for IP address conflicts...[/bold]")
    conflicts = find_ip_conflicts(api_client, site, args.include_historical)

    # Display results
    display_ip_conflicts(conflicts, api_client, site)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Operation cancelled by user.[/bold yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        if logging.getLogger().level == logging.DEBUG:
            console.print_exception()
        sys.exit(1)
