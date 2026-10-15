"""Issue 036: the Integration API models against Ubiquiti's v10.6.102 reference.

Fixtures here are the shapes the issue quotes from the reference and the live checks: a
device list record with ``state: ONLINE`` and ``features: ["accessPoint"]``; a device detail
whose ``features`` and ``interfaces`` are objects (``interfaces.ports`` as the port
diagnostics read it); an ACL rule with ``portFilter`` and ``metadata.origin``; DNS policies
typed ``A_RECORD`` and friends. Each pins what the old model lost or rejected.
"""

import pytest
from typing import Any
from unifi_mapper.network.acl import ACLManager
from unifi_mapper.network.dns import DNSPolicyManager
from unifi_mapper.network.models import (
    ACLRule,
    ACLTrafficFilter,
    DeviceFeature,
    DeviceInfo,
    DeviceState,
    DNSPolicy,
    DNSRecordType,
)
from unittest.mock import AsyncMock, MagicMock


# --- devices ----------------------------------------------------------------------------------

# The device list, as the live check recorded it for an access point.
AP_LISTED: dict[str, Any] = {
    'id': '00000000-0000-0000-0000-0000000000a1',
    'name': 'Office AP',
    'model': 'U7PRO',
    'macAddress': '02:00:00:00:00:a1',
    'ipAddress': '192.0.2.21',
    'state': 'ONLINE',
    'firmwareVersion': '7.1.90',
    'firmwareUpdatable': False,
    'features': ['accessPoint'],
    'interfaces': ['radios'],
}

# A device detail: ``features`` and ``interfaces`` are objects; ``interfaces.ports`` is the
# shape ``port_diagnostics`` reads and ``tests/fixtures_unifi.py`` serves.
SWITCH_DETAIL: dict[str, Any] = {
    'id': '00000000-0000-0000-0000-0000000000f2',
    'name': 'Rack switch',
    'model': 'USW-Flex-XG',
    'macAddress': '02:00:00:00:00:f2',
    'state': 'ONLINE',
    'features': {'switching': {}, 'accessPoint': None},
    'interfaces': {
        'ports': [
            {
                'idx': 5,
                'state': 'UP',
                'connector': 'RJ45',
                'maxSpeedMbps': 10000,
                'speedMbps': 5000,
            }
        ]
    },
}


class TestDeviceState:
    @pytest.mark.parametrize('value', ['ONLINE', 'OFFLINE', 'PENDING_ADOPTION', 'UPDATING'])
    def test_reference_states_are_members(self, value: str) -> None:
        device = DeviceInfo.model_validate({**AP_LISTED, 'state': value})
        assert device.state is DeviceState(value)

    def test_an_unknown_state_is_kept_as_sent(self) -> None:
        device = DeviceInfo.model_validate({**AP_LISTED, 'state': 'SOMETHING_NEW'})
        assert device.state == 'SOMETHING_NEW'
        assert not isinstance(device.state, DeviceState)


class TestDeviceFeatures:
    def test_the_listed_access_point_validates_and_is_an_access_point(self) -> None:
        device = DeviceInfo.model_validate(AP_LISTED)
        assert device.state is DeviceState.ONLINE
        assert device.features == ['accessPoint']
        assert device.feature_names == ['accessPoint']
        assert (device.is_access_point, device.is_switch, device.is_router) == (True, False, False)

    @pytest.mark.parametrize(
        ('features', 'expected'),
        [
            (['switching'], (True, False, False)),
            (['gateway'], (False, True, False)),
            (['gateway', 'switching', 'accessPoint'], (True, True, True)),
            ([], (False, False, False)),
        ],
        ids=['switching', 'gateway', 'all three', 'none'],
    )
    def test_feature_checks_use_the_reference_names(
        self, features: list[str], expected: tuple[bool, bool, bool]
    ) -> None:
        device = DeviceInfo(features=features)
        assert (device.is_switch, device.is_router, device.is_access_point) == expected

    def test_the_detail_objects_validate_and_keep_their_ports(self) -> None:
        device = DeviceInfo.model_validate(SWITCH_DETAIL)
        assert device.features == {'switching': {}, 'accessPoint': None}
        # A key whose value is null is not a feature the device has.
        assert device.feature_names == ['switching']
        assert (device.is_switch, device.is_access_point) == (True, False)
        assert not isinstance(device.interfaces, list)
        port = device.interfaces.ports[0]
        assert (port.idx, port.state, port.connector) == (5, 'UP', 'RJ45')
        assert (port.max_speed_mbps, port.speed_mbps) == (10000, 5000)


class TestDeviceFeatureEnum:
    """``DeviceFeature`` carries the reference's feature names (issue 082)."""

    def test_the_members_are_the_reference_names(self) -> None:
        # The reference's ``features`` item enum: switching, accessPoint, gateway.
        assert {f.name: f.value for f in DeviceFeature} == {
            'SWITCHING': 'switching',
            'ACCESS_POINT': 'accessPoint',
            'GATEWAY': 'gateway',
        }

    def test_a_member_matches_a_live_device_in_either_shape(self) -> None:
        listed = DeviceInfo.model_validate(AP_LISTED)
        detail = DeviceInfo.model_validate(SWITCH_DETAIL)
        assert DeviceFeature.ACCESS_POINT in listed.feature_names
        assert DeviceFeature.SWITCHING in detail.feature_names
        assert DeviceFeature.ACCESS_POINT not in detail.feature_names
        assert [DeviceFeature(name) for name in listed.feature_names] == [
            DeviceFeature.ACCESS_POINT
        ]

    def test_the_pre_reference_member_names_still_resolve(self) -> None:
        """``SWITCH`` and ``ROUTER`` are aliases, so a caller using them keeps working."""
        assert DeviceFeature.SWITCH is DeviceFeature.SWITCHING
        assert DeviceFeature.ROUTER is DeviceFeature.GATEWAY
        assert DeviceFeature['SWITCH'] is DeviceFeature.SWITCHING
        assert DeviceInfo(features=['gateway']).is_router
        assert DeviceFeature.ROUTER in DeviceInfo(features=['gateway']).feature_names

    def test_detail_keys_the_model_does_not_name_are_kept(self) -> None:
        detail = {**SWITCH_DETAIL, 'interfaces': {'ports': [{'idx': 1, 'somethingNew': 7}]}}
        device = DeviceInfo.model_validate(detail)
        assert not isinstance(device.interfaces, list)
        assert device.interfaces.ports[0].model_extra == {'somethingNew': 7}
        assert device.interfaces.model_dump(by_alias=True, exclude_none=True) == {
            'ports': [{'idx': 1, 'somethingNew': 7}]
        }


# --- ACL rules --------------------------------------------------------------------------------

# One rule shaped as the reference documents it (``tests/mcp/test_network_tool_payloads.py``
# serves the same record), plus the ``portFilter`` key the issue names.
USER_RULE: dict[str, Any] = {
    'type': 'IPV4',
    'id': '00000000-0000-0000-0000-0000000000c1',
    'name': 'Block lab to NAS',
    'enabled': True,
    'action': 'BLOCK',
    'index': 0,
    'metadata': {'origin': 'USER_DEFINED'},
    'protocolFilter': ['TCP'],
    'sourceFilter': {'ipAddressesOrSubnets': ['192.0.2.0/24'], 'portFilter': [22, 443]},
    'destinationFilter': {'ipAddressesOrSubnets': ['192.0.2.5']},
}
DERIVED_RULE: dict[str, Any] = {
    **USER_RULE,
    'id': '00000000-0000-0000-0000-0000000000c2',
    'name': 'Derived',
    'metadata': {'origin': 'DERIVED'},
}


class TestACLRuleReferenceShape:
    def test_port_filter_is_read_from_the_reference_key(self) -> None:
        filter_ = ACLTrafficFilter.model_validate({'portFilter': [22, 443]})
        assert filter_.port_filter == [22, 443]
        assert filter_.model_dump(by_alias=True, exclude_defaults=True) == {
            'portFilter': [22, 443]
        }

    def test_origin_is_read_from_metadata(self) -> None:
        rule = ACLRule.model_validate(USER_RULE)
        assert rule.metadata is not None and rule.metadata.origin == 'USER_DEFINED'
        assert rule.origin == 'USER_DEFINED'
        assert rule.source_filter is not None and rule.source_filter.port_filter == [22, 443]
        assert ACLRule.model_validate(DERIVED_RULE).origin == 'DERIVED'
        assert ACLRule().origin == ''

    def test_the_rule_round_trips_with_the_reference_keys(self) -> None:
        dumped = ACLRule.model_validate(USER_RULE).model_dump(by_alias=True, exclude_defaults=True)
        assert dumped['metadata'] == {'origin': 'USER_DEFINED'}
        assert dumped['sourceFilter']['portFilter'] == [22, 443]
        assert 'origin' not in dumped and 'portsFilter' not in dumped['sourceFilter']


def _acl_client(rules: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.list_acl_rules = AsyncMock(return_value=[ACLRule.model_validate(r) for r in rules])
    client.create_acl_rule = AsyncMock(return_value=ACLRule.model_validate(USER_RULE))
    return client


class TestACLManagerReferenceShape:
    async def test_user_and_system_rules_split_on_metadata_origin(self) -> None:
        manager = ACLManager(_acl_client([USER_RULE, DERIVED_RULE]))
        assert [r.id for r in await manager.get_user_rules()] == [USER_RULE['id']]
        assert [r.id for r in await manager.get_system_rules()] == [DERIVED_RULE['id']]
        summary = await manager.get_acl_summary()
        assert (summary.user_rules, summary.system_rules) == (1, 1)
        assert (summary.rules_with_source_filter, summary.rules_with_destination_filter) == (2, 2)

    async def test_analyze_rule_sees_the_port_filter(self) -> None:
        rule = ACLRule.model_validate({**USER_RULE, 'sourceFilter': {'portFilter': [22]}})
        assert ACLManager(_acl_client([])).analyze_rule(rule).has_source_filter is True

    @pytest.mark.parametrize('create', ['create_block_rule', 'create_allow_rule'])
    async def test_create_helpers_send_the_reference_port_key(self, create: str) -> None:
        client = _acl_client([])
        await getattr(ACLManager(client), create)(
            'Block lab', source_ports=[22], destination_ips=['192.0.2.5'], destination_ports=[443]
        )
        kwargs = client.create_acl_rule.call_args.kwargs
        assert kwargs['source_filter']['portFilter'] == [22]
        assert kwargs['destination_filter']['portFilter'] == [443]
        assert 'portsFilter' not in kwargs['source_filter']


# --- DNS policies -----------------------------------------------------------------------------

REFERENCE_DNS_TYPES = [
    'A_RECORD',
    'AAAA_RECORD',
    'CNAME_RECORD',
    'MX_RECORD',
    'TXT_RECORD',
    'SRV_RECORD',
    'FORWARD_DOMAIN',
]


def _policy(policy_id: str, record_type: str, **fields: Any) -> dict[str, Any]:
    # Shaped as ``tests/mcp/test_network_tool_payloads.py`` serves the reference's A record.
    return {
        'type': record_type,
        'id': policy_id,
        'enabled': True,
        'domain': f'{policy_id}.lab.example',
        'ttlSeconds': 3600,
        **fields,
    }


def _dns_client(policies: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.list_dns_policies = AsyncMock(
        return_value=[DNSPolicy.model_validate(p) for p in policies]
    )
    client.create_dns_policy = AsyncMock(
        return_value=DNSPolicy.model_validate(
            _policy('p-new', 'A_RECORD', ipv4Address='192.0.2.5')
        )
    )
    return client


class TestDNSReferenceTypes:
    def test_the_enum_has_the_reference_types(self) -> None:
        assert [t.value for t in DNSRecordType] == REFERENCE_DNS_TYPES

    async def test_the_summary_counts_the_reference_types(self) -> None:
        policies = [
            _policy('a1', 'A_RECORD', ipv4Address='192.0.2.5'),
            _policy('a2', 'A_RECORD', ipv4Address='192.0.2.6'),
            _policy('a4', 'AAAA_RECORD', ipv6Address='2001:db8::5'),
            _policy('c1', 'CNAME_RECORD', targetDomain='nas.lab.example'),
            _policy('m1', 'MX_RECORD', mailServerDomain='mail.lab.example', priority=10),
            _policy('t1', 'TXT_RECORD', text='v=spf1 -all'),
            _policy('s1', 'SRV_RECORD', serverDomain='sip.lab.example', port=5060),
            _policy('f1', 'FORWARD_DOMAIN', ipAddress='192.0.2.53'),
        ]
        summary = await DNSPolicyManager(_dns_client(policies)).get_summary()
        assert (summary.a_records, summary.aaaa_records, summary.cname_records) == (2, 1, 1)
        assert (summary.mx_records, summary.txt_records, summary.srv_records) == (1, 1, 1)
        # FORWARD_DOMAIN has no counter of its own: it is the one "other" record.
        assert summary.other_records == 1
        assert (
            len(await DNSPolicyManager(_dns_client(policies)).get_policies_by_type('A_RECORD'))
            == 2
        )

    @pytest.mark.parametrize(
        ('create', 'kwargs', 'sent'),
        [
            ('create_a_record', {'ipv4_address': '192.0.2.5'}, 'A_RECORD'),
            ('create_aaaa_record', {'ipv6_address': '2001:db8::5'}, 'AAAA_RECORD'),
        ],
        ids=['A_RECORD', 'AAAA_RECORD'],
    )
    async def test_create_helpers_send_the_reference_type(
        self, create: str, kwargs: dict[str, str], sent: str
    ) -> None:
        client = _dns_client([])
        await getattr(DNSPolicyManager(client), create)('nas.lab.example', **kwargs)
        assert client.create_dns_policy.call_args.kwargs['policy_type'] == sent


class TestDNSPolicyOrigin:
    """``metadata.origin`` on a DNS policy, as on an ACL rule (issue 084)."""

    def test_origin_is_read_from_metadata(self) -> None:
        user = DNSPolicy.model_validate(
            _policy('u1', 'A_RECORD', ipv4Address='192.0.2.5', metadata={'origin': 'USER_DEFINED'})
        )
        derived = DNSPolicy.model_validate(
            _policy('d1', 'A_RECORD', ipv4Address='192.0.2.6', metadata={'origin': 'DERIVED'})
        )
        assert user.metadata is not None and user.metadata.origin == 'USER_DEFINED'
        assert (user.origin, derived.origin) == ('USER_DEFINED', 'DERIVED')

    def test_a_policy_without_metadata_has_no_origin(self) -> None:
        policy = DNSPolicy.model_validate(_policy('n1', 'A_RECORD', ipv4Address='192.0.2.7'))
        assert policy.metadata is None and policy.origin == ''

    def test_an_unknown_origin_is_kept_as_sent(self) -> None:
        policy = DNSPolicy.model_validate(
            _policy('x1', 'A_RECORD', metadata={'origin': 'SOMETHING_NEW'})
        )
        assert policy.origin == 'SOMETHING_NEW'

    def test_the_policy_round_trips_with_the_reference_keys(self) -> None:
        sent = _policy(
            'u1', 'A_RECORD', ipv4Address='192.0.2.5', metadata={'origin': 'USER_DEFINED'}
        )
        dumped = DNSPolicy.model_validate(sent).model_dump(by_alias=True, exclude_defaults=True)
        assert dumped['metadata'] == {'origin': 'USER_DEFINED'}
