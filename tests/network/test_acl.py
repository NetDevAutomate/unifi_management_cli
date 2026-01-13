"""Tests for ACL management module."""

from __future__ import annotations

import pytest
from unifi_mapper.network.acl import (
    ACLManager,
    ACLRuleStats,
    ACLSummary,
)
from unifi_mapper.network.models import (
    ACLActionType,
    ACLDeviceFilter,
    ACLProtocol,
    ACLRule,
    ACLTrafficFilter,
)
from unittest.mock import AsyncMock, MagicMock


class TestACLRuleStats:
    """Tests for ACLRuleStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        stats = ACLRuleStats(
            rule_id='rule-1',
            rule_name='Block SSH',
            action=ACLActionType.BLOCK,
        )
        assert stats.rule_id == 'rule-1'
        assert stats.rule_name == 'Block SSH'
        assert stats.action == ACLActionType.BLOCK
        assert stats.enabled is True
        assert stats.has_source_filter is False
        assert stats.has_destination_filter is False
        assert stats.protocols == []
        assert stats.enforcing_device_count == 0

    def test_with_data(self) -> None:
        """Test creation with actual stats."""
        stats = ACLRuleStats(
            rule_id='rule-1',
            rule_name='Block SSH',
            action=ACLActionType.BLOCK,
            enabled=True,
            has_source_filter=True,
            has_destination_filter=True,
            protocols=[ACLProtocol.TCP],
            enforcing_device_count=3,
        )
        assert stats.enabled is True
        assert stats.has_source_filter is True
        assert stats.protocols == [ACLProtocol.TCP]
        assert stats.enforcing_device_count == 3


class TestACLSummary:
    """Tests for ACLSummary dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        summary = ACLSummary()
        assert summary.total_rules == 0
        assert summary.enabled_rules == 0
        assert summary.disabled_rules == 0
        assert summary.block_rules == 0
        assert summary.allow_rules == 0
        assert summary.user_rules == 0
        assert summary.system_rules == 0
        assert summary.rules_with_source_filter == 0
        assert summary.rules_with_destination_filter == 0
        assert summary.rules_by_protocol == {}

    def test_with_counts(self) -> None:
        """Test creation with actual counts."""
        summary = ACLSummary(
            total_rules=10,
            enabled_rules=8,
            disabled_rules=2,
            block_rules=6,
            allow_rules=4,
            user_rules=7,
            system_rules=3,
            rules_with_source_filter=5,
            rules_with_destination_filter=4,
            rules_by_protocol={'TCP': 8, 'UDP': 2},
        )
        assert summary.total_rules == 10
        assert summary.block_rules == 6
        assert summary.rules_by_protocol['TCP'] == 8


class TestACLManager:
    """Tests for ACLManager."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_acl_rules = AsyncMock()
        client.create_acl_rule = AsyncMock()
        client.update_acl_rule = AsyncMock()
        client.delete_acl_rule = AsyncMock()
        return client

    @pytest.fixture
    def sample_rules(self) -> list[ACLRule]:
        """Create sample ACL rules."""
        return [
            ACLRule(
                id='rule-1',
                type='INTER_NETWORK',
                name='Block SSH',
                enabled=True,
                action=ACLActionType.BLOCK,
                origin='USER',
                sourceFilter=ACLTrafficFilter(
                    ipAddressesOrSubnets=['192.168.1.0/24'],
                    portsFilter=[22],
                ),
                destinationFilter=ACLTrafficFilter(
                    ipAddressesOrSubnets=['10.0.0.0/8'],
                ),
                protocolFilter=[ACLProtocol.TCP],
            ),
            ACLRule(
                id='rule-2',
                type='INTER_NETWORK',
                name='Allow Web',
                enabled=True,
                action=ACLActionType.ALLOW,
                origin='USER',
                sourceFilter=ACLTrafficFilter(
                    networkIds=['net-1'],
                ),
                destinationFilter=ACLTrafficFilter(
                    portsFilter=[80, 443],
                ),
                protocolFilter=[ACLProtocol.TCP],
            ),
            ACLRule(
                id='rule-3',
                type='INTER_NETWORK',
                name='System Rule',
                enabled=False,
                action=ACLActionType.BLOCK,
                origin='SYSTEM',
            ),
            ACLRule(
                id='rule-4',
                type='INTER_NETWORK',
                name='Block DNS',
                enabled=True,
                action=ACLActionType.BLOCK,
                origin='USER',
                protocolFilter=[ACLProtocol.TCP, ACLProtocol.UDP],
                enforcingDeviceFilter=ACLDeviceFilter(
                    deviceIds=['device-1', 'device-2'],
                ),
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_all_rules(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting all ACL rules."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_all_rules()

        assert len(rules) == 4
        assert any(r.name == 'Block SSH' for r in rules)

    @pytest.mark.asyncio
    async def test_get_rule_by_id(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting rule by ID."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)

        rule = await manager.get_rule_by_id('rule-1')
        assert rule is not None
        assert rule.name == 'Block SSH'

        rule = await manager.get_rule_by_id('nonexistent')
        assert rule is None

    @pytest.mark.asyncio
    async def test_get_rule_by_name(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting rule by name."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)

        # Case-insensitive search
        rule = await manager.get_rule_by_name('block ssh')
        assert rule is not None
        assert rule.id == 'rule-1'

        rule = await manager.get_rule_by_name('nonexistent')
        assert rule is None

    @pytest.mark.asyncio
    async def test_get_enabled_rules(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting enabled rules."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_enabled_rules()

        assert len(rules) == 3
        assert all(r.enabled for r in rules)

    @pytest.mark.asyncio
    async def test_get_disabled_rules(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting disabled rules."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_disabled_rules()

        assert len(rules) == 1
        assert rules[0].name == 'System Rule'

    @pytest.mark.asyncio
    async def test_get_block_rules(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting BLOCK rules."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_block_rules()

        assert len(rules) == 3
        assert all(r.action == ACLActionType.BLOCK for r in rules)

    @pytest.mark.asyncio
    async def test_get_allow_rules(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting ALLOW rules."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_allow_rules()

        assert len(rules) == 1
        assert rules[0].name == 'Allow Web'

    @pytest.mark.asyncio
    async def test_get_user_rules(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting user-defined rules."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_user_rules()

        assert len(rules) == 3
        assert all(r.origin == 'USER' for r in rules)

    @pytest.mark.asyncio
    async def test_get_system_rules(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting system rules."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_system_rules()

        assert len(rules) == 1
        assert rules[0].name == 'System Rule'

    @pytest.mark.asyncio
    async def test_get_rules_by_protocol(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting rules by protocol."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        tcp_rules = await manager.get_rules_by_protocol(ACLProtocol.TCP)

        assert len(tcp_rules) == 3  # rule-1, rule-2, rule-4

    @pytest.mark.asyncio
    async def test_get_rules_for_network(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting rules for a network."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_rules_for_network('net-1')

        assert len(rules) == 1
        assert rules[0].name == 'Allow Web'

    @pytest.mark.asyncio
    async def test_get_rules_for_device(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting rules for a device."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        rules = await manager.get_rules_for_device('device-1')

        # Rules without device filter apply to all devices
        # rule-4 has device filter including device-1
        assert len(rules) == 4

    @pytest.mark.asyncio
    async def test_create_block_rule(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating a BLOCK rule."""
        mock_client.list_acl_rules.return_value = []

        new_rule = ACLRule(
            id='new-rule',
            name='Block Test',
            enabled=True,
            action=ACLActionType.BLOCK,
        )
        mock_client.create_acl_rule.return_value = new_rule

        manager = ACLManager(mock_client)
        result = await manager.create_block_rule(
            name='Block Test',
            source_ips=['192.168.1.0/24'],
            destination_ports=[22],
            protocols=[ACLProtocol.TCP],
        )

        assert result.name == 'Block Test'
        mock_client.create_acl_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_allow_rule(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating an ALLOW rule."""
        mock_client.list_acl_rules.return_value = []

        new_rule = ACLRule(
            id='new-rule',
            name='Allow Test',
            enabled=True,
            action=ACLActionType.ALLOW,
        )
        mock_client.create_acl_rule.return_value = new_rule

        manager = ACLManager(mock_client)
        result = await manager.create_allow_rule(
            name='Allow Test',
            source_ips=['10.0.0.0/8'],
            destination_ports=[80, 443],
        )

        assert result.name == 'Allow Test'
        mock_client.create_acl_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_enable_rule(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test enabling a rule."""
        mock_client.list_acl_rules.return_value = sample_rules

        updated_rule = ACLRule(
            id='rule-3',
            name='System Rule',
            enabled=True,
            action=ACLActionType.BLOCK,
        )
        mock_client.update_acl_rule.return_value = updated_rule

        manager = ACLManager(mock_client)
        result = await manager.enable_rule('rule-3')

        assert result.enabled is True
        mock_client.update_acl_rule.assert_called_once_with('rule-3', enabled=True)

    @pytest.mark.asyncio
    async def test_disable_rule(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test disabling a rule."""
        mock_client.list_acl_rules.return_value = sample_rules

        updated_rule = ACLRule(
            id='rule-1',
            name='Block SSH',
            enabled=False,
            action=ACLActionType.BLOCK,
        )
        mock_client.update_acl_rule.return_value = updated_rule

        manager = ACLManager(mock_client)
        result = await manager.disable_rule('rule-1')

        assert result.enabled is False
        mock_client.update_acl_rule.assert_called_once_with('rule-1', enabled=False)

    @pytest.mark.asyncio
    async def test_delete_rule(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test deleting a rule."""
        mock_client.list_acl_rules.return_value = sample_rules
        mock_client.delete_acl_rule.return_value = None

        manager = ACLManager(mock_client)
        result = await manager.delete_rule('rule-1')

        assert result is True
        mock_client.delete_acl_rule.assert_called_once_with('rule-1')

    @pytest.mark.asyncio
    async def test_analyze_rule(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test analyzing a rule."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        stats = manager.analyze_rule(sample_rules[0])

        assert stats.rule_id == 'rule-1'
        assert stats.rule_name == 'Block SSH'
        assert stats.action == ACLActionType.BLOCK
        assert stats.has_source_filter is True
        assert stats.has_destination_filter is True
        assert ACLProtocol.TCP in stats.protocols

    @pytest.mark.asyncio
    async def test_get_acl_summary(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test getting ACL summary."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        summary = await manager.get_acl_summary()

        assert summary.total_rules == 4
        assert summary.enabled_rules == 3
        assert summary.disabled_rules == 1
        assert summary.block_rules == 3
        assert summary.allow_rules == 1
        assert summary.user_rules == 3
        assert summary.system_rules == 1

    @pytest.mark.asyncio
    async def test_get_security_report(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test security report generation."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)
        report = await manager.get_security_report()

        assert 'summary' in report
        assert 'issues' in report
        assert 'recommendations' in report
        assert 'rules_by_protocol' in report

        summary = report['summary']
        assert summary['total_rules'] == 4

    @pytest.mark.asyncio
    async def test_cache_usage(
        self,
        mock_client: MagicMock,
        sample_rules: list[ACLRule],
    ) -> None:
        """Test that cache is used properly."""
        mock_client.list_acl_rules.return_value = sample_rules

        manager = ACLManager(mock_client)

        # First call should fetch
        await manager.get_all_rules()
        assert mock_client.list_acl_rules.call_count == 1

        # Second call should use cache
        await manager.get_all_rules()
        assert mock_client.list_acl_rules.call_count == 1

        # Force refresh
        await manager.get_all_rules(refresh=True)
        assert mock_client.list_acl_rules.call_count == 2
