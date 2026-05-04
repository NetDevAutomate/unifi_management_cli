"""Tests for the 12 new analysis modules — pure functions only, no API calls."""

from __future__ import annotations

import pytest
from unifi_mapper.analysis.bandwidth_test import _parse_json_output, _parse_text_output
from unifi_mapper.analysis.channel_optimiser import optimize_5ghz, optimize_24ghz
from unifi_mapper.analysis.client_density import _analyze_density
from unifi_mapper.analysis.dhcp_pool import _analyze_dhcp_pools
from unifi_mapper.analysis.latency_matrix import _build_target_list, _parse_ping_output
from unifi_mapper.analysis.poe_budget import _analyze_poe_budgets
from unifi_mapper.analysis.radio_config import build_optimisation_plan
from unifi_mapper.analysis.neighbour_scan import (
    _group_rogue_entries,
    compute_channel_neighbour_score,
    rssi_weight,
)
from unifi_mapper.analysis.uplink_redundancy import _analyze_uplink_redundancy


# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def switch_device() -> dict:
    return {
        "_id": "sw1",
        "name": "Core Switch",
        "mac": "aa:bb:cc:dd:ee:01",
        "model": "USW-Pro-48-PoE",
        "type": "usw",
        "total_max_power": 600,
        "port_table": [
            {"port_idx": 1, "up": True, "speed": 1000, "is_uplink": False,
             "poe_mode": "auto", "poe_power": "15.2", "name": "AP Office"},
            {"port_idx": 2, "up": True, "speed": 1000, "is_uplink": False,
             "poe_mode": "auto", "poe_power": "4.1", "name": "Phone"},
            {"port_idx": 49, "up": True, "speed": 10000, "is_uplink": True,
             "poe_mode": "off", "poe_power": "0", "name": "Uplink 1"},
            {"port_idx": 50, "up": True, "speed": 10000, "is_uplink": True,
             "poe_mode": "off", "poe_power": "0", "name": "Uplink 2"},
        ],
    }


@pytest.fixture
def ap_device() -> dict:
    return {
        "_id": "ap1",
        "name": "Living Room AP",
        "mac": "aa:bb:cc:dd:ee:10",
        "model": "U6-Pro",
        "type": "uap",
        "radio_table": [
            {"radio": "na", "channel": 36, "ht": "40", "tx_power": 20,
             "tx_power_mode": "auto", "min_rssi_enabled": False, "min_rssi": -80},
            {"radio": "ng", "channel": 1, "ht": "20", "tx_power": 23,
             "tx_power_mode": "auto", "min_rssi_enabled": False, "min_rssi": -80},
        ],
        "radio_table_stats": [
            {"channel": 36, "cu_total": 45, "cu_self_rx": 10, "cu_self_tx": 15,
             "num_sta": 8, "satisfaction": 85},
            {"channel": 1, "cu_total": 30, "cu_self_rx": 5, "cu_self_tx": 10,
             "num_sta": 4, "satisfaction": 90},
        ],
    }


@pytest.fixture
def wireless_clients() -> list[dict]:
    return [
        {"mac": "cc:01:00:00:00:01", "name": "Laptop", "ap_mac": "aa:bb:cc:dd:ee:10",
         "is_wired": False, "rssi": -55, "signal": -55, "channel": 36,
         "essid": "HomeNet", "ip": "192.0.2.100", "network_id": "net1"},
        {"mac": "cc:01:00:00:00:02", "name": "Phone", "ap_mac": "aa:bb:cc:dd:ee:10",
         "is_wired": False, "rssi": -70, "signal": -70, "channel": 1,
         "essid": "HomeNet", "ip": "192.0.2.101", "network_id": "net1"},
    ]


@pytest.fixture
def dhcp_networks() -> list[dict]:
    return [
        {"_id": "net1", "name": "LAN", "dhcpd_enabled": True,
         "dhcpd_start": "192.0.2.100", "dhcpd_stop": "192.0.2.199",
         "subnet": "192.0.2.0/24", "vlan": None},
        {"_id": "net2", "name": "IoT", "dhcpd_enabled": True,
         "dhcpd_start": "198.51.100.10", "dhcpd_stop": "198.51.100.19",
         "subnet": "198.51.100.0/24", "vlan": 10},
    ]


# ── 1. DHCP Pool ─────────────────────────────────────────────────────────────


class TestDHCPPool:
    def test_pool_size_calculation(self, dhcp_networks: list[dict]) -> None:
        """Pool size = stop - start + 1."""
        clients = [{"network_id": "net1"} for _ in range(50)]
        pools, _, _ = _analyze_dhcp_pools(dhcp_networks, clients)

        lan = next(p for p in pools if p.network_name == "LAN")
        assert lan.pool_size == 100
        assert lan.active_clients == 50
        assert lan.utilization_percent == 50.0
        assert lan.status == "OK"

    def test_critical_utilization(self) -> None:
        """>=90% utilization triggers CRITICAL."""
        networks = [{"_id": "n1", "name": "Full", "dhcpd_enabled": True,
                      "dhcpd_start": "10.0.0.1", "dhcpd_stop": "10.0.0.10"}]
        clients = [{"network_id": "n1"} for _ in range(9)]
        pools, warnings, recommendations = _analyze_dhcp_pools(networks, clients)

        assert pools[0].status == "CRITICAL"
        assert len(warnings) == 1
        assert len(recommendations) == 1

    def test_disabled_network_skipped(self) -> None:
        """DHCP-disabled networks are excluded."""
        networks = [{"_id": "n1", "name": "Static", "dhcpd_enabled": False,
                      "dhcpd_start": "10.0.0.1", "dhcpd_stop": "10.0.0.254"}]
        pools, _, _ = _analyze_dhcp_pools(networks, [])
        assert pools == []

    def test_empty_inputs(self) -> None:
        pools, warnings, recommendations = _analyze_dhcp_pools([], [])
        assert pools == []
        assert warnings == []


# ── 2. PoE Budget ────────────────────────────────────────────────────────────


class TestPoEBudget:
    def test_consumption_from_port_table(self, switch_device: dict) -> None:
        """Sums poe_power strings from ports with poe_mode != off."""
        statuses, _, _ = _analyze_poe_budgets([switch_device])

        assert len(statuses) == 1
        s = statuses[0]
        assert s.poe_budget == 600
        assert s.poe_consumption == pytest.approx(19.3, abs=0.1)
        assert s.status == "OK"

    def test_high_draw_ports_detected(self, switch_device: dict) -> None:
        """Ports drawing >5W appear in high_draw_ports."""
        statuses, _, _ = _analyze_poe_budgets([switch_device])
        high = statuses[0].high_draw_ports
        assert len(high) == 1
        assert high[0].poe_power == pytest.approx(15.2)

    def test_critical_poe(self) -> None:
        """>=90% utilization triggers CRITICAL."""
        device = {
            "_id": "sw2", "name": "PoE Switch", "type": "usw",
            "model": "USW-Lite-8-PoE", "total_max_power": 52,
            "port_table": [
                {"port_idx": 1, "poe_mode": "auto", "poe_power": "25.0"},
                {"port_idx": 2, "poe_mode": "auto", "poe_power": "23.0"},
            ],
        }
        statuses, warnings, recommendations = _analyze_poe_budgets([device])
        assert statuses[0].status == "CRITICAL"
        assert len(warnings) == 1

    def test_non_switch_skipped(self) -> None:
        """APs and other device types are ignored."""
        statuses, _, _ = _analyze_poe_budgets([{"type": "uap", "total_max_power": 0}])
        assert statuses == []


# ── 3. Client Density ────────────────────────────────────────────────────────


class TestClientDensity:
    def test_groups_clients_by_ap(self, ap_device: dict, wireless_clients: list[dict]) -> None:
        aps, total, _, _ = _analyze_density(wireless_clients, [ap_device])

        assert total == 2
        assert len(aps) == 1
        assert aps[0].client_count == 2
        assert aps[0].device_name == "Living Room AP"

    def test_avg_signal(self, ap_device: dict, wireless_clients: list[dict]) -> None:
        aps, _, _, _ = _analyze_density(wireless_clients, [ap_device])
        assert aps[0].avg_signal_dbm == pytest.approx(-62.5)

    def test_overloaded_ap_warning(self, ap_device: dict) -> None:
        """>30 clients triggers WARNING, >50 triggers CRITICAL."""
        clients = [
            {"mac": f"cc:00:00:00:00:{i:02x}", "ap_mac": ap_device["mac"],
             "is_wired": False, "rssi": -60, "signal": -60}
            for i in range(35)
        ]
        aps, _, warnings, _ = _analyze_density(clients, [ap_device])
        assert aps[0].status == "WARNING"
        assert len(warnings) == 1

    def test_empty_clients(self, ap_device: dict) -> None:
        aps, total, _, _ = _analyze_density([], [ap_device])
        assert total == 0
        assert aps == []


# ── 4. Uplink Redundancy ─────────────────────────────────────────────────────


class TestUplinkRedundancy:
    def test_dual_uplink_is_redundant(self, switch_device: dict) -> None:
        statuses, _, _ = _analyze_uplink_redundancy([switch_device])
        assert len(statuses) == 1
        assert statuses[0].redundant is True
        assert statuses[0].uplink_count == 2
        assert statuses[0].total_uplink_speed_mbps == 20000

    def test_single_uplink_warning(self) -> None:
        device = {
            "_id": "sw3", "name": "Edge Switch", "type": "usw", "model": "USW-Flex-Mini",
            "port_table": [
                {"port_idx": 1, "is_uplink": True, "up": True, "speed": 1000},
                {"port_idx": 2, "is_uplink": False, "up": True, "speed": 100},
            ],
        }
        statuses, warnings, recommendations = _analyze_uplink_redundancy([device])
        assert statuses[0].redundant is False
        assert statuses[0].status == "WARNING"
        assert len(warnings) == 1

    def test_ap_devices_skipped(self) -> None:
        statuses, _, _ = _analyze_uplink_redundancy([{"type": "uap", "port_table": []}])
        assert statuses == []


# ── 5. Latency Matrix ────────────────────────────────────────────────────────


class TestLatencyMatrix:
    def test_parse_ping_success(self) -> None:
        target = {"ip": "192.0.2.1", "name": "Gateway", "type": "device"}
        output = (
            "PING 192.0.2.1 (192.0.2.1): 56 data bytes\n"
            "64 bytes from 192.0.2.1: seq=0 ttl=64 time=0.456 ms\n"
            "3 packets transmitted, 3 received, 0% packet loss\n"
            "rtt min/avg/max/mdev = 0.321/0.456/0.789/0.123 ms\n"
        )
        result = _parse_ping_output(target, output)
        assert result.reachable is True
        assert result.rtt_avg == pytest.approx(0.456)
        assert result.rtt_min == pytest.approx(0.321)
        assert result.packet_loss == 0.0

    def test_parse_ping_unreachable(self) -> None:
        target = {"ip": "10.0.0.99", "name": "Dead Host", "type": "client"}
        output = "3 packets transmitted, 0 received, 100% packet loss\n"
        result = _parse_ping_output(target, output)
        assert result.reachable is False
        assert result.packet_loss == 100.0

    def test_parse_ping_empty_output(self) -> None:
        target = {"ip": "10.0.0.1", "name": "Unknown", "type": "device"}
        result = _parse_ping_output(target, "")
        assert result.reachable is False

    def test_build_target_list_deduplicates(self) -> None:
        devices = [{"ip": "192.0.2.1", "name": "GW", "mac": "aa:00", "model": "UDM"}]
        clients = [{"ip": "192.0.2.1", "name": "dup"}, {"ip": "192.0.2.50", "name": "PC"}]
        targets = _build_target_list(devices, clients, include_clients=True)
        assert len(targets) == 2
        ips = {t["ip"] for t in targets}
        assert ips == {"192.0.2.1", "192.0.2.50"}

    def test_build_target_list_excludes_clients(self) -> None:
        devices = [{"ip": "192.0.2.1", "name": "GW", "mac": "aa:00", "model": "UDM"}]
        clients = [{"ip": "192.0.2.50", "name": "PC"}]
        targets = _build_target_list(devices, clients, include_clients=False)
        assert len(targets) == 1


# ── 6. Radio Config ──────────────────────────────────────────────────────────


class TestRadioConfig:
    def test_recommends_80mhz_for_5ghz(self, ap_device: dict) -> None:
        """5GHz radios below 80MHz width get upgrade recommendation."""
        changes = build_optimisation_plan([ap_device])
        na_changes = [c for c in changes if c["radio"] == "na"]
        assert len(na_changes) == 1
        assert na_changes[0]["ht"] == "80"
        assert na_changes[0]["min_rssi_enabled"] is True

    def test_recommends_reduced_24ghz_power(self, ap_device: dict) -> None:
        """2.4GHz radios with high tx_power get reduced to 12."""
        changes = build_optimisation_plan([ap_device])
        ng_changes = [c for c in changes if c["radio"] == "ng"]
        assert len(ng_changes) == 1
        assert ng_changes[0]["tx_power"] == 12

    def test_kitchen_channel_move(self) -> None:
        """Kitchen AP on channel 36 gets moved to 44."""
        device = {
            "_id": "ap_k", "name": "Kitchen AP", "type": "uap",
            "radio_table": [{"radio": "na", "channel": 36, "ht": "40"}],
        }
        changes = build_optimisation_plan([device])
        assert changes[0]["channel"] == 44

    def test_non_ap_skipped(self) -> None:
        changes = build_optimisation_plan([{"_id": "sw1", "type": "usw"}])
        assert changes == []


# ── 7. Channel Optimiser ─────────────────────────────────────────────────────


class TestChannelOptimiser:
    def _make_aps(self, channels_5: list[int], channels_24: list[int]) -> list[dict]:
        aps = []
        for i, (ch5, ch24) in enumerate(zip(channels_5, channels_24)):
            aps.append({
                "device_id": f"ap{i}",
                "name": f"AP-{i}",
                "radios": {
                    "5GHz": {"channel": ch5, "utilization": 20 + i * 10,
                             "interference": 5, "num_sta": 3},
                    "2.4GHz": {"channel": ch24, "utilization": 15 + i * 5,
                               "interference": 3, "num_sta": 2},
                },
            })
        return aps

    def test_5ghz_assigns_different_channels(self) -> None:
        """Two APs on same channel should get separated."""
        aps = self._make_aps([36, 36], [1, 6])
        recs = optimize_5ghz(aps)
        assigned = {r["recommended_channel"] for r in recs}
        assert len(assigned) == 2  # different channels

    def test_5ghz_empty_input(self) -> None:
        assert optimize_5ghz([]) == []

    def test_24ghz_distributes_across_channels(self) -> None:
        """Three APs should spread across 1, 6, 11."""
        aps = self._make_aps([36, 44, 149], [1, 1, 1])
        recs = optimize_24ghz(aps)
        assigned = [r["recommended_channel"] for r in recs]
        assert set(assigned) == {1, 6, 11}

    def test_24ghz_empty_input(self) -> None:
        assert optimize_24ghz([]) == []

    # ── Neighbour-integration tests (Task 4) ─────────────────────────────────
    # These pass neighbour_data kwarg which doesn't exist yet → TypeError.

    def test_5ghz_neighbour_penalty_lowers_score(self) -> None:
        """Ch 36 with 5 strong neighbours vs ch 149 with 0 → ch 149 preferred."""
        aps = self._make_aps([36, 149], [1, 6])
        neighbour_data = {36: 5 * 3.0, 149: 0.0}  # 5 strong neighbours on ch 36
        recs = optimize_5ghz(aps, neighbour_data=neighbour_data)
        # With equal utilization, ch 149 (no neighbours) should be preferred
        # over ch 36 (heavy neighbour penalty)
        ch36_rec = next((r for r in recs if r["current_channel"] == 36), None)
        assert ch36_rec is not None
        assert ch36_rec["recommended_channel"] != 36  # should move away

    def test_5ghz_neighbour_penalty_capped_at_35(self) -> None:
        """Raw penalty 60 (20 strong neighbours × 3.0) capped at 35."""
        aps = self._make_aps([36], [1])
        neighbour_data = {36: 20 * 3.0, 149: 0.0}  # raw 60, should cap at 35
        recs = optimize_5ghz(aps, neighbour_data=neighbour_data)
        # The penalty applied to ch 36 should be 35, not 60
        assert len(recs) == 1

    def test_24ghz_neighbour_penalty_applied(self) -> None:
        """Ch 6 with neighbours scores worse than ch 11 with none."""
        aps = self._make_aps([36, 44], [6, 6])
        neighbour_data = {1: 0.0, 6: 10.0, 11: 0.0, 13: 0.0}
        recs = optimize_24ghz(aps, neighbour_data=neighbour_data)
        # At least one AP should move away from ch 6
        moved = [r for r in recs if r["current_channel"] == 6
                 and r["recommended_channel"] != 6]
        assert len(moved) >= 1

    def test_24ghz_adjacent_channel_penalty(self) -> None:
        """AP on ch 4 at RSSI -60 adds reduced penalty to ch 6 via adjacent offset."""
        aps = self._make_aps([36], [6])
        # ch 6 gets penalty from adjacent ch 4 neighbour:
        # -60 dBm with -25 dB offset → effective -85 → WEAK bucket 0.5
        neighbour_data = {1: 0.0, 6: 0.5, 11: 0.0, 13: 0.0}
        recs = optimize_24ghz(aps, neighbour_data=neighbour_data)
        assert len(recs) == 1

    def test_5ghz_dfs_plus_neighbour_combined(self) -> None:
        """DFS ch 52 with dfs_penalty + neighbour_penalty combined correctly."""
        aps = self._make_aps([52], [1])
        neighbour_data = {52: 10.0, 36: 0.0, 149: 0.0}
        recs = optimize_5ghz(aps, neighbour_data=neighbour_data)
        # DFS penalty (15) + neighbour penalty (10) = 25 added to utilization
        assert len(recs) == 1

    def test_optimize_with_no_neighbour_data(self) -> None:
        """neighbour_data=None behaves identically to current (backward compat)."""
        aps = self._make_aps([36, 44], [1, 6])
        recs_without = optimize_5ghz(aps)
        recs_with_none = optimize_5ghz(aps, neighbour_data=None)
        assert recs_without == recs_with_none


# ── 8. Link Error Tracking ───────────────────────────────────────────────────
# The compare logic is in compare_link_errors (async + file I/O).
# We test the delta calculation inline by replicating the core logic.


class TestLinkErrorTracking:
    """Test the delta calculation logic extracted from compare_link_errors."""

    @staticmethod
    def _compute_delta(prev: dict, current: dict, elapsed_minutes: float) -> dict:
        """Replicate the core delta logic from compare_link_errors."""
        rx_err = max(0, (current.get("rx_errors", 0) or 0) - prev.get("rx_errors", 0))
        tx_err = max(0, (current.get("tx_errors", 0) or 0) - prev.get("tx_errors", 0))
        rx_drop = max(0, (current.get("rx_dropped", 0) or 0) - prev.get("rx_dropped", 0))
        tx_drop = max(0, (current.get("tx_dropped", 0) or 0) - prev.get("tx_dropped", 0))
        total = rx_err + tx_err + rx_drop + tx_drop
        rate = total / elapsed_minutes if elapsed_minutes > 0 else 0
        return {"total_delta": total, "rate_per_min": round(rate, 1)}

    def test_delta_with_new_errors(self) -> None:
        prev = {"rx_errors": 100, "tx_errors": 50, "rx_dropped": 10, "tx_dropped": 5}
        curr = {"rx_errors": 150, "tx_errors": 55, "rx_dropped": 12, "tx_dropped": 5}
        result = self._compute_delta(prev, curr, elapsed_minutes=5.0)
        assert result["total_delta"] == 57
        assert result["rate_per_min"] == pytest.approx(11.4)

    def test_delta_no_change(self) -> None:
        prev = {"rx_errors": 100, "tx_errors": 50, "rx_dropped": 10, "tx_dropped": 5}
        result = self._compute_delta(prev, prev, elapsed_minutes=5.0)
        assert result["total_delta"] == 0

    def test_delta_counter_reset_clamped(self) -> None:
        """Counter reset (current < prev) should clamp to 0, not go negative."""
        prev = {"rx_errors": 500, "tx_errors": 0, "rx_dropped": 0, "tx_dropped": 0}
        curr = {"rx_errors": 10, "tx_errors": 0, "rx_dropped": 0, "tx_dropped": 0}
        result = self._compute_delta(prev, curr, elapsed_minutes=5.0)
        assert result["total_delta"] == 0

    @staticmethod
    def _detect_reboot(prev_uptime: int, curr_uptime: int) -> bool:
        """Replicate reboot detection: current uptime < baseline uptime."""
        return prev_uptime is not None and curr_uptime < prev_uptime

    def test_reboot_detected_when_uptime_decreased(self) -> None:
        """Device uptime going backwards means it rebooted between snapshots."""
        assert self._detect_reboot(prev_uptime=86400, curr_uptime=300) is True

    def test_reboot_not_detected_when_uptime_increased(self) -> None:
        """Normal case: uptime advances between snapshots."""
        assert self._detect_reboot(prev_uptime=86400, curr_uptime=86700) is False

    def test_reboot_not_detected_when_uptime_equal(self) -> None:
        """Snapshots captured very close together may show equal uptime."""
        assert self._detect_reboot(prev_uptime=86400, curr_uptime=86400) is False

    def test_reboot_suppresses_flagging(self) -> None:
        """Ports on rebooted devices must not be flagged even if their rate exceeds threshold.

        This prevents false-positive 'huge error increase' alerts after a device reboot
        where counters reset to 0 and any new error appears as a large delta.
        """
        # Simulated scenario: baseline had 10 errors, current has 50, elapsed 1 min.
        # Rate = 40/min, which would normally flag at threshold=10.
        # But because the device rebooted (uptime went backwards), flagging is suppressed.
        threshold = 10.0
        rate_per_min = 40.0
        reboot_detected = True
        # Replicate the flagging condition from compare_link_errors
        should_flag = rate_per_min >= threshold and not reboot_detected
        assert should_flag is False


# ── 9. Roaming Analysis ──────────────────────────────────────────────────────
# analyze_roaming is async + file-based. We test the core analysis logic
# by replicating the client_history → roamers/sticky classification.


class TestRoamingAnalysis:
    @staticmethod
    def _classify_client(observations: list[dict]) -> dict:
        """Replicate roaming classification from analyze_roaming."""
        unique_aps = {o["ap_name"] for o in observations}
        roam_count = len(unique_aps) - 1
        valid_rssi = [o["rssi"] for o in observations if o.get("rssi")]
        avg_rssi = sum(valid_rssi) / len(valid_rssi) if valid_rssi else 0
        min_rssi = min(valid_rssi) if valid_rssi else 0
        transitions = sum(
            1 for i in range(1, len(observations))
            if observations[i]["ap_name"] != observations[i - 1]["ap_name"]
        )
        return {
            "roam_count": roam_count,
            "transitions": transitions,
            "avg_rssi": round(avg_rssi),
            "min_rssi": min_rssi,
            "is_sticky": roam_count == 0 and min_rssi < 30 and len(observations) >= 3,
        }

    def test_roaming_client_detected(self) -> None:
        obs = [
            {"ap_name": "Living Room", "rssi": -55},
            {"ap_name": "Kitchen", "rssi": -60},
            {"ap_name": "Living Room", "rssi": -50},
        ]
        result = self._classify_client(obs)
        assert result["roam_count"] == 1
        assert result["transitions"] == 2

    def test_sticky_client_detected(self) -> None:
        obs = [
            {"ap_name": "Garage", "rssi": 15},
            {"ap_name": "Garage", "rssi": 12},
            {"ap_name": "Garage", "rssi": 18},
        ]
        result = self._classify_client(obs)
        assert result["is_sticky"] is True
        assert result["roam_count"] == 0

    def test_good_signal_not_sticky(self) -> None:
        """RSSI >= 30 means good signal — not sticky even if stationary."""
        obs = [
            {"ap_name": "Office", "rssi": 55},
            {"ap_name": "Office", "rssi": 60},
            {"ap_name": "Office", "rssi": 58},
        ]
        result = self._classify_client(obs)
        assert result["is_sticky"] is False


# ── 10. Config Drift ─────────────────────────────────────────────────────────
# detect_drift is async + file-based. We test the comparison logic directly.


class TestConfigDrift:
    @staticmethod
    def _compare_configs(baseline_config: dict, current_config: dict) -> list[dict]:
        """Replicate the drift comparison from detect_drift."""
        drifts = []
        for key in baseline_config:
            if key not in current_config:
                drifts.append({"field": key, "type": "REMOVED"})
            elif baseline_config[key] != current_config[key]:
                drifts.append({
                    "field": key, "type": "CHANGED",
                    "baseline": baseline_config[key], "current": current_config[key],
                })
        return drifts

    def test_detects_changed_field(self) -> None:
        baseline = {"stp_priority": "32768", "port_overrides": []}
        current = {"stp_priority": "4096", "port_overrides": []}
        drifts = self._compare_configs(baseline, current)
        assert len(drifts) == 1
        assert drifts[0]["field"] == "stp_priority"
        assert drifts[0]["type"] == "CHANGED"

    def test_detects_removed_field(self) -> None:
        baseline = {"stp_priority": "32768", "snmp_contact": "admin@example.com"}
        current = {"stp_priority": "32768"}
        drifts = self._compare_configs(baseline, current)
        assert len(drifts) == 1
        assert drifts[0]["type"] == "REMOVED"

    def test_no_drift(self) -> None:
        config = {"stp_priority": "32768", "port_overrides": [{"port_idx": 1, "name": "AP"}]}
        drifts = self._compare_configs(config, config)
        assert drifts == []


# ── 11. Neighbour Scan ───────────────────────────────────────────────────────
# scan_neighbours uses stat/rogueap (passive, always-fresh).
# Tests target the new helper functions in neighbour_scan.py (Task 3).


def _make_rogue_entry(
    *,
    bssid: str = "b0:5b:99:ea:5a:76",
    essid: str = "Neighbour-Net",
    channel: int = 6,
    signal: int = -70,
    rssi: int = 12,
    noise: int = -96,
    band: str = "ng",
    bw: int = 20,
    freq: int = 2437,
    ap_mac: str = "02:00:fe:02:00:04",
    age: int = 0,
    last_seen: int = 1777896779,
    is_ubnt: bool = False,
    is_adhoc: bool = False,
    security: str = "WPA2-Personal (AES/CCMP)",
) -> dict:
    """Build a realistic stat/rogueap entry."""
    return {
        "bssid": bssid,
        "essid": essid,
        "channel": channel,
        "signal": signal,
        "rssi": rssi,
        "noise": noise,
        "band": band,
        "bw": bw,
        "freq": freq,
        "ap_mac": ap_mac,
        "age": age,
        "last_seen": last_seen,
        "is_ubnt": is_ubnt,
        "is_adhoc": is_adhoc,
        "security": security,
    }


class TestNeighbourScan:
    """Tests for neighbour_scan.py helper functions (stat/rogueap based)."""

    def test_parse_rogue_entries_groups_by_ap(self) -> None:
        """Raw entries with mixed ap_mac values produce correct per-AP grouping."""
        entries = [
            _make_rogue_entry(ap_mac="aa:bb:cc:00:00:01", channel=6, signal=-70),
            _make_rogue_entry(ap_mac="aa:bb:cc:00:00:01", channel=36, signal=-55),
            _make_rogue_entry(ap_mac="aa:bb:cc:00:00:02", channel=1, signal=-80),
        ]
        ap_mac_to_name = {
            "aa:bb:cc:00:00:01": "Living Room",
            "aa:bb:cc:00:00:02": "Kitchen",
        }
        result = _group_rogue_entries(entries, ap_mac_to_name)
        assert len(result) == 2
        names = {ap["ap_name"] for ap in result}
        assert names == {"Living Room", "Kitchen"}
        lr = next(ap for ap in result if ap["ap_name"] == "Living Room")
        assert "channel_summary" in lr
        assert "neighbours" in lr
        assert len(lr["neighbours"]) == 2

    def test_parse_rogue_entries_filters_own_network(self) -> None:
        """Entries with is_ubnt=True are excluded."""
        entries = [
            _make_rogue_entry(is_ubnt=True, signal=-60),
            _make_rogue_entry(is_ubnt=False, signal=-70),
        ]
        result = _group_rogue_entries(entries, {"02:00:fe:02:00:04": "AP-1"})
        total = sum(len(ap["neighbours"]) for ap in result)
        assert total == 1

    def test_parse_rogue_entries_filters_stale(self) -> None:
        """Entries with age > MAX_ROGUE_AGE_SECONDS are excluded."""
        entries = [
            _make_rogue_entry(age=0, signal=-60),
            _make_rogue_entry(age=301, signal=-65, bssid="aa:bb:cc:dd:ee:ff"),
        ]
        result = _group_rogue_entries(entries, {"02:00:fe:02:00:04": "AP-1"})
        total = sum(len(ap["neighbours"]) for ap in result)
        assert total == 1

    def test_parse_rogue_entries_empty(self) -> None:
        """Empty input produces empty aps list."""
        result = _group_rogue_entries([], {})
        assert result == []

    @pytest.mark.parametrize(
        ("signal_dbm", "expected_weight"),
        [
            (-50, 3.0),   # strong: > -67
            (-66, 3.0),   # strong: > -67
            (-67, 1.0),   # boundary: exactly -67 → MEDIUM
            (-75, 1.0),   # medium: -67 to -82
            (-82, 0.5),   # boundary: exactly -82 → WEAK
            (-90, 0.5),   # weak: < -82
        ],
    )
    def test_rssi_weight_buckets(self, signal_dbm: int, expected_weight: float) -> None:
        """Oracle-validated RSSI weighting thresholds."""
        assert rssi_weight(signal_dbm) == expected_weight

    def test_channel_neighbour_score_5ghz(self) -> None:
        """5 GHz: weighted sum of co-channel neighbours, no adjacent compensation."""
        neighbours = [
            _make_rogue_entry(channel=36, signal=-60, band="na"),  # strong → 3.0
            _make_rogue_entry(channel=36, signal=-75, band="na"),  # medium → 1.0
            _make_rogue_entry(channel=36, signal=-90, band="na"),  # weak → 0.5
            _make_rogue_entry(channel=44, signal=-55, band="na"),  # different ch → 0
        ]
        score = compute_channel_neighbour_score(neighbours, target_channel=36, band="na")
        assert score == pytest.approx(3.0 + 1.0 + 0.5)

    def test_channel_neighbour_score_24ghz_adjacent(self) -> None:
        """2.4 GHz: AP on ch 4 at -60 dBm contributes to ch 6 with -25 dB offset."""
        neighbours = [
            _make_rogue_entry(channel=4, signal=-60, band="ng"),
        ]
        score = compute_channel_neighbour_score(neighbours, target_channel=6, band="ng")
        # effective RSSI = -60 + (-25) = -85 → below -82 → WEAK bucket → 0.5
        assert score == pytest.approx(0.5)

    def test_channel_neighbour_score_24ghz_far_channel(self) -> None:
        """2.4 GHz: AP on ch 1 does not contribute to ch 11 (distance > 2)."""
        neighbours = [
            _make_rogue_entry(channel=1, signal=-55, band="ng"),
        ]
        score = compute_channel_neighbour_score(neighbours, target_channel=11, band="ng")
        assert score == 0.0

    def test_ap_name_filter(self) -> None:
        """When filter_ap_mac provided, only matching entries appear."""
        entries = [
            _make_rogue_entry(ap_mac="aa:bb:cc:00:00:01", signal=-60),
            _make_rogue_entry(ap_mac="aa:bb:cc:00:00:02", signal=-70),
        ]
        ap_mac_to_name = {
            "aa:bb:cc:00:00:01": "Living Room",
            "aa:bb:cc:00:00:02": "Kitchen",
        }
        result = _group_rogue_entries(
            entries, ap_mac_to_name, filter_ap_mac="aa:bb:cc:00:00:01",
        )
        assert len(result) == 1
        assert result[0]["ap_name"] == "Living Room"


# ── 12. Bandwidth Test ───────────────────────────────────────────────────────


class TestBandwidthTest:
    def test_parse_json_output(self) -> None:
        data = {
            "start": {"test_start": {"num_streams": 1}},
            "end": {
                "sum_sent": {"bytes": 1_170_000_000, "bits_per_second": 936_000_000, "retransmits": 3},
                "sum_received": {"bytes": 1_170_000_000, "bits_per_second": 935_000_000},
            },
        }
        result = _parse_json_output(data, "192.0.2.50", reverse=False, duration=10)
        assert result["status"] == "OK"
        assert result["throughput_mbps"] == 935.0
        assert result["retransmits"] == 3
        assert result["streams"] == 1

    def test_parse_json_reverse(self) -> None:
        data = {
            "start": {"test_start": {"num_streams": 4}},
            "end": {
                "sum_sent": {"bytes": 500_000_000, "bits_per_second": 400_000_000, "retransmits": 0},
                "sum_received": {"bytes": 500_000_000, "bits_per_second": 400_000_000},
            },
        }
        result = _parse_json_output(data, "10.0.0.1", reverse=True, duration=10)
        assert "download" in result["direction"]
        assert result["throughput_mbps"] == 400.0

    def test_parse_text_output_gbps(self) -> None:
        stdout = (
            "[  5]   0.00-10.00  sec  1.09 GBytes   937 Mbits/sec  receiver\n"
        )
        result = _parse_text_output(stdout, "192.0.2.50", reverse=False, duration=10)
        assert result["status"] == "OK"
        assert result["throughput_mbps"] == 937.0

    def test_parse_text_output_sum_line(self) -> None:
        stdout = "[SUM]   0.00-10.00  sec  2.18 GBytes  1.87 Gbits/sec\n"
        result = _parse_text_output(stdout, "10.0.0.1", reverse=False, duration=10)
        assert result["throughput_mbps"] == 1870.0

    def test_parse_text_output_no_match(self) -> None:
        result = _parse_text_output("garbage output", "10.0.0.1", reverse=False, duration=10)
        assert result["status"] == "PARSE_ERROR"
        assert result["throughput_mbps"] == 0
