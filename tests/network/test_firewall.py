"""Tests for Firewall management module."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unifi_mapper.network.firewall import (
    FirewallManager,
    PolicyHitStats,
    ZoneTrafficStats,
)
from unifi_mapper.network.models import (
    FirewallAction,
    FirewallActionType,
    FirewallDestination,
    FirewallPolicy,
    FirewallSource,
    FirewallZone,
)
from unittest.mock import AsyncMock, MagicMock


class TestPolicyHitStats:
    """Tests for PolicyHitStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        stats = PolicyHitStats(policy_id='policy-1', policy_name='Block IoT')
        assert stats.policy_id == 'policy-1'
        assert stats.policy_name == 'Block IoT'
        assert stats.hit_count == 0
        assert stats.blocked_count == 0
        assert stats.allowed_count == 0

    def test_with_data(self) -> None:
        """Test creation with actual stats."""
        stats = PolicyHitStats(
            policy_id='policy-1',
            policy_name='Block IoT',
            hit_count=100,
            last_hit=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            blocked_count=95,
            allowed_count=5,
            bytes_matched=1024000,
        )
        assert stats.hit_count == 100
        assert stats.blocked_count == 95
        assert stats.bytes_matched == 1024000


class TestZoneTrafficStats:
    """Tests for ZoneTrafficStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation."""
        stats = ZoneTrafficStats(
            source_zone_id='zone-1',
            source_zone_name='IoT',
            destination_zone_id='zone-2',
            destination_zone_name='WAN',
        )
        assert stats.source_zone_name == 'IoT'
        assert stats.destination_zone_name == 'WAN'
        assert stats.policy_count == 0
        assert stats.enabled_policies == 0
        assert stats.logging_enabled_count == 0
        assert stats.policies == []


class TestFirewallManager:
    """Tests for FirewallManager."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_firewall_zones = AsyncMock()
        client.list_firewall_policies = AsyncMock()
        client.enable_policy_logging = AsyncMock()
        client.create_firewall_policy = AsyncMock()
        return client

    @pytest.fixture
    def sample_zones(self) -> list[FirewallZone]:
        """Create sample firewall zones."""
        return [
            FirewallZone(id='zone-iot', name='IoT', networkIds=['net-1'], configurable=True),
            FirewallZone(id='zone-lan', name='LAN', networkIds=['net-2'], configurable=True),
            FirewallZone(id='zone-wan', name='WAN', networkIds=[], configurable=False),
        ]

    @pytest.fixture
    def sample_policies(self) -> list[FirewallPolicy]:
        """Create sample firewall policies."""
        return [
            FirewallPolicy(
                id='policy-1',
                name='Block IoT to WAN',
                enabled=True,
                loggingEnabled=True,
                action=FirewallAction(type=FirewallActionType.BLOCK),
                source=FirewallSource(firewallZoneId='zone-iot'),
                destination=FirewallDestination(firewallZoneId='zone-wan'),
                origin='USER',
            ),
            FirewallPolicy(
                id='policy-2',
                name='Allow LAN to WAN',
                enabled=True,
                loggingEnabled=False,
                action=FirewallAction(type=FirewallActionType.ALLOW),
                source=FirewallSource(firewallZoneId='zone-lan'),
                destination=FirewallDestination(firewallZoneId='zone-wan'),
                origin='USER',
            ),
            FirewallPolicy(
                id='policy-3',
                name='System Policy',
                enabled=True,
                loggingEnabled=False,
                action=FirewallAction(type=FirewallActionType.BLOCK),
                source=FirewallSource(firewallZoneId='zone-iot'),
                destination=FirewallDestination(firewallZoneId='zone-lan'),
                origin='SYSTEM',
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_zones(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
    ) -> None:
        """Test getting firewall zones."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = []

        manager = FirewallManager(mock_client)
        zones = await manager.get_zones()

        assert len(zones) == 3
        assert any(z.name == 'IoT' for z in zones)

    @pytest.mark.asyncio
    async def test_get_zone_by_name(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
    ) -> None:
        """Test getting zone by name."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = []

        manager = FirewallManager(mock_client)

        # Case-insensitive search
        zone = await manager.get_zone_by_name('iot')
        assert zone is not None
        assert zone.name == 'IoT'

        # Non-existent zone
        zone = await manager.get_zone_by_name('nonexistent')
        assert zone is None

    @pytest.mark.asyncio
    async def test_get_policies(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test getting firewall policies."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        manager = FirewallManager(mock_client)
        policies = await manager.get_policies()

        assert len(policies) == 3
        assert any(p.name == 'Block IoT to WAN' for p in policies)

    @pytest.mark.asyncio
    async def test_get_policies_for_zone_pair(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test getting policies for zone pair."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        manager = FirewallManager(mock_client)
        policies = await manager.get_policies_for_zone_pair('zone-iot', 'zone-wan')

        assert len(policies) == 1
        assert policies[0].name == 'Block IoT to WAN'

    @pytest.mark.asyncio
    async def test_get_zone_traffic_stats(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test zone traffic statistics."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        manager = FirewallManager(mock_client)
        stats = await manager.get_zone_traffic_stats()

        # Should have stats for each unique zone pair
        assert len(stats) == 3  # IoT→WAN, LAN→WAN, IoT→LAN

        # Find IoT→WAN stats
        iot_wan = next(
            (s for s in stats if s.source_zone_name == 'IoT' and s.destination_zone_name == 'WAN'),
            None,
        )
        assert iot_wan is not None
        assert iot_wan.policy_count == 1
        assert iot_wan.logging_enabled_count == 1

    @pytest.mark.asyncio
    async def test_enable_logging_for_policy(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test enabling logging for a policy."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        updated_policy = FirewallPolicy(
            id='policy-2',
            name='Allow LAN to WAN',
            enabled=True,
            loggingEnabled=True,
            action=FirewallAction(type=FirewallActionType.ALLOW),
        )
        mock_client.enable_policy_logging.return_value = updated_policy

        manager = FirewallManager(mock_client)
        result = await manager.enable_logging_for_policy('policy-2')

        assert result.logging_enabled is True
        mock_client.enable_policy_logging.assert_called_once_with('policy-2', enabled=True)

    @pytest.mark.asyncio
    async def test_enable_logging_for_all_policies(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test enabling logging for all policies."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        # Mock return updated policy
        mock_client.enable_policy_logging.return_value = FirewallPolicy(
            id='policy-2',
            name='Allow LAN to WAN',
            enabled=True,
            loggingEnabled=True,
            action=FirewallAction(type=FirewallActionType.ALLOW),
        )

        manager = FirewallManager(mock_client)
        updated = await manager.enable_logging_for_all_policies()

        # Should only update policy-2 (policy-1 already has logging, policy-3 is SYSTEM)
        assert len(updated) == 1
        assert updated[0].name == 'Allow LAN to WAN'

    @pytest.mark.asyncio
    async def test_enable_logging_block_only(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test enabling logging only for BLOCK policies."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        manager = FirewallManager(mock_client)
        updated = await manager.enable_logging_for_all_policies(block_only=True)

        # Should not update any (policy-1 already has logging, policy-3 is SYSTEM)
        assert len(updated) == 0

    @pytest.mark.asyncio
    async def test_get_policies_without_logging(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test getting policies without logging enabled."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        manager = FirewallManager(mock_client)
        policies = await manager.get_policies_without_logging()

        assert len(policies) == 2  # policy-2 and policy-3
        assert all(not p.logging_enabled for p in policies)

    @pytest.mark.asyncio
    async def test_create_block_policy(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
    ) -> None:
        """Test creating a block policy."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = []

        new_policy = FirewallPolicy(
            id='new-policy',
            name='Block Test',
            enabled=True,
            loggingEnabled=True,
            action=FirewallAction(type=FirewallActionType.BLOCK),
        )
        mock_client.create_firewall_policy.return_value = new_policy

        manager = FirewallManager(mock_client)
        result = await manager.create_block_policy(
            name='Block Test',
            source_zone_name='IoT',
            destination_zone_name='LAN',
            logging_enabled=True,
        )

        assert result.name == 'Block Test'
        mock_client.create_firewall_policy.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_block_policy_zone_not_found(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
    ) -> None:
        """Test creating block policy with non-existent zone."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = []

        manager = FirewallManager(mock_client)

        with pytest.raises(ValueError, match='Source zone not found'):
            await manager.create_block_policy(
                name='Test',
                source_zone_name='NonExistent',
                destination_zone_name='LAN',
            )

    @pytest.mark.asyncio
    async def test_get_security_audit_report(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test security audit report generation."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        manager = FirewallManager(mock_client)
        report = await manager.get_security_audit_report()

        assert 'generated_at' in report
        assert 'summary' in report
        assert 'recommendations' in report
        assert 'zones' in report
        assert 'policies_without_logging' in report

        summary = report['summary']
        assert summary['total_zones'] == 3
        assert summary['total_policies'] == 3
        assert summary['block_policies'] == 2
        assert summary['allow_policies'] == 1
        assert summary['policies_with_logging'] == 1

    @pytest.mark.asyncio
    async def test_cache_usage(
        self,
        mock_client: MagicMock,
        sample_zones: list[FirewallZone],
        sample_policies: list[FirewallPolicy],
    ) -> None:
        """Test that cache is used properly."""
        mock_client.list_firewall_zones.return_value = sample_zones
        mock_client.list_firewall_policies.return_value = sample_policies

        manager = FirewallManager(mock_client)

        # First call should fetch
        await manager.get_zones()
        assert mock_client.list_firewall_zones.call_count == 1

        # Second call should use cache
        await manager.get_zones()
        assert mock_client.list_firewall_zones.call_count == 1

        # Force refresh
        await manager.get_zones(refresh=True)
        assert mock_client.list_firewall_zones.call_count == 2
