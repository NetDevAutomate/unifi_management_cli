"""Per-VLAN traffic sampling: ``unifi-mapper vlan-traffic sample`` (class B, CLI only).

The controller keeps no per-VLAN byte counter, and its own reports age out within weeks, so
one sample reads every ``br*`` bridge interface's cumulative byte counters on the gateway,
over SSH in one command, and stores a row per VLAN in the local store
(``analysis/vlan_traffic_store.py``), whose rollups and reports give honest 1w, 1m and 1y
averages and peaks. A VLAN is matched to its interface by subnet, never by a ``br<vlan>``
naming convention (``analysis/vlan_interfaces.py``); a VLAN with no live interface is listed
under ``unresolved``, never dropped.

The controller's network list is read through ``UniFiClient()``, which borrows the
read-only holder the CLI installs (the legacy ``rest/networkconf`` records, whose subnets
the resolver matches). The SSH command is one fixed script run as ``sh -c`` with no value
from a user or the controller in it, through ``analysis/gateway_ssh.py`` with a 30 s bound;
it runs on the gateway as the SSH user, whose host key is not verified (issue 038), which is
also why no schedule is published for the sampler until 038 is decided. No MCP tool triggers
a sample (decision D1 in issue 060); the MCP tools read stored results only.

Ported from the July work (a local archive, not in the repo): the script and the two
parsers are July's, unchanged in logic; the sampler is rebuilt on the shared SSH and store
helpers.
"""

import json
import time
from pathlib import Path
from typing import Any
from unifi_mapper.analysis.gateway_ssh import gateway_session, run_gateway_command, ssh_login
from unifi_mapper.analysis.vlan_interfaces import resolve_vlan_interfaces
from unifi_mapper.analysis.vlan_traffic_store import default_db_path, insert_samples
from unifi_mapper.core.utils.client import UniFiClient


# For each br* interface print "iface rx_bytes tx_bytes", then a marker line, then the
# interfaces' addresses as JSON for the subnet match. A constant: nothing is interpolated.
SAMPLE_SCRIPT = (
    'for i in /sys/class/net/br*; do '
    'n=$(basename "$i"); '
    'echo "$n $(cat "$i"/statistics/rx_bytes) $(cat "$i"/statistics/tx_bytes)"; '
    'done; echo "===ADDR==="; ip -4 -j addr show'
)
SAMPLE_TIMEOUT = 30
ADDR_MARKER = '===ADDR==='


def parse_bridge_counters(output: str) -> dict[str, dict[str, int]]:
    """Parse the counter lines (``<iface> <rx_bytes> <tx_bytes>``) before the marker. Pure.

    Args:
        output: The script's stdout before :data:`ADDR_MARKER`.

    Returns:
        Interface name to ``{rx_bytes, tx_bytes}``; a line that is not three fields with two
        integers is skipped.
    """
    counters: dict[str, dict[str, int]] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        iface, rx_raw, tx_raw = parts
        try:
            counters[iface] = {'rx_bytes': int(rx_raw), 'tx_bytes': int(tx_raw)}
        except ValueError:
            continue
    return counters


def split_sample_output(stdout: str) -> tuple[str, list[dict[str, Any]]]:
    """Split the script's stdout into the counter text and the parsed address list. Pure.

    Returns:
        ``(counter text, addresses)``; the addresses are ``[]`` when the marker is missing or
        what follows it is not a JSON list.
    """
    if ADDR_MARKER in stdout:
        counters_block, _, json_block = stdout.partition(ADDR_MARKER)
    else:
        counters_block, json_block = stdout, ''
    try:
        parsed = json.loads(json_block.strip()) if json_block.strip() else []
    except json.JSONDecodeError:
        parsed = []
    if not isinstance(parsed, list):
        parsed = []
    return counters_block, [entry for entry in parsed if isinstance(entry, dict)]


async def sample_vlan_traffic(db_path: Path | None = None) -> dict[str, Any]:
    """Sample every resolved VLAN's bridge counters once and store one row each.

    The SSH login is checked first, then the network list is read (one controller call),
    the script run (one SSH command), each VLAN matched to its interface by subnet, and the
    rows written in one transaction.

    Args:
        db_path: The store (default ``vlan_traffic_store.default_db_path()``).

    Returns:
        ``ts`` (the sample's Unix time), ``sampled`` (``{vlan_id, network_name, iface,
        rx_bytes, tx_bytes}`` each), ``unresolved`` (VLANs with no live interface), and
        ``skipped`` (resolved VLANs whose interface printed no counters this time).

    Raises:
        ToolError: ``CONFIG_MISSING`` without the SSH password, the controller's and the SSH
            connection's errors, ``TIMEOUT`` past 30 s, and ``API_ERROR`` when the store
            can't be written.
    """
    ssh_login()  # a missing SSH password fails before the controller is asked
    async with UniFiClient() as client:
        networks = await client.get_networks()
    async with gateway_session() as conn:
        result = await run_gateway_command(
            conn, ['sh', '-c', SAMPLE_SCRIPT], timeout=SAMPLE_TIMEOUT
        )
    counters_text, addresses = split_sample_output(result.stdout)
    counters = parse_bridge_counters(counters_text)
    resolution = resolve_vlan_interfaces([n for n in networks if isinstance(n, dict)], addresses)
    ts = int(time.time())
    sampled, skipped = [], []
    for entry in resolution['resolved']:
        counter = counters.get(entry['iface'])
        if counter is None:
            skipped.append(entry)
            continue
        sampled.append(
            {
                'ts_utc': ts,
                'vlan_id': entry['vlan_id'],
                'network_name': entry['network_name'],
                'iface': entry['iface'],
                **counter,
            }
        )
    if sampled:
        insert_samples(default_db_path() if db_path is None else Path(db_path), sampled)
    return {
        'ts': ts,
        'sampled': sampled,
        'unresolved': resolution['unresolved'],
        'skipped': skipped,
    }
