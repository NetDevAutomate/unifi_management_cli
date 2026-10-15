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
