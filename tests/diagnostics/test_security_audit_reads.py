"""`security_audit` reads the rogue-AP list from the endpoint that exists.

Found by running the new `diagnose security` command against a live controller: the audit
asked for ``rest/rogueap``, which UniFi Network answers with ``400 api.err.InvalidObject``,
so the tool failed on every call. The passive list is ``stat/rogueap``, the endpoint
``UniFiClient.get_rogue_aps`` (and `analyze neighbours`) already use.
"""

import importlib
from typing import Any


module = importlib.import_module('unifi_mapper.diagnostics.security_audit')


class FakeClient:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.rogue_calls = 0

    async def __aenter__(self) -> 'FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def build_path(self, endpoint: str) -> str:
        return f'/proxy/network/api/s/default/{endpoint}'

    async def get(self, path: str) -> list[dict[str, Any]]:
        self.paths.append(path)
        if path.endswith('rest/rogueap'):
            raise RuntimeError('HTTP 400: api.err.InvalidObject')
        return []

    async def get_rogue_aps(self) -> list[dict[str, Any]]:
        self.rogue_calls += 1
        return []


async def test_the_audit_reads_rogue_aps_from_the_passive_endpoint(monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(module, 'UniFiClient', lambda: fake)
    report = await module.security_audit()
    assert fake.rogue_calls == 1
    assert not any(p.endswith('rest/rogueap') for p in fake.paths), fake.paths
    assert report.total_devices == 0 and report.rogue_aps == []
