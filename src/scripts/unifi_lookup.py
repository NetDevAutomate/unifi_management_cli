#!/usr/bin/env python3
"""
UniFi Client Lookup Tool

A CLI tool that looks up UniFi clients by MAC address (or partial MAC) and displays the results
in a formatted table with client name, IP address, MAC address, connected device, and status.
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add parent directory to path to import from unifi_mapper
sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from unifi_mapper.api_client import UnifiApiClient

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
log = logging.getLogger("unifi_lookup")

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

    # Log connection details in debug mode
    log.debug(f"Connecting to UniFi Controller at {base_url}")
    log.debug(f"Using site: {site}")
    log.debug(f"SSL verification: {'enabled' if verify_ssl else 'disabled'}")
    log.debug(
        f"Authentication method: {'API token' if api_token else 'Username/password'}"
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


def search_clients(
    api_client: UnifiApiClient, search_term: str, site: str
) -> List[Dict[str, Any]]:
    """
    Search for clients matching the search term.

    Args:
        api_client: UniFi API client
        search_term: Search term (case insensitive)
        site: Site ID

    Returns:
        List[Dict[str, Any]]: List of matching clients
    """
    # Get all clients
    clients_data = api_client.get_clients(site)

    if not clients_data or "data" not in clients_data:
        console.print("[bold yellow]Warning:[/bold yellow] No clients found.")
        return []

    clients = clients_data["data"]

    # Prepare search term (case insensitive)
    search_term = search_term.lower()

    # Filter clients based on search term
    matching_clients = []

    for client in clients:
        # Check if search term is in client name, hostname, MAC address, or IP address
        client_name = client.get("name", "").lower()
        hostname = client.get("hostname", "").lower()
        mac = client.get("mac", "").lower()
        ip = client.get("ip", "").lower()

        if (
            search_term in client_name
            or search_term in hostname
            or search_term in mac
            or search_term in ip
        ):
            matching_clients.append(client)

    return matching_clients


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


def display_clients(
    clients: List[Dict[str, Any]], api_client: UnifiApiClient, site: str
) -> None:
    """
    Display clients in a formatted table.

    Args:
        clients: List of clients
        api_client: UniFi API client
        site: Site ID
    """
    if not clients:
        console.print(
            Panel(
                "[bold yellow]No matching clients found.[/bold yellow]",
                title="UniFi Client Lookup",
                border_style="yellow",
            )
        )
        return

    # Create table
    table = Table(title=f"UniFi Clients ({len(clients)} found)")

    # Add columns
    table.add_column("Client Name", style="cyan")
    table.add_column("IP Address", style="blue")
    table.add_column("MAC Address", style="magenta")
    table.add_column("Connected To", style="green")
    table.add_column("Status", style="yellow")

    # Add rows
    for client in clients:
        # Get client name (use hostname if name is not available)
        client_name = client.get("name", client.get("hostname", "Unknown"))

        # Get IP address
        ip_address = client.get("ip", "N/A")

        # Get MAC address
        mac_address = format_mac_address(client.get("mac", ""))

        # Get connected device
        connected_to = "N/A"
        if client.get("sw_mac"):
            # Client is connected to a switch
            connected_to = f"{get_device_name(api_client, site, client['sw_mac'])} (Port {client.get('sw_port', 'Unknown')})"
        elif client.get("ap_mac"):
            # Client is connected to an access point
            connected_to = get_device_name(api_client, site, client["ap_mac"])

        # Get status
        status = (
            "[green]Connected[/green]"
            if client.get("is_wired", False)
            or client.get("is_guest", False)
            or client.get("_is_guest_by_uap", False)
            else "[red]Disconnected[/red]"
        )

        # Add row
        table.add_row(client_name, ip_address, mac_address, connected_to, status)

    # Display table
    console.print(table)


def main():
    """Main function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="UniFi Client Lookup Tool")

    # Search term argument
    parser.add_argument(
        "search_term",
        help="Search term (client name, hostname, MAC address, or IP address)",
    )

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

    # Suppress SSL warnings option
    parser.add_argument(
        "--suppress-ssl-warnings",
        action="store_true",
        help="Suppress SSL certificate warnings",
    )

    args = parser.parse_args()

    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        log.debug("Debug logging enabled")

    # Suppress SSL warnings by default
    if not args.verify_ssl:
        import urllib3

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

    # Search for clients
    console.print(
        f"[bold]Searching for clients matching '[cyan]{args.search_term}[/cyan]'...[/bold]"
    )
    clients = search_clients(api_client, args.search_term, site)

    # Display results
    display_clients(clients, api_client, site)


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
