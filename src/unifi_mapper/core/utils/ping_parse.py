"""Ping output parsing shared by the gateway SSH tools.

Handles both GNU iputils (``rtt min/avg/max/mdev``) and BusyBox (``round-trip
min/avg/max``) output, the two variants seen on UniFi OS consoles and APs. Pure: no I/O.
Used by ``diagnose latency-matrix`` and the gateway probes.
"""

import re
from dataclasses import dataclass


# GNU: "rtt min/avg/max/mdev = 0.123/0.456/0.789/0.012 ms"
# BusyBox: "round-trip min/avg/max = 0.123/0.456/0.789 ms"
RTT_RE = re.compile(
    r'(?:rtt|round-trip) min/avg/max(?:/(?:mdev|stddev))?'
    r' = ([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?'
)
LOSS_RE = re.compile(r'(\d+) packets transmitted, (\d+) (?:packets )?received')
LOSS_PCT_RE = re.compile(r'([\d.]+)% packet loss')


@dataclass
class PingStats:
    """Parsed statistics from one ping run.

    Attributes:
        transmitted: Packets sent, from ping's counts line (0 if it did not parse).
        received: Replies counted on that line (0 if it did not parse).
        loss_pct: Packet loss in percent: ping's own ``% packet loss`` figure when printed,
            else computed from the counts, else 100.
        rtt_min: Fastest round trip in ms, or None without a round-trip line.
        rtt_avg: Mean round trip in ms, or None.
        rtt_max: Slowest round trip in ms, or None.
        rtt_mdev: GNU ping's mean deviation in ms, or None (BusyBox does not print it).
    """

    transmitted: int
    received: int
    loss_pct: float
    rtt_min: float | None = None
    rtt_avg: float | None = None
    rtt_max: float | None = None
    rtt_mdev: float | None = None

    @property
    def reachable(self) -> bool:
        """Whether any reply came back: the one rule every caller uses.

        The counted replies decide when the counts line parsed (``received > 0``, even when
        the computed loss rounds to 100); without it, the ``% packet loss`` line does
        (``loss_pct < 100``). Output with neither is unreachable.
        """
        if self.transmitted > 0:
            return self.received > 0
        return self.loss_pct < 100


def parse_ping_output(output: str) -> PingStats:
    """Parse ping stdout into ``PingStats``.

    Args:
        output: Raw stdout from a ping command (GNU or BusyBox format).

    Returns:
        PingStats. If nothing parseable is found, 100% loss with zero packet counts (the
        target is treated as unreachable).
    """
    transmitted = 0
    received = 0
    loss_pct = 100.0

    loss_match = LOSS_RE.search(output)
    if loss_match:
        transmitted = int(loss_match.group(1))
        received = int(loss_match.group(2))
        if transmitted > 0:
            loss_pct = round(100 * (transmitted - received) / transmitted, 1)

    pct_match = LOSS_PCT_RE.search(output)
    if pct_match:
        loss_pct = float(pct_match.group(1))

    stats = PingStats(transmitted=transmitted, received=received, loss_pct=loss_pct)

    rtt_match = RTT_RE.search(output)
    if rtt_match:
        stats.rtt_min = float(rtt_match.group(1))
        stats.rtt_avg = float(rtt_match.group(2))
        stats.rtt_max = float(rtt_match.group(3))
        if rtt_match.group(4) is not None:
            stats.rtt_mdev = float(rtt_match.group(4))

    return stats
