"""Tests for the shared ping output parser (GNU and BusyBox variants).

Ported from the July work (a local archive, not in the repo) with documentation addresses.
"""

from unifi_mapper.core.utils.ping_parse import parse_ping_output


GNU_OUTPUT = """\
PING 192.0.2.10 (192.0.2.10) 56(84) bytes of data.
64 bytes from 192.0.2.10: icmp_seq=1 ttl=64 time=1.23 ms
64 bytes from 192.0.2.10: icmp_seq=2 ttl=64 time=1.45 ms
64 bytes from 192.0.2.10: icmp_seq=3 ttl=64 time=1.10 ms

--- 192.0.2.10 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 1.100/1.260/1.450/0.144 ms
"""

BUSYBOX_OUTPUT = """\
PING 192.0.2.10 (192.0.2.10): 56 data bytes

--- 192.0.2.10 ping statistics ---
10 packets transmitted, 8 packets received, 20% packet loss
round-trip min/avg/max = 2.100/5.500/12.300 ms
"""

TOTAL_LOSS_OUTPUT = """\
PING 192.0.2.10 (192.0.2.10) 56(84) bytes of data.

--- 192.0.2.10 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss, time 4100ms
"""


def test_gnu_variant_full_parse() -> None:
    stats = parse_ping_output(GNU_OUTPUT)
    assert stats.transmitted == 3
    assert stats.received == 3
    assert stats.loss_pct == 0.0
    assert stats.rtt_min == 1.100
    assert stats.rtt_avg == 1.260
    assert stats.rtt_max == 1.450
    assert stats.rtt_mdev == 0.144
    assert stats.reachable


def test_busybox_variant_no_mdev() -> None:
    stats = parse_ping_output(BUSYBOX_OUTPUT)
    assert stats.transmitted == 10
    assert stats.received == 8
    assert stats.loss_pct == 20.0
    assert stats.rtt_avg == 5.5
    assert stats.rtt_mdev is None
    assert stats.reachable


def test_total_loss() -> None:
    stats = parse_ping_output(TOTAL_LOSS_OUTPUT)
    assert stats.loss_pct == 100.0
    assert stats.rtt_avg is None
    assert not stats.reachable


def test_garbage_output_treated_as_unreachable() -> None:
    stats = parse_ping_output('ping: unknown host nowhere.invalid')
    assert stats.loss_pct == 100.0
    assert stats.transmitted == 0
    assert not stats.reachable


def test_loss_computed_from_counts_when_pct_missing() -> None:
    stats = parse_ping_output('4 packets transmitted, 3 received')
    assert stats.loss_pct == 25.0
    assert stats.reachable


def test_fractional_loss_is_read_whole() -> None:
    stats = parse_ping_output('3 packets transmitted, 2 received, 33.3333% packet loss')
    assert stats.loss_pct == 33.3333
