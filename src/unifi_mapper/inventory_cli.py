#!/usr/bin/env python3
"""
UniFi Network Inventory and Firmware Management CLI.

Provides inventory listing, firmware version reporting, and firmware update capabilities.
Integrated into the main unifi-mapper CLI as subcommands.
"""

import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box

from .api_client import UnifiApiClient
from .cli import get_default_config_path, load_env_from_config

log = logging.getLogger(__name__)
console = Console()

# Create Typer app for inventory commands
inventory_app = typer.Typer(
    name="inventory",
    help="📦 Device inventory and firmware management",
)


def parse_filter(filter_str: str) -> set[str]:
    """Parse comma-separated filter string into set of device types."""
    if not filter_str or filter_str.lower() == "all":
        return {"all"}

    types = set()
    for item in filter_str.lower().split(","):
        item = item.strip()
        # Normalize aliases
        if item in ("firewall", "router", "gateway", "udm"):
            types.add("firewall")
        elif item in ("switch", "usw", "switches"):
            types.add("switch")
        elif item in ("ap", "accesspoint", "access_point", "aps", "uap"):
            types.add("ap")
        elif item == "other":
            types.add("other")
        elif item == "all":
            types.add("all")
        else:
            console.print(f"[yellow]Warning: Unknown device type '{item}', ignoring[/yellow]")

    return types if types else {"all"}


def get_device_type(model: str, device_type_field: str = "") -> str:
    """Determine device type from model string."""
    model_lower = model.lower()
    type_lower = device_type_field.lower() if device_type_field else ""

    # Check type field first if available
    if type_lower in ("ugw", "udm", "usg"):
        return "firewall"
    if type_lower == "usw":
        return "switch"
    if type_lower == "uap":
        return "ap"

    # Routers/Gateways/Firewalls
    if any(x in model_lower for x in ["udm", "usg", "ugw", "gateway", "router", "dream"]):
        return "firewall"

    # Switches - comprehensive patterns
    if any(x in model_lower for x in ["usw", "switch", "us-", "usl", "usm", "us8", "us16", "us24", "us48"]):
        return "switch"
    if model_lower.startswith("us") and len(model_lower) > 2 and model_lower[2].isdigit():
        return "switch"

    # Access Points
    if any(x in model_lower for x in ["uap", "u6", "u7", "ac", "nano", "litebeam", "flexhd", "ualr", "uacc"]):
        return "ap"

    return "other"


def get_api_client(config_path: Optional[str] = None) -> tuple[UnifiApiClient, str]:
    """Create and authenticate API client."""
    if config_path is None:
        config_path = get_default_config_path()

    load_env_from_config(config_path)

    base_url = os.environ.get("UNIFI_URL")
    site = os.environ.get("UNIFI_SITE", "default")
    api_token = os.environ.get("UNIFI_CONSOLE_API_TOKEN")
    username = os.environ.get("UNIFI_USERNAME")
    password = os.environ.get("UNIFI_PASSWORD")
    verify_ssl = os.environ.get("UNIFI_VERIFY_SSL", "false").lower() == "true"

    if not base_url:
        console.print("[red]Error: UNIFI_URL not configured[/red]")
        raise typer.Exit(1)

    client = UnifiApiClient(
        base_url=base_url,
        site=site,
        api_token=api_token,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )

    if not client.login():
        console.print("[red]Error: Failed to authenticate with UniFi controller[/red]")
        raise typer.Exit(1)

    return client, site


def fetch_and_categorize_devices(client: UnifiApiClient, site: str) -> dict[str, list[dict]]:
    """Fetch all devices and categorize by type."""
    devices_response = client.get_devices(site)

    if not devices_response or "data" not in devices_response:
        console.print("[red]Error: Failed to retrieve devices from controller[/red]")
        raise typer.Exit(1)

    categorized: dict[str, list[dict]] = {
        "firewall": [],
        "switch": [],
        "ap": [],
        "other": [],
    }

    for device in devices_response["data"]:
        model = device.get("model", "Unknown")
        type_field = device.get("type", "")
        device_type = get_device_type(model, type_field)

        device_info = {
            "name": device.get("name", "Unnamed"),
            "model": model,
            "model_name": device.get("model_name", model),
            "version": device.get("version", "Unknown"),
            "ip": device.get("ip", "N/A"),
            "mac": device.get("mac", "N/A"),
            "id": device.get("_id", ""),
            "adopted": device.get("adopted", False),
            "state": device.get("state", 0),
            "uptime": device.get("uptime", 0),
            "upgradable": device.get("upgradable", False),
            "upgrade_to_firmware": device.get("upgrade_to_firmware", ""),
            "type": device_type,
            "raw_type": type_field,
        }

        categorized[device_type].append(device_info)

    # Sort each category by name
    for category in categorized:
        categorized[category].sort(key=lambda x: x["name"].lower())

    return categorized


def display_device_table(devices: list[dict], title: str, show_upgrade: bool = False):
    """Display devices in a rich table."""
    if not devices:
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Name", style="white", max_width=30)
    table.add_column("Model", style="green")
    table.add_column("Firmware", style="yellow")
    table.add_column("IP Address", style="blue")

    if show_upgrade:
        table.add_column("Upgrade Available", style="magenta")

    for device in devices:
        name = device["name"][:29] if len(device["name"]) > 29 else device["name"]
        model = device["model"]
        version = device["version"]
        ip = device["ip"]

        if show_upgrade:
            if device["upgradable"] and device["upgrade_to_firmware"]:
                upgrade_info = f"✓ {device['upgrade_to_firmware']}"
                upgrade_style = "green"
            elif device["upgradable"]:
                upgrade_info = "✓ Available"
                upgrade_style = "yellow"
            else:
                upgrade_info = "—"
                upgrade_style = "dim"

            table.add_row(name, model, version, ip, f"[{upgrade_style}]{upgrade_info}[/{upgrade_style}]")
        else:
            table.add_row(name, model, version, ip)

    console.print(table)
    console.print()


def display_firmware_summary(devices: list[dict], device_type: str):
    """Display firmware version summary for a device category."""
    if not devices:
        return

    firmware_counts: dict[str, list[str]] = defaultdict(list)
    for device in devices:
        firmware_counts[device["version"]].append(device["name"])

    console.print(f"[bold]{device_type.upper()} Firmware Summary:[/bold]")
    for version, names in sorted(firmware_counts.items()):
        console.print(f"  • {version}: {len(names)} device(s)")

    console.print()


def display_model_summary(devices: list[dict], device_type: str):
    """Display model summary for a device category."""
    if not devices:
        return

    model_counts: dict[str, list[str]] = defaultdict(list)
    for device in devices:
        model_counts[device["model"]].append(device["name"])

    console.print(f"[bold]{device_type.upper()} Model Summary:[/bold]")
    for model, names in sorted(model_counts.items()):
        console.print(f"  • {model}: {len(names)} device(s)")

    console.print()


def _save_inventory_report(categorized: dict, filter_types: set, output_path: str, show_all: bool):
    """Save inventory report to markdown file."""
    lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_url = os.environ.get("UNIFI_URL", "Unknown")
    site = os.environ.get("UNIFI_SITE", "default")

    lines.append("# UniFi Network Inventory Report")
    lines.append(f"\n**Generated:** {timestamp}")
    lines.append(f"**Controller:** {base_url}")
    lines.append(f"**Site:** {site}")
    lines.append("")

    # Summary
    total = sum(len(devices) for devices in categorized.values())
    lines.append("## Summary")
    lines.append("")
    lines.append("| Device Type | Count |")
    lines.append("|-------------|-------|")
    lines.append(f"| Firewalls/Routers | {len(categorized['firewall'])} |")
    lines.append(f"| Switches | {len(categorized['switch'])} |")
    lines.append(f"| Access Points | {len(categorized['ap'])} |")
    lines.append(f"| Other | {len(categorized['other'])} |")
    lines.append(f"| **Total** | **{total}** |")
    lines.append("")

    type_titles = {
        "firewall": "Firewalls / Routers",
        "switch": "Switches",
        "ap": "Access Points",
        "other": "Other Devices",
    }

    for device_type, title in type_titles.items():
        if show_all or device_type in filter_types:
            devices = categorized[device_type]
            if devices:
                lines.append(f"## {title}")
                lines.append("")
                lines.append("| Name | Model | Firmware | IP |")
                lines.append("|------|-------|----------|-----|")
                for d in devices:
                    lines.append(f"| {d['name']} | {d['model']} | {d['version']} | {d['ip']} |")
                lines.append("")

    Path(output_path).write_text("\n".join(lines))


def _trigger_firmware_upgrade(client: UnifiApiClient, site: str, device_mac: str) -> bool:
    """Trigger firmware upgrade for a device via the UniFi API."""
    import requests

    # Determine the correct endpoint based on controller type
    if client.is_unifi_os:
        endpoints = [
            f"{client.base_url}/proxy/network/api/s/{site}/cmd/devmgr",
        ]
    else:
        endpoints = [
            f"{client.base_url}/api/s/{site}/cmd/devmgr",
        ]

    upgrade_payload = {
        "cmd": "upgrade",
        "mac": device_mac.lower(),
    }

    for endpoint in endpoints:
        try:
            response = client.session.post(
                endpoint,
                json=upgrade_payload,
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                meta = result.get("meta", {})
                if meta.get("rc") == "ok":
                    return True

        except requests.exceptions.RequestException:
            continue

    return False


@inventory_app.command("list")
def inventory_list(
    filter: str = typer.Option(
        "all",
        "--filter", "-f",
        help="Device types: all, switch, ap, firewall, other (comma-separated)",
    ),
    config: Optional[str] = typer.Option(
        None,
        "--config", "-c",
        help="Path to .env config file",
    ),
    show_summary: bool = typer.Option(
        True,
        "--summary/--no-summary",
        help="Show firmware and model summaries",
    ),
    show_upgrade: bool = typer.Option(
        False,
        "--show-upgrade", "-u",
        help="Show available firmware upgrades",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output", "-o",
        help="Save report to file (markdown format)",
    ),
):
    """📦 Display inventory of UniFi network devices.

    Filter options:
    - all: Show all devices
    - switch: Show switches only
    - ap: Show access points only
    - firewall: Show routers/gateways/firewalls
    - other: Show uncategorized devices

    Examples:
        unifi-mapper inventory list --filter switch
        unifi-mapper inventory list --filter switch,ap
        unifi-mapper inventory list --filter all --show-upgrade
    """
    filter_types = parse_filter(filter)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Connecting to UniFi controller...", total=None)
        client, site = get_api_client(config)

        progress.add_task("Fetching devices...", total=None)
        categorized = fetch_and_categorize_devices(client, site)

    # Header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_url = os.environ.get("UNIFI_URL", "Unknown")

    console.print(Panel.fit(
        f"[bold]UniFi Network Inventory[/bold]\n"
        f"Controller: {base_url}\n"
        f"Site: {site}\n"
        f"Generated: {timestamp}",
        border_style="blue",
    ))
    console.print()

    # Summary counts
    total = sum(len(devices) for devices in categorized.values())
    console.print("[bold]Device Summary:[/bold]")
    console.print(f"  Firewalls/Routers: {len(categorized['firewall'])}")
    console.print(f"  Switches:          {len(categorized['switch'])}")
    console.print(f"  Access Points:     {len(categorized['ap'])}")
    console.print(f"  Other:             {len(categorized['other'])}")
    console.print(f"  [bold]Total:             {total}[/bold]")
    console.print()

    # Display requested device types
    show_all = "all" in filter_types

    type_titles = {
        "firewall": "🔥 Firewalls / Routers / Gateways",
        "switch": "🔌 Switches",
        "ap": "📡 Access Points",
        "other": "📦 Other Devices",
    }

    for device_type, title in type_titles.items():
        if show_all or device_type in filter_types:
            devices = categorized[device_type]
            if devices:
                display_device_table(devices, title, show_upgrade=show_upgrade)

                if show_summary:
                    display_firmware_summary(devices, device_type)
                    display_model_summary(devices, device_type)

    # Check for upgrades available
    if show_upgrade:
        upgradable_devices = []
        for device_type, devices in categorized.items():
            if show_all or device_type in filter_types:
                for device in devices:
                    if device["upgradable"]:
                        upgradable_devices.append(device)

        if upgradable_devices:
            console.print(f"[bold yellow]⚠️  {len(upgradable_devices)} device(s) have firmware updates available[/bold yellow]")
            console.print("Run 'unifi-mapper inventory update-firmware' to upgrade devices")
        else:
            console.print("[bold green]✅ All devices are up to date[/bold green]")

    # Save to file if requested
    if output:
        _save_inventory_report(categorized, filter_types, output, show_all)
        console.print(f"\n[green]Report saved to: {output}[/green]")

    client.logout()


@inventory_app.command("check-updates")
def check_updates(
    filter: str = typer.Option(
        "all",
        "--filter", "-f",
        help="Device types: all, switch, ap, firewall (comma-separated)",
    ),
    config: Optional[str] = typer.Option(
        None,
        "--config", "-c",
        help="Path to .env config file",
    ),
):
    """🔍 Check for available firmware updates.

    Quick way to see which devices have updates available.

    Examples:
        unifi-mapper inventory check-updates
        unifi-mapper inventory check-updates --filter switch
    """
    filter_types = parse_filter(filter)
    show_all = "all" in filter_types

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Connecting to UniFi controller...", total=None)
        client, site = get_api_client(config)

        progress.add_task("Checking for updates...", total=None)
        categorized = fetch_and_categorize_devices(client, site)

    # Find devices with available upgrades
    updates_by_type: dict[str, list[dict]] = defaultdict(list)
    total_updates = 0

    for device_type, devices in categorized.items():
        if show_all or device_type in filter_types:
            for device in devices:
                if device["upgradable"]:
                    updates_by_type[device_type].append(device)
                    total_updates += 1

    if total_updates == 0:
        console.print("[bold green]✅ All devices are running the latest firmware![/bold green]")
        client.logout()
        return

    console.print(f"[bold yellow]⚠️  {total_updates} device(s) have firmware updates available[/bold yellow]")
    console.print()

    for device_type in ["firewall", "switch", "ap", "other"]:
        devices = updates_by_type.get(device_type, [])
        if devices:
            type_name = {
                "firewall": "Firewalls/Routers",
                "switch": "Switches",
                "ap": "Access Points",
                "other": "Other",
            }[device_type]

            console.print(f"[bold]{type_name}:[/bold]")
            for device in devices:
                current = device["version"]
                new_ver = device["upgrade_to_firmware"] or "Update Available"
                console.print(f"  • {device['name']}: {current} → {new_ver}")
            console.print()

    console.print("Run 'unifi-mapper inventory update-firmware --filter <type>' to upgrade devices")
    client.logout()


@inventory_app.command("update-firmware")
def update_firmware(
    filter: str = typer.Option(
        ...,
        "--filter", "-f",
        help="Device types to update: all, switch, ap, firewall (comma-separated)",
    ),
    config: Optional[str] = typer.Option(
        None,
        "--config", "-c",
        help="Path to .env config file",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run", "-n",
        help="Show what would be updated without making changes",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-y",
        help="Skip confirmation prompt",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Wait between device upgrades (recommended)",
    ),
    delay: int = typer.Option(
        30,
        "--delay", "-d",
        help="Seconds to wait between device upgrades",
    ),
):
    """⬆️ Update firmware on UniFi devices.

    Triggers firmware updates for devices that have updates available.
    Updates are staggered to avoid overwhelming the network.

    ⚠️  WARNING: Firmware updates will cause device reboots!
    Plan maintenance window accordingly.

    Examples:
        # Preview what would be updated
        unifi-mapper inventory update-firmware --filter switch --dry-run

        # Update all switches
        unifi-mapper inventory update-firmware --filter switch

        # Update all devices (use with caution!)
        unifi-mapper inventory update-firmware --filter all --force
    """
    filter_types = parse_filter(filter)
    show_all = "all" in filter_types

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Connecting to UniFi controller...", total=None)
        client, site = get_api_client(config)

        progress.add_task("Fetching devices...", total=None)
        categorized = fetch_and_categorize_devices(client, site)

    # Find devices with available upgrades
    upgradable_devices = []
    for device_type, devices in categorized.items():
        if show_all or device_type in filter_types:
            for device in devices:
                if device["upgradable"]:
                    upgradable_devices.append(device)

    if not upgradable_devices:
        console.print("[green]✅ No firmware updates available for the selected device types[/green]")
        client.logout()
        return

    # Display upgrade plan
    console.print(Panel.fit(
        f"[bold]Firmware Update Plan[/bold]\n"
        f"Devices to update: {len(upgradable_devices)}\n"
        f"Mode: {'DRY RUN' if dry_run else 'LIVE'}",
        border_style="yellow" if dry_run else "red",
    ))
    console.print()

    # Group by type for display
    by_type: dict[str, list[dict]] = defaultdict(list)
    for device in upgradable_devices:
        by_type[device["type"]].append(device)

    table = Table(
        title="Devices to Update",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Type", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Model", style="green")
    table.add_column("Current", style="yellow")
    table.add_column("New Version", style="green bold")

    for device_type in ["firewall", "switch", "ap", "other"]:
        for device in by_type.get(device_type, []):
            new_ver = device["upgrade_to_firmware"] or "Available"
            table.add_row(
                device_type.upper(),
                device["name"],
                device["model"],
                device["version"],
                new_ver,
            )

    console.print(table)
    console.print()

    if dry_run:
        console.print("[yellow]DRY RUN: No changes will be made[/yellow]")
        client.logout()
        return

    # Confirmation
    if not force:
        console.print("[bold red]⚠️  WARNING: Firmware updates will cause device reboots![/bold red]")
        console.print("Devices may be offline for several minutes during update.")
        console.print()

        confirm = typer.confirm(
            f"Are you sure you want to update {len(upgradable_devices)} device(s)?",
            default=False,
        )

        if not confirm:
            console.print("[yellow]Update cancelled[/yellow]")
            client.logout()
            return

    # Perform updates
    console.print()
    console.print("[bold]Starting firmware updates...[/bold]")

    success_count = 0
    fail_count = 0

    for i, device in enumerate(upgradable_devices, 1):
        device_name = device["name"]
        device_mac = device["mac"]

        console.print(f"\n[{i}/{len(upgradable_devices)}] Upgrading {device_name}...")

        try:
            success = _trigger_firmware_upgrade(client, site, device_mac)

            if success:
                success_count += 1
                console.print("  [green]✓ Upgrade triggered successfully[/green]")
            else:
                fail_count += 1
                console.print("  [red]✗ Failed to trigger upgrade[/red]")

        except Exception as e:
            fail_count += 1
            console.print(f"  [red]✗ Error: {e}[/red]")

        # Wait between upgrades
        if wait and i < len(upgradable_devices):
            console.print(f"  Waiting {delay}s before next upgrade...")
            time.sleep(delay)

    # Summary
    console.print()
    console.print(Panel.fit(
        f"[bold]Update Summary[/bold]\n"
        f"[green]Successful: {success_count}[/green]\n"
        f"[red]Failed: {fail_count}[/red]",
        border_style="green" if fail_count == 0 else "yellow",
    ))

    if success_count > 0:
        console.print()
        console.print("[yellow]Note: Devices will reboot to apply updates.[/yellow]")
        console.print("Monitor the UniFi Controller for progress.")

    client.logout()


# Standalone entry point for direct execution
def main():
    """Standalone entry point."""
    inventory_app()


if __name__ == "__main__":
    main()
