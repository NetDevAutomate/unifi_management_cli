"""Issues 031 and 032: the Integration API paths for ACL rules and DNS policies.

Network 10.6.106 answers 404 for the client's old ``/sites/{siteId}/acls`` and
``/sites/{siteId}/dns-policies``. Ubiquiti's Network API reference (v10.6.102) and one guarded
GET on the console both give ``/sites/{siteId}/acl-rules`` and ``/sites/{siteId}/dns/policies``.
These tests pin all five call sites of each resource (list, get, create, update, delete) with
``httpx.MockTransport``, and show the GET-only guard still refuses the writes before any I/O.
Nothing reaches a network.
"""

import httpx
import pytest
from collections.abc import Awaitable, Callable
from pydantic import SecretStr
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.core.utils.readonly import (
    ReadOnlyAsyncTransport,
    ReadOnlyViolation,
    get_only_request_allowed,
)
from unifi_mapper.network.client import UniFiNetworkClient
from unifi_mapper.network.config import NetworkConfig


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
SITE = f'/proxy/network/integrations/v1/sites/{SITE_ID}'
ACL_RULES = f'{SITE}/acl-rules'
DNS_POLICIES = f'{SITE}/dns/policies'

Call = Callable[[UniFiNetworkClient], Awaitable[Any]]


class Recorder(httpx.MockTransport):
    """A fake Integration API: records ``(method, path)``; an empty page or one object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == 'GET' and request.url.path in (ACL_RULES, DNS_POLICIES):
            page = {'offset': 0, 'limit': 200, 'count': 0, 'totalCount': 0, 'data': []}
            return httpx.Response(200, json=page)
        return httpx.Response(200, json={'id': 'x-1'})


def _client(transport: httpx.AsyncBaseTransport) -> UniFiNetworkClient:
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    return UniFiNetworkClient(config, transport=transport)


READS: list[tuple[str, Call, tuple[str, str]]] = [
    ('list_acl_rules', lambda c: c.list_acl_rules(), ('GET', ACL_RULES)),
    ('get_acl_rule', lambda c: c.get_acl_rule('acl-1'), ('GET', f'{ACL_RULES}/acl-1')),
    ('list_dns_policies', lambda c: c.list_dns_policies(), ('GET', DNS_POLICIES)),
    ('get_dns_policy', lambda c: c.get_dns_policy('dns-1'), ('GET', f'{DNS_POLICIES}/dns-1')),
]

WRITES: list[tuple[str, Call, tuple[str, str]]] = [
    ('create_acl_rule', lambda c: c.create_acl_rule('Block lab', 'IPV4'), ('POST', ACL_RULES)),
    (
        'update_acl_rule',
        lambda c: c.update_acl_rule('acl-1', enabled=False),
        ('PUT', f'{ACL_RULES}/acl-1'),
    ),
    ('delete_acl_rule', lambda c: c.delete_acl_rule('acl-1'), ('DELETE', f'{ACL_RULES}/acl-1')),
    (
        'create_dns_policy',
        lambda c: c.create_dns_policy('nas.lab', 'A_RECORD', ipv4_address='192.0.2.5'),
        ('POST', DNS_POLICIES),
    ),
    (
        'update_dns_policy',
        lambda c: c.update_dns_policy('dns-1', enabled=False),
        ('PUT', f'{DNS_POLICIES}/dns-1'),
    ),
    (
        'delete_dns_policy',
        lambda c: c.delete_dns_policy('dns-1'),
        ('DELETE', f'{DNS_POLICIES}/dns-1'),
    ),
]


@pytest.mark.parametrize(('name', 'call', 'expected'), READS, ids=[r[0] for r in READS])
async def test_reads_use_the_served_paths(
    name: str, call: Call, expected: tuple[str, str]
) -> None:
    recorder = Recorder()
    async with _client(recorder) as client:
        await call(client)
    assert recorder.calls == [expected]


@pytest.mark.parametrize(('name', 'call', 'expected'), WRITES, ids=[w[0] for w in WRITES])
async def test_writes_use_the_same_paths_and_the_guard_refuses_them(
    name: str, call: Call, expected: tuple[str, str]
) -> None:
    unguarded = Recorder()
    async with _client(unguarded) as client:
        await call(client)
    assert unguarded.calls == [expected]

    behind_guard = Recorder()
    guard = ReadOnlyAsyncTransport(behind_guard, policy=get_only_request_allowed)
    async with _client(guard) as client:
        with pytest.raises(ReadOnlyViolation) as refused:
            await call(client)
    assert behind_guard.calls == []
    method, path = expected
    assert str(refused.value) == f'refused {method} {path!r}: only GET and HEAD are allowed'
