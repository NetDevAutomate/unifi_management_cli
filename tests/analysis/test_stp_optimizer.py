"""Tests for STP optimizer module."""

from __future__ import annotations

import pytest

from unifi_mapper.core.models.stp import (
    STP_PRIORITY_ACCESS_BASE,
    STP_PRIORITY_CORE,
    STP_PRIORITY_DEFAULT,
    STP_PRIORITY_DISTRIBUTION,
    STPChange,
    STPConnection,
    STPOptimizationReport,
    STPPortConfig,
    STPPortState,
    STPRole,
    STPTopology,
    SwitchSTPConfig,
)
from unifi_mapper.analysis.stp_optimizer import (
    _parse_stp_state,
    _parse_stp_role,
    _calculate_hierarchy_tiers,
    _render_stp_diagram,
    format_stp_report_markdown,
)


class TestSTPModels:
    """Tests for STP Pydantic models."""

    def test_stp_port_state_enum(self) -> None:
        """Test STPPortState enum values."""
        assert STPPortState.FORWARDING.value == 'forwarding'
        assert STPPortState.BLOCKING.value == 'blocking'
        assert STPPortState.DISCARDING.value == 'discarding'
        assert STPPortState.LEARNING.value == 'learning'
        assert STPPortState.LISTENING.value == 'listening'
        assert STPPortState.DISABLED.value == 'disabled'

    def test_stp_role_enum(self) -> None:
        """Test STPRole enum values."""
        assert STPRole.ROOT.value == 'root'
        assert STPRole.DESIGNATED.value == 'designated'
        assert STPRole.ALTERNATE.value == 'alternate'
        assert STPRole.BACKUP.value == 'backup'
        assert STPRole.DISABLED.value == 'disabled'

    def test_stp_port_config_creation(self) -> None:
        """Test STPPortConfig model creation."""
        port = STPPortConfig(
            port_idx=1,
            port_name='Port 1',
            stp_state=STPPortState.FORWARDING,
            stp_role=STPRole.DESIGNATED,
            path_cost=19,
            connected_device='Switch-2',
        )
        assert port.port_idx == 1
        assert port.port_name == 'Port 1'
        assert port.stp_state == STPPortState.FORWARDING
        assert port.stp_role == STPRole.DESIGNATED
        assert port.path_cost == 19
        assert port.connected_device == 'Switch-2'

    def test_stp_port_config_defaults(self) -> None:
        """Test STPPortConfig default values."""
        port = STPPortConfig(port_idx=1)
        assert port.port_name == ''
        assert port.stp_state == STPPortState.FORWARDING
        assert port.stp_role == STPRole.DESIGNATED
        assert port.path_cost == 0
        assert port.connected_device is None
        assert port.is_uplink is False

    def test_switch_stp_config_creation(self) -> None:
        """Test SwitchSTPConfig model creation."""
        switch = SwitchSTPConfig(
            device_id='abc123',
            name='Core-Switch',
            mac='00:11:22:33:44:55',
            model='USW-Pro-48-PoE',
            current_priority=4096,
            hierarchy_tier=0,
            is_root_bridge=True,
            connected_to_gateway=True,
        )
        assert switch.device_id == 'abc123'
        assert switch.name == 'Core-Switch'
        assert switch.mac == '00:11:22:33:44:55'
        assert switch.model == 'USW-Pro-48-PoE'
        assert switch.current_priority == 4096
        assert switch.hierarchy_tier == 0
        assert switch.is_root_bridge is True
        assert switch.connected_to_gateway is True

    def test_switch_stp_config_defaults(self) -> None:
        """Test SwitchSTPConfig default values."""
        switch = SwitchSTPConfig(
            device_id='test',
            name='Test',
            mac='00:00:00:00:00:00',
        )
        assert switch.current_priority == STP_PRIORITY_DEFAULT
        assert switch.optimal_priority is None
        assert switch.hierarchy_tier == 2
        assert switch.is_root_bridge is False
        assert switch.port_states == []
        assert switch.uplink_ports == []
        assert switch.connected_to_gateway is False

    def test_stp_connection_creation(self) -> None:
        """Test STPConnection model creation."""
        conn = STPConnection(
            from_device_id='switch1',
            from_device_name='Switch-1',
            from_port_idx=24,
            to_device_id='switch2',
            to_device_name='Switch-2',
            stp_state=STPPortState.BLOCKING,
            is_blocked=True,
        )
        assert conn.from_device_id == 'switch1'
        assert conn.from_device_name == 'Switch-1'
        assert conn.from_port_idx == 24
        assert conn.to_device_id == 'switch2'
        assert conn.is_blocked is True
        assert conn.stp_state == STPPortState.BLOCKING

    def test_stp_topology_creation(self) -> None:
        """Test STPTopology model creation."""
        topology = STPTopology(
            root_bridge_id='switch1',
            root_bridge_name='Core-Switch',
            root_bridge_priority=4096,
            gateway_id='gateway1',
            gateway_name='UDM-Pro',
            switches=[],
            connections=[],
            loops_detected=False,
            blocked_ports_count=0,
        )
        assert topology.root_bridge_id == 'switch1'
        assert topology.root_bridge_name == 'Core-Switch'
        assert topology.root_bridge_priority == 4096
        assert topology.loops_detected is False

    def test_stp_change_creation(self) -> None:
        """Test STPChange model creation."""
        change = STPChange(
            device_id='switch1',
            device_name='Access-Switch',
            current_priority=32768,
            new_priority=16384,
            hierarchy_tier=2,
            reason='Access switch should have priority 16384',
        )
        assert change.device_id == 'switch1'
        assert change.current_priority == 32768
        assert change.new_priority == 16384
        assert change.hierarchy_tier == 2

    def test_stp_optimization_report_creation(self) -> None:
        """Test STPOptimizationReport model creation."""
        topology = STPTopology()
        report = STPOptimizationReport(
            switches_analyzed=3,
            current_root='Switch-1',
            current_root_priority=32768,
            optimal_root='Switch-2',
            changes_required=2,
            changes=[],
            topology=topology,
        )
        assert report.switches_analyzed == 3
        assert report.current_root == 'Switch-1'
        assert report.changes_required == 2


class TestSTPPriorityConstants:
    """Tests for STP priority constants."""

    def test_priority_values(self) -> None:
        """Test standard STP priority values."""
        assert STP_PRIORITY_CORE == 4096
        assert STP_PRIORITY_DISTRIBUTION == 8192
        assert STP_PRIORITY_ACCESS_BASE == 16384
        assert STP_PRIORITY_DEFAULT == 32768

    def test_priority_ordering(self) -> None:
        """Test that priorities are correctly ordered (lower = better)."""
        assert STP_PRIORITY_CORE < STP_PRIORITY_DISTRIBUTION
        assert STP_PRIORITY_DISTRIBUTION < STP_PRIORITY_ACCESS_BASE
        assert STP_PRIORITY_ACCESS_BASE < STP_PRIORITY_DEFAULT


class TestSTPStateParsing:
    """Tests for STP state parsing functions."""

    def test_parse_stp_state_valid(self) -> None:
        """Test parsing valid STP state strings."""
        assert _parse_stp_state('forwarding') == STPPortState.FORWARDING
        assert _parse_stp_state('blocking') == STPPortState.BLOCKING
        assert _parse_stp_state('discarding') == STPPortState.DISCARDING
        assert _parse_stp_state('learning') == STPPortState.LEARNING
        assert _parse_stp_state('listening') == STPPortState.LISTENING
        assert _parse_stp_state('disabled') == STPPortState.DISABLED

    def test_parse_stp_state_case_insensitive(self) -> None:
        """Test case insensitive parsing."""
        assert _parse_stp_state('FORWARDING') == STPPortState.FORWARDING
        assert _parse_stp_state('Blocking') == STPPortState.BLOCKING

    def test_parse_stp_state_unknown(self) -> None:
        """Test parsing unknown state defaults to forwarding."""
        assert _parse_stp_state('unknown') == STPPortState.FORWARDING
        assert _parse_stp_state('') == STPPortState.FORWARDING

    def test_parse_stp_role_valid(self) -> None:
        """Test parsing valid STP role strings."""
        assert _parse_stp_role('root') == STPRole.ROOT
        assert _parse_stp_role('designated') == STPRole.DESIGNATED
        assert _parse_stp_role('alternate') == STPRole.ALTERNATE
        assert _parse_stp_role('backup') == STPRole.BACKUP
        assert _parse_stp_role('disabled') == STPRole.DISABLED

    def test_parse_stp_role_unknown(self) -> None:
        """Test parsing unknown role defaults to designated."""
        assert _parse_stp_role('unknown') == STPRole.DESIGNATED
        assert _parse_stp_role('') == STPRole.DESIGNATED


class TestHierarchyTierCalculation:
    """Tests for hierarchy tier calculation."""

    def test_calculate_tiers_core_switch(self) -> None:
        """Test core switch tier assignment."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            connected_to_gateway=True,
        )
        switches = [core]
        _calculate_hierarchy_tiers(switches)
        assert core.hierarchy_tier == 0

    def test_calculate_tiers_distribution_switch(self) -> None:
        """Test distribution switch tier assignment."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            connected_to_gateway=True,
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='dist1'),
            ],
        )
        dist = SwitchSTPConfig(
            device_id='dist1',
            name='Distribution',
            mac='00:00:00:00:00:02',
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='core1'),
            ],
        )
        switches = [core, dist]
        _calculate_hierarchy_tiers(switches)
        assert core.hierarchy_tier == 0
        assert dist.hierarchy_tier == 1

    def test_calculate_tiers_access_switch(self) -> None:
        """Test access switch tier assignment."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            connected_to_gateway=True,
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='dist1'),
            ],
        )
        dist = SwitchSTPConfig(
            device_id='dist1',
            name='Distribution',
            mac='00:00:00:00:00:02',
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='core1'),
                STPPortConfig(port_idx=2, connected_device_id='access1'),
            ],
        )
        access = SwitchSTPConfig(
            device_id='access1',
            name='Access',
            mac='00:00:00:00:00:03',
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='dist1'),
            ],
        )
        switches = [core, dist, access]
        _calculate_hierarchy_tiers(switches)
        assert core.hierarchy_tier == 0
        assert dist.hierarchy_tier == 1
        assert access.hierarchy_tier == 2


class TestSTPDiagramRendering:
    """Tests for STP diagram rendering."""

    def test_render_empty_topology(self) -> None:
        """Test rendering empty topology."""
        topology = STPTopology()
        diagram = _render_stp_diagram(topology, [], show_optimal=False)
        assert '```mermaid' in diagram
        assert 'No STP data' in diagram or 'graph TB' in diagram

    def test_render_single_switch(self) -> None:
        """Test rendering single switch topology."""
        switch = SwitchSTPConfig(
            device_id='switch1',
            name='Core-Switch',
            mac='00:00:00:00:00:01',
            current_priority=4096,
            hierarchy_tier=0,
            is_root_bridge=True,
        )
        topology = STPTopology(
            root_bridge_id='switch1',
            root_bridge_name='Core-Switch',
            switches=[switch],
        )
        diagram = _render_stp_diagram(topology, [], show_optimal=False)
        assert '```mermaid' in diagram
        assert 'Core-Switch' in diagram
        assert '4096' in diagram
        assert '👑' in diagram  # Root bridge crown

    def test_render_blocked_connection(self) -> None:
        """Test rendering blocked STP connection."""
        sw1 = SwitchSTPConfig(
            device_id='sw1', name='SW1', mac='00:00:00:00:00:01',
            hierarchy_tier=0,
        )
        sw2 = SwitchSTPConfig(
            device_id='sw2', name='SW2', mac='00:00:00:00:00:02',
            hierarchy_tier=1,
        )
        conn = STPConnection(
            from_device_id='sw1',
            from_device_name='SW1',
            from_port_idx=1,
            to_device_id='sw2',
            to_device_name='SW2',
            is_blocked=True,
        )
        topology = STPTopology(switches=[sw1, sw2], connections=[conn])
        diagram = _render_stp_diagram(topology, [], show_optimal=False)
        assert 'blocked' in diagram


class TestMarkdownReportFormatting:
    """Tests for markdown report formatting."""

    def test_format_basic_report(self) -> None:
        """Test formatting a basic report."""
        topology = STPTopology(
            root_bridge_id='switch1',
            root_bridge_name='Core-Switch',
            root_bridge_priority=4096,
        )
        report = STPOptimizationReport(
            switches_analyzed=1,
            current_root='Core-Switch',
            current_root_priority=4096,
            optimal_root='Core-Switch',
            changes_required=0,
            changes=[],
            topology=topology,
        )
        markdown = format_stp_report_markdown(report)

        assert '# STP Optimization Report' in markdown
        assert 'Switches Analyzed' in markdown
        assert 'Current Root' in markdown
        assert 'Core-Switch' in markdown

    def test_format_report_with_changes(self) -> None:
        """Test formatting report with changes."""
        topology = STPTopology()
        change = STPChange(
            device_id='sw1',
            device_name='Access-Switch',
            current_priority=32768,
            new_priority=16384,
            hierarchy_tier=2,
            reason='Access switch should have priority 16384',
        )
        report = STPOptimizationReport(
            switches_analyzed=2,
            current_root='Access-Switch',
            current_root_priority=32768,
            optimal_root='Core-Switch',
            changes_required=1,
            changes=[change],
            topology=topology,
        )
        markdown = format_stp_report_markdown(report)

        assert 'Recommended Changes' in markdown
        assert 'Access-Switch' in markdown
        assert '32768' in markdown
        assert '16384' in markdown
        assert '```diff' in markdown

    def test_format_report_with_issues(self) -> None:
        """Test formatting report with issues."""
        topology = STPTopology()
        report = STPOptimizationReport(
            switches_analyzed=1,
            changes_required=0,
            changes=[],
            topology=topology,
            issues=['Root bridge using default priority'],
        )
        markdown = format_stp_report_markdown(report)

        assert 'Issues Detected' in markdown
        assert 'Root bridge using default priority' in markdown

    def test_format_report_contains_priority_table(self) -> None:
        """Test report contains STP priority reference table."""
        topology = STPTopology()
        report = STPOptimizationReport(
            switches_analyzed=1,
            changes_required=0,
            changes=[],
            topology=topology,
        )
        markdown = format_stp_report_markdown(report)

        assert 'STP Priority Standards' in markdown
        assert '4096' in markdown
        assert '8192' in markdown
        assert '16384' in markdown
        assert '32768' in markdown
