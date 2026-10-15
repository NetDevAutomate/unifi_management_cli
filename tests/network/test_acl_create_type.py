"""The ACL create helpers send a ``type`` the reference accepts (issue 083).

Ubiquiti's Network API reference (v10.6.102) makes an ACL rule's ``type`` a discriminator with
two values, ``IPV4`` and ``MAC``; ``USER`` is a value of ``metadata.origin``, another field.
These tests drive the real ``UniFiNetworkClient`` over a mock transport and read the body the
helpers would POST.
"""

from __future__ import annotations

import httpx
import json
import pytest
from pydantic import SecretStr
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.network.acl import ACLManager
from unifi_mapper.network.client import UniFiNetworkClient
from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.network.models import ACLProtocol


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
ACL_RULES = f'/proxy/network/integration/v1/sites/{SITE_ID}/acl-rules'
REFERENCE_ACL_TYPES = {'IPV4', 'MAC'}


class CreateRecorder(httpx.MockTransport):
    """Answers the probe and records each ACL-rule POST body."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('/v1/info'):
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        assert (request.method, request.url.path) == ('POST', ACL_RULES)
        body = json.loads(request.content)
        self.bodies.append(body)
        return httpx.Response(200, json={**body, 'id': 'r-new', 'index': 0})


@pytest.mark.parametrize('create', ['create_block_rule', 'create_allow_rule'])
async def test_the_default_rule_type_is_ipv4(create: str) -> None:
    recorder = CreateRecorder()
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    async with UniFiNetworkClient(config, transport=recorder) as client:
        await getattr(ACLManager(client), create)('Block lab', protocols=[ACLProtocol.TCP])

    [body] = recorder.bodies
    assert body['type'] == 'IPV4'
    assert body['type'] in REFERENCE_ACL_TYPES


async def test_an_explicit_rule_type_is_sent_as_given() -> None:
    recorder = CreateRecorder()
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    async with UniFiNetworkClient(config, transport=recorder) as client:
        await ACLManager(client).create_block_rule('Block lab', rule_type='MAC')

    assert [b['type'] for b in recorder.bodies] == ['MAC']


# --- issue 094: the per-side filters are typed, never empty, and MACs never ride an IPV4 rule


async def _create(create: str, **kwargs: Any) -> dict[str, Any]:
    recorder = CreateRecorder()
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    async with UniFiNetworkClient(config, transport=recorder) as client:
        await getattr(ACLManager(client), create)('Block lab', **kwargs)
    [body] = recorder.bodies
    return body


@pytest.mark.parametrize('create', ['create_block_rule', 'create_allow_rule'])
async def test_an_ip_filter_is_typed_and_carries_only_the_lists_it_has(create: str) -> None:
    body = await _create(create, source_ips=['192.0.2.0/24'], destination_ports=[443])
    assert body['sourceFilter'] == {
        'type': 'IP_ADDRESSES_OR_SUBNETS',
        'ipAddressesOrSubnets': ['192.0.2.0/24'],
    }
    assert body['destinationFilter'] == {'type': 'PORTS', 'portFilter': [443]}


@pytest.mark.parametrize('create', ['create_block_rule', 'create_allow_rule'])
async def test_ips_with_ports_keep_the_address_type_and_both_lists(create: str) -> None:
    body = await _create(create, source_ips=['192.0.2.5'], source_ports=[22])
    assert body['sourceFilter'] == {
        'type': 'IP_ADDRESSES_OR_SUBNETS',
        'ipAddressesOrSubnets': ['192.0.2.5'],
        'portFilter': [22],
    }
    assert 'destinationFilter' not in body or body['destinationFilter'] is None


@pytest.mark.parametrize('create', ['create_block_rule', 'create_allow_rule'])
async def test_no_filter_inputs_means_no_filter_at_all(create: str) -> None:
    body = await _create(create, protocols=[ACLProtocol.TCP])
    assert body.get('sourceFilter') is None and body.get('destinationFilter') is None
    for side in ('sourceFilter', 'destinationFilter'):
        assert body.get(side) != {}, 'an empty filter object is refused by the reference'


async def test_macs_are_refused_on_an_ipv4_rule_before_any_request() -> None:
    recorder = CreateRecorder()
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    async with UniFiNetworkClient(config, transport=recorder) as client:
        with pytest.raises(ValueError, match='MAC'):
            await ACLManager(client).create_block_rule(
                'Block lab', source_macs=['02:00:00:00:00:01']
            )
    assert recorder.bodies == []
