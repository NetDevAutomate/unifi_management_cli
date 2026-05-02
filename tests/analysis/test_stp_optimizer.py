"""Tests for STP optimizer module."""

from __future__ import annotations

from unifi_mapper.analysis.stp_optimizer import (
    _calculate_hierarchy_tiers,
    _parse_stp_role,
    _parse_stp_state,
    _render_stp_diagram,
    calculate_optimal_priorities,
    format_stp_report_markdown,
)
from unifi_mapper.core.models.capability import SwitchCapabilityClass
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
from unifi_mapper.core.utils.overrides import STPOverrides


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
            capability=SwitchCapabilityClass.AGGREGATION,
            root_eligible=True,
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
            capability=SwitchCapabilityClass.AGGREGATION,
            root_eligible=True,
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='dist1'),
            ],
        )
        dist = SwitchSTPConfig(
            device_id='dist1',
            name='Distribution',
            mac='00:00:00:00:00:02',
            capability=SwitchCapabilityClass.ACCESS_POE,
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
            capability=SwitchCapabilityClass.AGGREGATION,
            root_eligible=True,
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='dist1'),
            ],
        )
        dist = SwitchSTPConfig(
            device_id='dist1',
            name='Distribution',
            mac='00:00:00:00:00:02',
            capability=SwitchCapabilityClass.ACCESS_POE,
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='core1'),
                STPPortConfig(port_idx=2, connected_device_id='access1'),
            ],
        )
        access = SwitchSTPConfig(
            device_id='access1',
            name='Access',
            mac='00:00:00:00:00:03',
            capability=SwitchCapabilityClass.ACCESS_POE,
            port_states=[
                STPPortConfig(port_idx=1, connected_device_id='dist1'),
            ],
        )
        switches = [core, dist, access]
        _calculate_hierarchy_tiers(switches)
        assert core.hierarchy_tier == 0
        assert dist.hierarchy_tier == 1
        assert access.hierarchy_tier == 2


class TestCapabilityAwareTiering:
    """Tests for capability-aware hierarchy + root guard (Phase 0 fix)."""

    def _make_switch(
        self,
        device_id: str,
        name: str,
        mac: str,
        capability: SwitchCapabilityClass,
        *,
        connected_to_gateway: bool = False,
        root_eligible: bool | None = None,
        connected_device_ids: tuple[str, ...] = (),
    ) -> SwitchSTPConfig:
        if root_eligible is None:
            root_eligible = capability in (
                SwitchCapabilityClass.AGGREGATION,
                SwitchCapabilityClass.CORE_DISTRIBUTION,
            )
        return SwitchSTPConfig(
            device_id=device_id,
            name=name,
            mac=mac,
            capability=capability,
            connected_to_gateway=connected_to_gateway,
            root_eligible=root_eligible,
            port_states=[
                STPPortConfig(port_idx=i, connected_device_id=peer)
                for i, peer in enumerate(connected_device_ids, start=1)
            ],
        )

    def test_access_class_gateway_neighbor_is_not_core(self) -> None:
        """Access switch cabled to gateway must be Tier 1, not Tier 0."""
        agg = self._make_switch(
            'agg1',
            'Xray3 USW Flex XG',
            '02:00:fe:02:00:09',
            SwitchCapabilityClass.AGGREGATION,
            connected_to_gateway=True,
        )
        access = self._make_switch(
            'access1',
            'Xray3 USW-Lite-16-PoE',
            '02:00:fe:02:00:13',
            SwitchCapabilityClass.ACCESS_POE,
            connected_to_gateway=True,
        )

        _calculate_hierarchy_tiers([agg, access])

        assert agg.hierarchy_tier == 0
        assert access.hierarchy_tier == 1
        assert (
            'not root-eligible' in access.tier_reason.lower()
            or 'distribution' in access.tier_reason.lower()
        )

    def test_multiple_aggregation_gateway_neighbors_share_tier_0(self) -> None:
        """Two AGGREGATION switches on the gateway both land in Tier 0."""
        agg1 = self._make_switch(
            'agg1',
            'Xray3 USW Flex XG',
            '02:00:fe:02:00:09',
            SwitchCapabilityClass.AGGREGATION,
            connected_to_gateway=True,
        )
        agg2 = self._make_switch(
            'agg2',
            'Mike2 10G Aggregation USW Flex XG',
            '78:45:58:62:f1:4a',
            SwitchCapabilityClass.AGGREGATION,
            connected_to_gateway=True,
        )
        _calculate_hierarchy_tiers([agg1, agg2])
        assert agg1.hierarchy_tier == 0
        assert agg2.hierarchy_tier == 0

    def test_override_force_access_demotes_gateway_neighbor(self) -> None:
        """force_access override demotes a gateway-connected AGGREGATION to Tier 1."""
        agg = self._make_switch(
            'agg1',
            'Xray3 USW Flex XG',
            '02:00:fe:02:00:09',
            SwitchCapabilityClass.AGGREGATION,
            connected_to_gateway=True,
        )
        # Would normally be Tier 0, but is forced to Access by override.
        overrides = STPOverrides(
            force_access_macs=frozenset({'0200fe020009'}),
        )
        _calculate_hierarchy_tiers([agg], overrides=overrides)
        assert agg.hierarchy_tier == 1
        assert 'force_access' in agg.tier_reason

    async def test_root_guard_refuses_priority_4096_for_access_class(self) -> None:
        """Even if access switch reached Tier 0 somehow, priority stays >= 8192."""
        bad = self._make_switch(
            'x',
            'Rogue Access',
            'aa:bb:cc:dd:ee:ff',
            SwitchCapabilityClass.ACCESS_POE,
        )
        bad.hierarchy_tier = 0  # contrived
        topology = STPTopology(switches=[bad])

        changes = await calculate_optimal_priorities(topology)

        # Switch's optimal_priority must be >= distribution floor
        assert bad.optimal_priority is not None
        assert bad.optimal_priority >= 8192
        # And change reason must mention the guard
        for change in changes:
            if change.device_id == 'x':
                assert 'root-guard' in change.reason.lower()
                assert change.new_priority >= 8192

    async def test_aggregation_tier_0_gets_4096(self) -> None:
        """AGGREGATION at Tier 0 receives priority 4096 from optimiser."""
        agg = self._make_switch(
            'agg1',
            'Xray3 USW Flex XG',
            '02:00:fe:02:00:09',
            SwitchCapabilityClass.AGGREGATION,
            connected_to_gateway=True,
        )
        agg.hierarchy_tier = 0
        agg.current_priority = 8192
        topology = STPTopology(switches=[agg])

        changes = await calculate_optimal_priorities(topology)

        assert agg.optimal_priority == 4096
        assert any(c.device_id == 'agg1' and c.new_priority == 4096 for c in changes)


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
            device_id='sw1',
            name='SW1',
            mac='00:00:00:00:00:01',
            hierarchy_tier=0,
        )
        sw2 = SwitchSTPConfig(
            device_id='sw2',
            name='SW2',
            mac='00:00:00:00:00:02',
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
