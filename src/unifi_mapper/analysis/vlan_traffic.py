"""Per-VLAN traffic sampling: ``unifi-mapper vlan-traffic sample`` (class B, CLI only).

The controller keeps no per-VLAN byte counter, and its own reports age out within weeks, so
one sample reads every ``br*`` bridge interface's cumulative byte counters on the gateway,
over SSH in one command, and stores a row per VLAN in the local store
(``analysis/vlan_traffic_store.py``), whose rollups and reports give 1w, 1m and 1y averages
and peaks. A VLAN is matched to its interface by subnet, never by a ``br<vlan>`` naming
convention (``analysis/vlan_interfaces.py``); a VLAN with no live interface is listed under
``unresolved``, never dropped. Counters are read for ``br*`` bridges only, so a VLAN whose
matched interface is not a bridge is listed under ``skipped`` (no counters), never sampled
from another interface.

The controller's network list is read through ``UniFiClient()``, which borrows the
read-only holder the CLI installs (the legacy ``rest/networkconf`` records, whose subnets
the resolver matches). The SSH command is one fixed script run as ``sh -c`` with no value
from a user or the controller in it, through ``analysis/gateway_ssh.py`` with a 30 s bound;
it runs on the gateway as the SSH user, whose host key is not verified (issue 038), which is
also why no schedule is published for the sampler until 038 is decided. No MCP tool triggers
a sample (decision D1 in issue 060); the MCP tools read stored results only.

Ported from the July work (a local archive, not in the repo): the script and the two
parsers are July's; the sampler is rebuilt on the shared SSH and store helpers, and the
parsers refuse output that July read as an empty or a partial sample (review B4, final
council F4).
"""

import json
import re
import time
from pathlib import Path
from typing import Any
from unifi_mapper.analysis.gateway_ssh import (
    check_exit_status,
    gateway_session,
    run_gateway_command,
    ssh_login,
)
from unifi_mapper.analysis.vlan_interfaces import resolve_vlan_interfaces
from unifi_mapper.analysis.vlan_traffic_store import default_db_path, insert_samples
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.redact import redact_text


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
# The script's exit status is its last command's, ``ip -4 -j addr show``, so a ``cat`` that
# fails shows only as an empty counter field, which parse_bridge_counters refuses.
SAMPLE_PROGRAM = 'the VLAN sample script'
SAMPLE_SUGGESTION = (
    "Check that the SSH user may run 'ip -4 -j addr show' and read /sys/class/net on the "
    'gateway (UNIFI_SSH_USERNAME)'
)
_COUNTER_RE = re.compile(r'[0-9]+')


def parse_bridge_counters(output: str) -> dict[str, dict[str, int]]:
    """Parse the counter lines (``<iface> <rx_bytes> <tx_bytes>``) before the marker. Pure.

    Every line that is not blank is a bridge's. The script exits with ``ip``'s status, so a
    ``cat`` that could not read a counter shows only as an empty field: a line that is not
    three fields ending in two non-negative integers fails the whole sample, never leaving
    out that bridge and storing the rest (final council F4).

    Args:
        output: The script's stdout before :data:`ADDR_MARKER`.

    Returns:
        Interface name to ``{rx_bytes, tx_bytes}``, one entry per bridge line.

    Raises:
        ToolError: ``API_ERROR`` for a bridge line without two integer counters, the line
            redacted in the message.
    """
    counters: dict[str, dict[str, int]] = {}
    for line in output.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 3 or not all(_COUNTER_RE.fullmatch(raw) for raw in parts[1:]):
            raise ToolError(
                message=(
                    'the VLAN sample script printed a bridge line without two integer '
                    f'counters: {redact_text(line)!r}'
                ),
                error_code=ErrorCodes.API_ERROR,
                suggestion=SAMPLE_SUGGESTION,
            )
        iface, rx_raw, tx_raw = parts
        counters[iface] = {'rx_bytes': int(rx_raw), 'tx_bytes': int(tx_raw)}
    return counters


def split_sample_output(stdout: str) -> tuple[str, list[dict[str, Any]]]:
    """Split the script's stdout into the counter text and the parsed address list. Pure.

    The address list is what matches a VLAN to its interface, so output without it is a
    failed sample, never an empty one: read as "no addresses", it would put every VLAN under
    ``unresolved`` and store nothing, silently.

    Args:
        stdout: The sample script's standard output.

    Returns:
        ``(counter text, addresses)``: the text before :data:`ADDR_MARKER`, and the address
        entries (dicts; any other entry is dropped) after it. An empty list is a gateway
        with no IPv4 address.

    Raises:
        ToolError: ``API_ERROR`` when the marker is missing, or what follows it is not a JSON
            list.
    """
    if ADDR_MARKER not in stdout:
        raise ToolError(
            message='the VLAN sample script printed no address list',
            error_code=ErrorCodes.API_ERROR,
            suggestion=SAMPLE_SUGGESTION,
        )
    counters_block, _, json_block = stdout.partition(ADDR_MARKER)
    try:
        parsed = json.loads(json_block)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, list):
        raise ToolError(
            message='the VLAN sample script printed an address list that is not a JSON list',
            error_code=ErrorCodes.API_ERROR,
            suggestion=SAMPLE_SUGGESTION,
        )
    return counters_block, [entry for entry in parsed if isinstance(entry, dict)]


async def sample_vlan_traffic(db_path: Path | None = None) -> dict[str, Any]:
    """Sample every resolved VLAN's bridge counters once and store one row each.

    The SSH login is checked first, then the network list is read (one controller call),
    the script run (one SSH command), each VLAN matched to its interface by subnet, and the
    rows written in one transaction. A script that exits with a failure status, prints no
    parseable address list, or prints a bridge line without two integer counters, is an
    error and stores nothing, so a sample is never partial. A run that resolves no VLAN
    to an interface with counters returns an empty ``sampled`` and writes nothing; the CLI
    exits 1 for it, so a schedule notices.

    Args:
        db_path: The store (default ``vlan_traffic_store.default_db_path()``).

    Returns:
        ``ts`` (the sample's Unix time), ``sampled`` (``{vlan_id, network_name, iface,
        rx_bytes, tx_bytes}`` each), ``unresolved`` (VLANs with no live interface), and
        ``skipped`` (resolved VLANs whose interface printed no counter line, such as one that
        is not a ``br*`` bridge).

    Raises:
        ToolError: ``CONFIG_MISSING`` without the SSH password; the controller's and the SSH
            connection's errors; ``TIMEOUT`` past 30 s; ``API_ERROR`` when the script fails
            or prints no address list, with its last stderr line redacted (for example
            ``the VLAN sample script could not run on the gateway (exit status 127): sh: ip:
            not found``), when a bridge line has no two integer counters (that line
            redacted), and when the store can't be written.
    """
    ssh_login()  # a missing SSH password fails before the controller is asked
    async with UniFiClient() as client:
        networks = await client.get_networks()
    async with gateway_session() as conn:
        result = await run_gateway_command(
            conn, ['sh', '-c', SAMPLE_SCRIPT], timeout=SAMPLE_TIMEOUT
        )
    check_exit_status(result, SAMPLE_PROGRAM)
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
