"""Tests for the reset-aware VAP counter deltas (``core/utils/counters``).

Ported from the July work (a local archive, not in the repo) with generic SSIDs.
"""

from unifi_mapper.core.utils.counters import (
    VapCounters,
    pick_vap,
    retry_delta,
    vap_counters_from_dict,
)


def _vap(essid: str, tx_packets: int, tx_retries: int) -> VapCounters:
    return VapCounters(essid=essid, tx_packets=tx_packets, tx_retries=tx_retries)


class TestVapCountersFromDict:
    def test_full_entry(self) -> None:
        vap = vap_counters_from_dict(
            {
                'essid': 'SSID A',
                'tx_packets': 1000,
                'tx_retries': 50,
                'tx_dropped': 2,
                'rx_packets': 900,
                'num_sta': 12,
                'channel': 11,
            }
        )
        assert vap.essid == 'SSID A'
        assert vap.tx_packets == 1000
        assert vap.tx_retries == 50
        assert vap.channel == 11

    def test_missing_counters_coerce_to_zero(self) -> None:
        vap = vap_counters_from_dict({'essid': 'SSID A'})
        assert vap.tx_packets == 0
        assert vap.tx_retries == 0
        assert vap.num_sta == 0
        assert vap.channel is None

    def test_none_counters_coerce_to_zero(self) -> None:
        vap = vap_counters_from_dict({'essid': 'SSID A', 'tx_packets': None, 'tx_retries': None})
        assert vap.tx_packets == 0
        assert vap.tx_retries == 0

    def test_missing_essid_defaults(self) -> None:
        assert vap_counters_from_dict({}).essid == '?'


class TestPickVap:
    def test_prefers_named_ssid(self) -> None:
        vaps = [_vap('SSID B', 9999, 1), _vap('SSID A', 10, 1)]
        picked = pick_vap(vaps, 'SSID A')
        assert picked is not None
        assert picked.essid == 'SSID A'

    def test_falls_back_to_busiest(self) -> None:
        vaps = [_vap('SSID B', 100, 1), _vap('SSID C', 5000, 1)]
        picked = pick_vap(vaps, 'SSID A')
        assert picked is not None
        assert picked.essid == 'SSID C'

    def test_empty_returns_none(self) -> None:
        assert pick_vap([], 'SSID A') is None


class TestRetryDelta:
    def test_first_sample_uses_cumulative_as_delta(self) -> None:
        cur = [_vap('SSID A', 1000, 100)]
        assert retry_delta(None, cur, 'SSID A') == (1000, 100, 10.0)

    def test_normal_interval_delta(self) -> None:
        prev = [_vap('SSID A', 1000, 100)]
        cur = [_vap('SSID A', 1500, 150)]
        assert retry_delta(prev, cur, 'SSID A') == (500, 50, 10.0)

    def test_counter_reset_treated_as_fresh_baseline(self) -> None:
        """An AP reboot resets the cumulative counters: never a negative delta."""
        prev = [_vap('SSID A', 100_000, 5_000)]
        cur = [_vap('SSID A', 200, 20)]  # rebooted: cumulative < previous
        dp, dr, pct = retry_delta(prev, cur, 'SSID A')
        assert (dp, dr) == (200, 20)
        assert pct == 10.0
        assert dp >= 0 and dr >= 0

    def test_vap_vanished_from_previous_sample(self) -> None:
        """A VAP absent from the previous sample: its cumulative value is the delta."""
        prev = [_vap('SSID B', 500, 10)]
        cur = [_vap('SSID B', 600, 12), _vap('SSID A', 300, 30)]
        assert retry_delta(prev, cur, 'SSID A') == (300, 30, 10.0)

    def test_no_traffic_gives_none_pct(self) -> None:
        """A zero packet delta gives no percentage, not 0.0."""
        prev = [_vap('SSID A', 1000, 100)]
        cur = [_vap('SSID A', 1000, 100)]
        dp, dr, pct = retry_delta(prev, cur, 'SSID A')
        assert (dp, dr) == (0, 0)
        assert pct is None

    def test_no_vaps_at_all(self) -> None:
        assert retry_delta(None, [], 'SSID A') == (0, 0, None)

    def test_fallback_vap_tracked_consistently(self) -> None:
        """Without the SSID, the busiest VAP's own SSID is matched in the previous sample."""
        prev = [_vap('SSID B', 1000, 10), _vap('SSID C', 2000, 20)]
        cur = [_vap('SSID B', 1100, 11), _vap('SSID C', 2500, 45)]
        assert retry_delta(prev, cur, 'Missing SSID') == (500, 25, 5.0)
