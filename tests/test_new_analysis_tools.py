"""Tests for the 12 new analysis modules — pure functions only, no API calls."""

from __future__ import annotations

import pytest

from unifi_mapper.analysis.dhcp_pool import _analyze_dhcp_pools
from unifi_mapper.analysis.poe_budget import _analyze_poe_budgets
from unifi_mapper.analysis.client_density import _analyze_density
from unifi_mapper.analysis.uplink_redundancy import _analyze_uplink_redundancy
from unifi_mapper.analysis.latency_matrix import _build_target_list, _parse_ping_output
from unifi_mapper.analysis.radio_config import build_optimisation_plan
from unifi_mapper.analysis.channel_optimiser import optimize_5ghz, optimize_24ghz
from unifi_mapper.analysis.bandwidth_test import _parse_json_output, _parse_text_output


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
# scan_neighbours is async + triggers RF scans. We test the result parsing logic.


class TestNeighbourScan:
    @staticmethod
    def _parse_scan_table(scan_table: list[dict]) -> dict:
        """Replicate neighbour parsing from scan_neighbours."""
        neighbours = []
        channel_summary: dict[int, int] = {}
        for entry in scan_table:
            ch = entry.get("channel", 0)
            channel_summary[ch] = channel_summary.get(ch, 0) + 1
            neighbours.append({
                "bssid": entry.get("bssid", ""),
                "ssid": entry.get("essid", "<hidden>"),
                "channel": ch,
                "rssi": entry.get("rssi", 0),
            })
        neighbours.sort(key=lambda x: -(x.get("rssi") or -100))
        return {"total": len(neighbours), "channel_summary": channel_summary,
                "strongest": neighbours[:10]}

    def test_parses_neighbours(self) -> None:
        scan_table = [
            {"bssid": "00:11:22:33:44:55", "essid": "Neighbor-5G", "channel": 36, "rssi": -65},
            {"bssid": "00:11:22:33:44:66", "essid": "Neighbor-2G", "channel": 6, "rssi": -72},
            {"bssid": "00:11:22:33:44:77", "essid": "", "channel": 36, "rssi": -80},
        ]
        result = self._parse_scan_table(scan_table)
        assert result["total"] == 3
        assert result["channel_summary"] == {36: 2, 6: 1}
        assert result["strongest"][0]["rssi"] == -65

    def test_empty_scan(self) -> None:
        result = self._parse_scan_table([])
        assert result["total"] == 0
        assert result["channel_summary"] == {}

    def test_hidden_ssid(self) -> None:
        scan_table = [{"bssid": "ff:ff:ff:ff:ff:ff", "channel": 1, "rssi": -90}]
        result = self._parse_scan_table(scan_table)
        assert result["strongest"][0]["ssid"] == "<hidden>"


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
