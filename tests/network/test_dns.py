"""Tests for DNS policy management module."""

from __future__ import annotations

import pytest
from unifi_mapper.network.dns import (
    DNSPolicyManager,
    DNSPolicySummary,
    DNSRecordInfo,
)
from unifi_mapper.network.models import DNSPolicy
from unittest.mock import AsyncMock, MagicMock


class TestDNSPolicySummary:
    """Tests for DNSPolicySummary dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        summary = DNSPolicySummary()
        assert summary.total_policies == 0
        assert summary.enabled_policies == 0
        assert summary.disabled_policies == 0
        assert summary.a_records == 0
        assert summary.aaaa_records == 0
        assert summary.cname_records == 0
        assert summary.mx_records == 0
        assert summary.txt_records == 0
        assert summary.srv_records == 0
        assert summary.other_records == 0
        assert summary.domains == []

    def test_with_data(self) -> None:
        """Test creation with actual data."""
        summary = DNSPolicySummary(
            total_policies=10,
            enabled_policies=8,
            disabled_policies=2,
            a_records=5,
            aaaa_records=2,
            cname_records=1,
            mx_records=1,
            txt_records=1,
            domains=['example.com', 'test.local'],
        )
        assert summary.total_policies == 10
        assert summary.a_records == 5
        assert len(summary.domains) == 2


class TestDNSRecordInfo:
    """Tests for DNSRecordInfo dataclass."""

    def test_creation(self) -> None:
        """Test creation with all fields."""
        info = DNSRecordInfo(
            policy_id='policy-1',
            domain='local.example.com',
            record_type='A',
            enabled=True,
            ttl_seconds=3600,
            value='192.168.1.100',
        )
        assert info.policy_id == 'policy-1'
        assert info.domain == 'local.example.com'
        assert info.record_type == 'A'
        assert info.enabled is True
        assert info.ttl_seconds == 3600
        assert info.value == '192.168.1.100'


class TestDNSPolicyManager:
    """Tests for DNSPolicyManager."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_dns_policies = AsyncMock()
        client.create_dns_policy = AsyncMock()
        client.update_dns_policy = AsyncMock()
        client.delete_dns_policy = AsyncMock()
        return client

    @pytest.fixture
    def sample_policies(self) -> list[DNSPolicy]:
        """Create sample DNS policies."""
        return [
            DNSPolicy(
                id='policy-1',
                type='A',
                enabled=True,
                domain='server.local',
                ipv4Address='192.168.1.100',
                ttlSeconds=3600,
            ),
            DNSPolicy(
                id='policy-2',
                type='A',
                enabled=True,
                domain='nas.local',
                ipv4Address='192.168.1.50',
                ttlSeconds=1800,
            ),
            DNSPolicy(
                id='policy-3',
                type='AAAA',
                enabled=True,
                domain='server.local',
                ipv6Address='fd00::100',
                ttlSeconds=3600,
            ),
            DNSPolicy(
                id='policy-4',
                type='CNAME',
                enabled=False,
                domain='www.local',
                targetDomain='server.local',
                ttlSeconds=3600,
            ),
            DNSPolicy(
                id='policy-5',
                type='TXT',
                enabled=True,
                domain='_dmarc.local',
                text='v=DMARC1; p=none',
                ttlSeconds=86400,
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_all_policies(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting all DNS policies."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)
        policies = await manager.get_all_policies()

        assert len(policies) == 5
        assert any(p.domain == 'server.local' for p in policies)

    @pytest.mark.asyncio
    async def test_get_policy_by_id(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting policy by ID."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)

        policy = await manager.get_policy_by_id('policy-1')
        assert policy is not None
        assert policy.domain == 'server.local'

        policy = await manager.get_policy_by_id('nonexistent')
        assert policy is None

    @pytest.mark.asyncio
    async def test_get_policy_by_domain(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting policy by domain."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)

        # Case-insensitive search
        policy = await manager.get_policy_by_domain('SERVER.LOCAL')
        assert policy is not None
        assert policy.id == 'policy-1'

        policy = await manager.get_policy_by_domain('nonexistent.local')
        assert policy is None

    @pytest.mark.asyncio
    async def test_get_enabled_policies(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting enabled policies."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)
        policies = await manager.get_enabled_policies()

        assert len(policies) == 4
        assert all(p.enabled for p in policies)

    @pytest.mark.asyncio
    async def test_get_disabled_policies(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting disabled policies."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)
        policies = await manager.get_disabled_policies()

        assert len(policies) == 1
        assert policies[0].domain == 'www.local'

    @pytest.mark.asyncio
    async def test_get_policies_by_type(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting policies by record type."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)

        a_records = await manager.get_policies_by_type('A')
        assert len(a_records) == 2

        aaaa_records = await manager.get_policies_by_type('AAAA')
        assert len(aaaa_records) == 1

        # Case-insensitive
        cname_records = await manager.get_policies_by_type('cname')
        assert len(cname_records) == 1

    @pytest.mark.asyncio
    async def test_search_policies(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test searching policies by domain."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)

        # Partial match
        results = await manager.search_policies('server')
        assert len(results) == 2  # server.local (A and AAAA)

        results = await manager.search_policies('local')
        assert len(results) == 5  # All have .local

    @pytest.mark.asyncio
    async def test_create_a_record(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating an A record."""
        mock_client.list_dns_policies.return_value = []

        new_policy = DNSPolicy(
            id='new-policy',
            type='A',
            enabled=True,
            domain='new.local',
            ipv4Address='192.168.1.200',
            ttlSeconds=3600,
        )
        mock_client.create_dns_policy.return_value = new_policy

        manager = DNSPolicyManager(mock_client)
        result = await manager.create_a_record(
            domain='new.local',
            ipv4_address='192.168.1.200',
        )

        assert result.domain == 'new.local'
        assert result.ipv4_address == '192.168.1.200'
        mock_client.create_dns_policy.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_aaaa_record(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating an AAAA record."""
        mock_client.list_dns_policies.return_value = []

        new_policy = DNSPolicy(
            id='new-policy',
            type='AAAA',
            enabled=True,
            domain='new.local',
            ipv6Address='fd00::200',
            ttlSeconds=3600,
        )
        mock_client.create_dns_policy.return_value = new_policy

        manager = DNSPolicyManager(mock_client)
        result = await manager.create_aaaa_record(
            domain='new.local',
            ipv6_address='fd00::200',
        )

        assert result.domain == 'new.local'
        assert result.ipv6_address == 'fd00::200'
        mock_client.create_dns_policy.assert_called_once()

    @pytest.mark.asyncio
    async def test_enable_policy(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test enabling a policy."""
        mock_client.list_dns_policies.return_value = sample_policies

        updated_policy = DNSPolicy(
            id='policy-4',
            type='CNAME',
            enabled=True,
            domain='www.local',
        )
        mock_client.update_dns_policy.return_value = updated_policy

        manager = DNSPolicyManager(mock_client)
        result = await manager.enable_policy('policy-4')

        assert result.enabled is True
        mock_client.update_dns_policy.assert_called_once_with('policy-4', enabled=True)

    @pytest.mark.asyncio
    async def test_disable_policy(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test disabling a policy."""
        mock_client.list_dns_policies.return_value = sample_policies

        updated_policy = DNSPolicy(
            id='policy-1',
            type='A',
            enabled=False,
            domain='server.local',
        )
        mock_client.update_dns_policy.return_value = updated_policy

        manager = DNSPolicyManager(mock_client)
        result = await manager.disable_policy('policy-1')

        assert result.enabled is False
        mock_client.update_dns_policy.assert_called_once_with('policy-1', enabled=False)

    @pytest.mark.asyncio
    async def test_update_ttl(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test updating policy TTL."""
        mock_client.list_dns_policies.return_value = sample_policies

        updated_policy = DNSPolicy(
            id='policy-1',
            type='A',
            enabled=True,
            domain='server.local',
            ttlSeconds=7200,
        )
        mock_client.update_dns_policy.return_value = updated_policy

        manager = DNSPolicyManager(mock_client)
        result = await manager.update_ttl('policy-1', 7200)

        assert result.ttl_seconds == 7200
        mock_client.update_dns_policy.assert_called_once_with('policy-1', ttlSeconds=7200)

    @pytest.mark.asyncio
    async def test_delete_policy(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test deleting a policy."""
        mock_client.list_dns_policies.return_value = sample_policies
        mock_client.delete_dns_policy.return_value = None

        manager = DNSPolicyManager(mock_client)
        result = await manager.delete_policy('policy-1')

        assert result is True
        mock_client.delete_dns_policy.assert_called_once_with('policy-1')

    def test_get_record_info(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting record info."""
        manager = DNSPolicyManager(mock_client)

        # Test A record
        info = manager.get_record_info(sample_policies[0])
        assert info.policy_id == 'policy-1'
        assert info.domain == 'server.local'
        assert info.record_type == 'A'
        assert info.value == '192.168.1.100'

        # Test AAAA record
        info = manager.get_record_info(sample_policies[2])
        assert info.value == 'fd00::100'

        # Test TXT record
        info = manager.get_record_info(sample_policies[4])
        assert info.value == 'v=DMARC1; p=none'

    @pytest.mark.asyncio
    async def test_get_summary(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting DNS summary."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)
        summary = await manager.get_summary()

        assert summary.total_policies == 5
        assert summary.enabled_policies == 4
        assert summary.disabled_policies == 1
        assert summary.a_records == 2
        assert summary.aaaa_records == 1
        assert summary.cname_records == 1
        assert summary.txt_records == 1

    @pytest.mark.asyncio
    async def test_export_policies(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test exporting policies."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)
        exported = await manager.export_policies()

        assert len(exported) == 5
        assert exported[0]['domain'] == 'server.local'
        assert exported[0]['type'] == 'A'
        assert exported[0]['enabled'] is True

    @pytest.mark.asyncio
    async def test_get_domains_list(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test getting domains list."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)
        domains = await manager.get_domains_list()

        # Unique and sorted
        assert len(domains) == 4  # server.local, nas.local, www.local, _dmarc.local
        assert domains == sorted(domains)

    @pytest.mark.asyncio
    async def test_cache_usage(
        self,
        mock_client: MagicMock,
        sample_policies: list[DNSPolicy],
    ) -> None:
        """Test that cache is used properly."""
        mock_client.list_dns_policies.return_value = sample_policies

        manager = DNSPolicyManager(mock_client)

        # First call should fetch
        await manager.get_all_policies()
        assert mock_client.list_dns_policies.call_count == 1

        # Second call should use cache
        await manager.get_all_policies()
        assert mock_client.list_dns_policies.call_count == 1

        # Force refresh
        await manager.get_all_policies(refresh=True)
        assert mock_client.list_dns_policies.call_count == 2
