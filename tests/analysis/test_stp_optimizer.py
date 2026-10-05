"""Tests for STP optimizer module."""

from __future__ import annotations

from unifi_mapper.analysis.stp_optimizer import (
    _calculate_hierarchy_tiers,
    _extract_port_stp_states,
    _parse_stp_role,
    _parse_stp_state,
    _render_stp_diagram,
    audit_stp_path_costs,
    build_10g_expansion_validation_report,
    calculate_optimal_priorities,
    expected_long_path_cost,
    format_10g_validation_report_markdown,
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
        assert switch.root_eligible is True
        assert switch.root_preference == 100
        assert switch.root_eligibility_reason == ''
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


class TestPortStateExtraction:
    """Tests for extracting STP and health fields from UniFi port tables."""

    def test_extracts_port_counters_with_safe_defaults(self) -> None:
        """Port extraction handles string booleans and missing nested stats."""
        device = {
            'port_table': [
                {
                    'port_idx': 1,
                    'name': 'Port 1',
                    'up': 'true',
                    'enabled': 'false',
                    'speed': '10000',
                    'full_duplex': 'false',
                    'rx_errors': '7',
                    'tx_errors': None,
                    'rx_dropped': '11',
                    'tx_dropped': '13',
                    'port_stats': None,
                }
            ],
            'lldp_table': [
                {
                    'local_port_idx': 1,
                    'chassis_id': '00:00:00:00:00:02',
                }
            ],
        }
        mac_to_device = {
            '000000000002': {
                '_id': 'switch2',
                'name': 'Switch 2',
                'type': 'usw',
            }
        }

        port_states, connections, blocked_count = _extract_port_stp_states(
            device,
            'switch1',
            'Switch 1',
            mac_to_device,
            gateway_mac=None,
        )

        assert blocked_count == 0
        assert len(connections) == 1
        port = port_states[0]
        assert port.is_up is True
        assert port.enabled is False
        assert port.link_speed_mbps == 10000
        assert port.full_duplex is False
        assert port.rx_errors == 7
        assert port.tx_errors == 0
        assert port.rx_dropped == 11
        assert port.tx_dropped == 13
        assert port.crc_errors == 0


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


class TestSTPOptimization:
    """Tests for STP priority optimization."""

    async def test_prefers_gateway_connected_flex_xg_over_lite_as_root(self) -> None:
        """Gateway-connected Flex XG should be preferred over Lite as STP root."""
        lite = SwitchSTPConfig(
            device_id='lite1',
            name='Xray3 USW-Lite-16-PoE',
            mac='00:00:00:00:00:10',
            model='USW-Lite-16-PoE',
            current_priority=STP_PRIORITY_DEFAULT,
            connected_to_gateway=True,
        )
        flex_xg = SwitchSTPConfig(
            device_id='flex1',
            name='Xray3 USW Flex XG 10G',
            mac='00:00:00:00:00:20',
            model='USW-Flex-XG',
            current_priority=STP_PRIORITY_DEFAULT,
            connected_to_gateway=True,
        )
        topology = STPTopology(switches=[lite, flex_xg])
        _calculate_hierarchy_tiers(topology.switches)

        changes = await calculate_optimal_priorities(topology)

        flex_change = next(change for change in changes if change.device_id == 'flex1')
        lite_change = next(change for change in changes if change.device_id == 'lite1')
        assert flex_xg.root_eligible is True
        assert flex_xg.root_preference == 10
        assert flex_change.new_priority == STP_PRIORITY_CORE
        assert lite.root_eligible is False
        assert lite_change.new_priority != STP_PRIORITY_CORE
        assert lite_change.new_priority == STP_PRIORITY_DISTRIBUTION

    async def test_gateway_connected_access_switch_is_not_assigned_root_priority(self) -> None:
        """Access-class switches should not receive priority 4096 just because they touch gateway."""
        flex_mini = SwitchSTPConfig(
            device_id='mini1',
            name='Desk Flex Mini',
            mac='00:00:00:00:00:11',
            model='USW-Flex-Mini',
            current_priority=STP_PRIORITY_DEFAULT,
            connected_to_gateway=True,
        )
        flex_xg = SwitchSTPConfig(
            device_id='flex1',
            name='Xray3 USW Flex XG 10G',
            mac='00:00:00:00:00:20',
            model='USW-Flex-XG',
            current_priority=STP_PRIORITY_DEFAULT,
            connected_to_gateway=True,
        )
        topology = STPTopology(switches=[flex_mini, flex_xg])
        _calculate_hierarchy_tiers(topology.switches)

        changes = await calculate_optimal_priorities(topology)

        mini_change = next(change for change in changes if change.device_id == 'mini1')
        flex_change = next(change for change in changes if change.device_id == 'flex1')
        assert flex_mini.root_eligible is False
        assert flex_change.new_priority == STP_PRIORITY_CORE
        assert mini_change.new_priority == STP_PRIORITY_DISTRIBUTION

    async def test_distribution_priority_sits_below_non_root_gateway_core(self) -> None:
        """Tier 1 switches should not tie with a demoted gateway-connected core."""
        lite = SwitchSTPConfig(
            device_id='lite1',
            name='Xray3 USW-Lite-16-PoE',
            mac='00:00:00:00:00:10',
            model='USW-Lite-16-PoE',
            current_priority=STP_PRIORITY_DISTRIBUTION,
            connected_to_gateway=True,
            port_states=[STPPortConfig(port_idx=1, connected_device_id='dist1')],
        )
        flex_xg = SwitchSTPConfig(
            device_id='flex1',
            name='Xray3 USW Flex XG 10G',
            mac='00:00:00:00:00:20',
            model='USW-Flex-XG',
            current_priority=STP_PRIORITY_CORE,
            connected_to_gateway=True,
        )
        distribution = SwitchSTPConfig(
            device_id='dist1',
            name='Xray3 Yankee3 US 8 60W',
            mac='00:00:00:00:00:30',
            current_priority=STP_PRIORITY_DISTRIBUTION,
            port_states=[STPPortConfig(port_idx=1, connected_device_id='lite1')],
        )
        topology = STPTopology(switches=[lite, flex_xg, distribution])
        _calculate_hierarchy_tiers(topology.switches)

        changes = await calculate_optimal_priorities(topology)

        dist_change = next(change for change in changes if change.device_id == 'dist1')
        assert dist_change.new_priority == 12288


class TestSTPPathCostAudit:
    """Tests for STP path-cost sanity checks."""

    def test_expected_long_path_costs(self) -> None:
        """Known Ethernet speeds map to IEEE long path costs."""
        assert expected_long_path_cost(100000) == 200
        assert expected_long_path_cost(40000) == 500
        assert expected_long_path_cost(10000) == 2000
        assert expected_long_path_cost(5000) == 4000
        assert expected_long_path_cost(2500) == 8000
        assert expected_long_path_cost(1000) == 20000
        assert expected_long_path_cost(100) == 200000

    def test_flags_legacy_10g_path_cost(self) -> None:
        """10G path cost 2 suggests legacy mode and must be flagged."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='agg1',
                    link_speed_mbps=10000,
                    path_cost=2,
                )
            ],
        )
        agg = SwitchSTPConfig(
            device_id='agg1',
            name='Aggregation',
            mac='00:00:00:00:00:02',
        )
        topology = STPTopology(switches=[core, agg])

        findings = audit_stp_path_costs(topology)

        assert len(findings) == 1
        assert findings[0].severity == 'CRITICAL'
        assert findings[0].expected_long_cost == 2000

    def test_accepts_10g_long_path_cost(self) -> None:
        """10G path cost 2000 matches long mode and passes."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='agg1',
                    link_speed_mbps=10000,
                    path_cost=2000,
                )
            ],
        )
        agg = SwitchSTPConfig(
            device_id='agg1',
            name='Aggregation',
            mac='00:00:00:00:00:02',
        )
        topology = STPTopology(switches=[core, agg])

        assert audit_stp_path_costs(topology) == []


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


class Test10GExpansionValidation:
    """Tests for 10G expansion validation logic."""

    def test_ready_with_clean_10g_core_links(self) -> None:
        """Clean explicit STP config with enough 10G links is ready."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            current_priority=STP_PRIORITY_CORE,
            hierarchy_tier=0,
            is_root_bridge=True,
            connected_to_gateway=True,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='flex1',
                    is_up=True,
                    link_speed_mbps=10000,
                ),
                STPPortConfig(
                    port_idx=2,
                    connected_device_id='flex2',
                    is_up=True,
                    link_speed_mbps=10000,
                ),
            ],
        )
        flex1 = SwitchSTPConfig(
            device_id='flex1',
            name='Flex-XG-1',
            mac='00:00:00:00:00:02',
            current_priority=STP_PRIORITY_DISTRIBUTION,
            hierarchy_tier=1,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='core1',
                    is_up=True,
                    link_speed_mbps=10000,
                ),
            ],
        )
        flex2 = SwitchSTPConfig(
            device_id='flex2',
            name='Flex-XG-2',
            mac='00:00:00:00:00:03',
            current_priority=STP_PRIORITY_DISTRIBUTION,
            hierarchy_tier=1,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='core1',
                    is_up=True,
                    link_speed_mbps=10000,
                ),
            ],
        )
        topology = STPTopology(
            root_bridge_id='core1',
            root_bridge_name='Core',
            root_bridge_priority=STP_PRIORITY_CORE,
            switches=[core, flex1, flex2],
            connections=[
                STPConnection(
                    from_device_id='core1',
                    from_device_name='Core',
                    from_port_idx=1,
                    to_device_id='flex1',
                    to_device_name='Flex-XG-1',
                ),
                STPConnection(
                    from_device_id='core1',
                    from_device_name='Core',
                    from_port_idx=2,
                    to_device_id='flex2',
                    to_device_name='Flex-XG-2',
                ),
            ],
        )

        report = build_10g_expansion_validation_report(topology, [], planned_flex_xg_switches=2)

        assert report.readiness == 'READY'
        assert report.validation_passed is True
        assert report.ten_gig_links == 4
        assert report.findings == []

    def test_flags_bad_root_and_port_errors(self) -> None:
        """Validation blocks expansion when root placement and links are unhealthy."""
        access = SwitchSTPConfig(
            device_id='access1',
            name='Access',
            mac='00:00:00:00:00:02',
            current_priority=STP_PRIORITY_DEFAULT,
            hierarchy_tier=1,
            is_root_bridge=True,
            connected_to_gateway=False,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='core1',
                    is_up=True,
                    link_speed_mbps=1000,
                    full_duplex=False,
                    rx_errors=2000,
                    crc_errors=150,
                ),
            ],
        )
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            current_priority=STP_PRIORITY_DEFAULT,
            hierarchy_tier=0,
            connected_to_gateway=True,
        )
        topology = STPTopology(
            root_bridge_id='access1',
            root_bridge_name='Access',
            root_bridge_priority=STP_PRIORITY_DEFAULT,
            switches=[access, core],
            connections=[
                STPConnection(
                    from_device_id='access1',
                    from_device_name='Access',
                    from_port_idx=1,
                    to_device_id='core1',
                    to_device_name='Core',
                )
            ],
        )
        changes = [
            STPChange(
                device_id='core1',
                device_name='Core',
                current_priority=STP_PRIORITY_DEFAULT,
                new_priority=STP_PRIORITY_CORE,
                hierarchy_tier=0,
                reason='Core switch should have priority 4096',
            )
        ]

        report = build_10g_expansion_validation_report(topology, changes)

        assert report.readiness == 'NOT_READY'
        assert report.validation_passed is False
        assert any(f.category == 'STP' and f.severity == 'CRITICAL' for f in report.findings)
        assert any(f.category == 'Errors' and f.severity == 'CRITICAL' for f in report.findings)

    def test_drops_only_are_info_below_threshold(self) -> None:
        """Drops without CRC/RX/TX errors should not fail validation below threshold."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            current_priority=STP_PRIORITY_CORE,
            hierarchy_tier=0,
            is_root_bridge=True,
            connected_to_gateway=True,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='agg1',
                    is_up=True,
                    link_speed_mbps=10000,
                    path_cost=2000,
                    rx_dropped=999,
                )
            ],
        )
        agg = SwitchSTPConfig(
            device_id='agg1',
            name='Aggregation',
            mac='00:00:00:00:00:02',
            current_priority=STP_PRIORITY_DISTRIBUTION,
            hierarchy_tier=1,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='core1',
                    is_up=True,
                    link_speed_mbps=10000,
                    path_cost=2000,
                )
            ],
        )
        topology = STPTopology(
            root_bridge_id='core1',
            root_bridge_name='Core',
            root_bridge_priority=STP_PRIORITY_CORE,
            switches=[core, agg],
            connections=[
                STPConnection(
                    from_device_id='core1',
                    from_device_name='Core',
                    from_port_idx=1,
                    to_device_id='agg1',
                    to_device_name='Aggregation',
                )
            ],
        )

        report = build_10g_expansion_validation_report(
            topology,
            [],
            planned_flex_xg_switches=1,
            drops_threshold=100000,
        )

        assert report.readiness == 'READY'
        assert report.validation_passed is True
        assert any(f.category == 'Drops' and f.severity == 'INFO' for f in report.findings)

    def test_drops_only_warn_above_threshold(self) -> None:
        """Drops-only counters become warnings when above configured threshold."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            current_priority=STP_PRIORITY_CORE,
            hierarchy_tier=0,
            is_root_bridge=True,
            connected_to_gateway=True,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='agg1',
                    is_up=True,
                    link_speed_mbps=10000,
                    path_cost=2000,
                    rx_dropped=1001,
                )
            ],
        )
        agg = SwitchSTPConfig(
            device_id='agg1',
            name='Aggregation',
            mac='00:00:00:00:00:02',
            current_priority=STP_PRIORITY_DISTRIBUTION,
            hierarchy_tier=1,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='core1',
                    is_up=True,
                    link_speed_mbps=10000,
                    path_cost=2000,
                )
            ],
        )
        topology = STPTopology(
            root_bridge_id='core1',
            root_bridge_name='Core',
            root_bridge_priority=STP_PRIORITY_CORE,
            switches=[core, agg],
            connections=[
                STPConnection(
                    from_device_id='core1',
                    from_device_name='Core',
                    from_port_idx=1,
                    to_device_id='agg1',
                    to_device_name='Aggregation',
                )
            ],
        )

        report = build_10g_expansion_validation_report(
            topology,
            [],
            planned_flex_xg_switches=1,
            drops_threshold=1000,
        )

        assert report.readiness == 'READY_WITH_WARNINGS'
        assert any(f.category == 'Drops' and f.severity == 'WARNING' for f in report.findings)

    def test_validation_includes_path_cost_findings(self) -> None:
        """10G validation includes STP path-cost sanity findings."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            current_priority=STP_PRIORITY_CORE,
            hierarchy_tier=0,
            is_root_bridge=True,
            connected_to_gateway=True,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='agg1',
                    is_up=True,
                    link_speed_mbps=10000,
                    path_cost=2,
                )
            ],
        )
        agg = SwitchSTPConfig(
            device_id='agg1',
            name='Aggregation',
            mac='00:00:00:00:00:02',
            current_priority=STP_PRIORITY_DISTRIBUTION,
            hierarchy_tier=1,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='core1',
                    is_up=True,
                    link_speed_mbps=10000,
                    path_cost=2000,
                )
            ],
        )
        topology = STPTopology(
            root_bridge_id='core1',
            root_bridge_name='Core',
            root_bridge_priority=STP_PRIORITY_CORE,
            switches=[core, agg],
            connections=[
                STPConnection(
                    from_device_id='core1',
                    from_device_name='Core',
                    from_port_idx=1,
                    to_device_id='agg1',
                    to_device_name='Aggregation',
                )
            ],
        )

        report = build_10g_expansion_validation_report(topology, [])

        assert report.readiness == 'NOT_READY'
        assert any(
            finding.category == 'Path Cost' and finding.severity == 'CRITICAL'
            for finding in report.findings
        )

    def test_format_10g_validation_report_markdown(self) -> None:
        """Validation report markdown includes readiness and post-install checks."""
        changes = [
            STPChange(
                device_id='access1',
                device_name='Access',
                current_priority=STP_PRIORITY_DEFAULT,
                new_priority=STP_PRIORITY_ACCESS_BASE,
                hierarchy_tier=2,
                reason='Access switch should have priority 16384',
            )
        ]
        report = build_10g_expansion_validation_report(
            STPTopology(),
            changes,
            planned_flex_xg_switches=2,
        )

        markdown = format_10g_validation_report_markdown(report)

        assert '# UniFi 10G Expansion Validation Report' in markdown
        assert 'Readiness' in markdown
        assert 'Post-install Checks' in markdown
        assert '16384' in markdown
        assert '```diff' in markdown

    def test_validation_ignores_gateway_lldp_ports_for_10g_counts(self) -> None:
        """Gateway LLDP adjacency does not count as an inter-switch 10G port."""
        core = SwitchSTPConfig(
            device_id='core1',
            name='Core',
            mac='00:00:00:00:00:01',
            current_priority=STP_PRIORITY_CORE,
            hierarchy_tier=0,
            is_root_bridge=True,
            connected_to_gateway=True,
            port_states=[
                STPPortConfig(
                    port_idx=1,
                    connected_device_id='gateway1',
                    is_up=True,
                    link_speed_mbps=10000,
                )
            ],
        )
        topology = STPTopology(
            root_bridge_id='core1',
            root_bridge_name='Core',
            root_bridge_priority=STP_PRIORITY_CORE,
            gateway_id='gateway1',
            gateway_name='Gateway',
            switches=[core],
            connections=[
                STPConnection(
                    from_device_id='core1',
                    from_device_name='Core',
                    from_port_idx=1,
                    to_device_id='gateway1',
                    to_device_name='Gateway',
                )
            ],
        )

        report = build_10g_expansion_validation_report(
            topology,
            [],
            planned_flex_xg_switches=1,
        )

        assert report.ten_gig_links == 0
        assert any(f.category == 'Topology' and f.severity == 'CRITICAL' for f in report.findings)

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


class TestGatewayIsNeverPlanned:
    """The gateway's bridge priority is not managed here: never proposed, never the root."""

    @staticmethod
    def _switch(device_id: str, name: str, model: str, *, tier: int, **over: object):
        return SwitchSTPConfig(
            device_id=device_id,
            name=name,
            mac=f'02:00:00:00:00:{int(device_id[-2:], 16):02x}',
            model=model,
            current_priority=over.pop('priority', STP_PRIORITY_DEFAULT),  # type: ignore[arg-type]
            hierarchy_tier=tier,
            **over,  # type: ignore[arg-type]
        )

    def _gateway(self, *, tier: int, connected: bool) -> SwitchSTPConfig:
        return self._switch(
            '0000000000000000000000f1',
            'Gateway',
            'UDMPRO',
            tier=tier,
            priority=STP_PRIORITY_DEFAULT,  # so any tier's priority would be a change
            connected_to_gateway=connected,
            capability=SwitchCapabilityClass.GATEWAY,
        )

    async def test_no_change_is_proposed_for_a_gateway_in_the_topology(self) -> None:
        core = self._switch(
            '0000000000000000000000a1',
            'Switch A',
            'USW-Aggregation',
            tier=0,
            connected_to_gateway=True,
        )
        topology = STPTopology(
            gateway_id='0000000000000000000000f1',
            gateway_name='Gateway',
            switches=[core, self._gateway(tier=1, connected=False)],
        )
        changes = await calculate_optimal_priorities(topology)
        assert [c.device_name for c in changes] == ['Switch A']
        assert changes[0].new_priority == STP_PRIORITY_CORE

    async def test_the_gateway_is_never_the_preferred_root(self) -> None:
        # An unknown-model core and the gateway both at tier 0, neither root-eligible: on a
        # name tie-break the gateway ('Gateway' < 'Switch A') used to win the root.
        core = self._switch(
            '0000000000000000000000a1',
            'Switch A',
            'unknown-model',
            tier=0,
            connected_to_gateway=True,
        )
        topology = STPTopology(
            gateway_id='0000000000000000000000f1',
            switches=[self._gateway(tier=0, connected=True), core],
        )
        changes = {
            c.device_name: c.new_priority for c in await calculate_optimal_priorities(topology)
        }
        assert changes == {'Switch A': STP_PRIORITY_CORE}

    async def test_the_report_never_names_the_gateway_as_optimal_root(self) -> None:
        from unifi_mapper.analysis.stp_optimizer import generate_stp_report

        # No LLDP to the gateway: every switch keeps tier 2 and the gateway comes first.
        switches = [
            self._gateway(tier=2, connected=False),
            self._switch('0000000000000000000000a1', 'Switch A', 'USW-Pro-24', tier=2),
        ]
        topology = STPTopology(gateway_id='0000000000000000000000f1', switches=switches)
        changes = await calculate_optimal_priorities(topology)
        report = await generate_stp_report(topology, changes)
        assert report.optimal_root == 'Switch A'
        assert all(c.device_name != 'Gateway' for c in report.changes)
        assert any('Skipped Gateway' in line for line in report.recommendations)

    async def test_a_gateway_alone_leaves_no_optimal_root(self) -> None:
        from unifi_mapper.analysis.stp_optimizer import generate_stp_report

        topology = STPTopology(
            gateway_id='0000000000000000000000f1',
            switches=[self._gateway(tier=2, connected=False)],
        )
        report = await generate_stp_report(topology, await calculate_optimal_priorities(topology))
        assert report.optimal_root is None and report.changes == []

    def test_stp_optimize_prints_one_line_per_skipped_gateway(self, monkeypatch) -> None:
        from typer.testing import CliRunner
        from unifi_mapper.analysis import stp_optimizer
        from unifi_mapper.typer_cli import app

        core = self._switch(
            '0000000000000000000000a1',
            'Switch A',
            'USW-Aggregation',
            tier=0,
            connected_to_gateway=True,
        )
        topology = STPTopology(
            gateway_id='0000000000000000000000f1',
            switches=[core, self._gateway(tier=1, connected=False)],
        )

        async def _discover(*_args: object, **_kwargs: object) -> STPTopology:
            return topology

        monkeypatch.setattr('unifi_mapper.cli.load_env_from_config', lambda path: None)
        monkeypatch.setattr(stp_optimizer, 'discover_stp_topology', _discover)
        result = CliRunner().invoke(app, ['stp', 'optimize'])
        assert result.exit_code == 0, result.output
        flat = ' '.join(result.output.split())
        assert flat.count('Skipped Gateway: gateway; its STP priority is not changed') == 1
        assert 'Switch A' in flat
