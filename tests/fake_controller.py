"""A fake UniFi controller behind the real read-only guard, for the July port's tests.

``FakeController`` is an ``httpx.MockTransport``: it answers the console-token login and the
routes it is given, answers anything else 404, and records every request, so a test can
assert that only reads left the host. ``SharedControllerClient`` wraps it in
``ReadOnlyAsyncTransport`` exactly as the MCP server and ``typer_cli._guarded`` do, so a write
would be refused before it reached the mock.
"""

import httpx
import pytest
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.client import SharedControllerClient, use_shared_controller_client


API = '/proxy/network/api/s/default'
V2 = '/proxy/network/v2/api/site/default'
LOGIN = frozenset({('GET', '/api/system'), ('GET', f'{API}/self')})
CREDENTIALS = Credentials(host='192.0.2.1', api_token=FAKE_TOKEN)

Route = Any | Callable[[httpx.Request], Any]


def legacy(data: Any) -> dict[str, Any]:
    """Wrap ``data`` the way the legacy API does (``meta`` plus ``data``)."""
    return {'meta': {'rc': 'ok'}, 'data': data}


class FakeController(httpx.MockTransport):
    """A controller that serves fixed routes and records ``(method, path)`` per request."""

    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = dict(routes)
        self.calls: list[tuple[str, str]] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if request.method == 'GET' and path == '/api/system':
            return httpx.Response(200, json={})
        if request.method == 'GET' and path == f'{API}/self':
            return httpx.Response(200, json=legacy([]))
        if path not in self.routes:
            return httpx.Response(404, json={'meta': {'rc': 'error', 'msg': 'api.err.NotFound'}})
        body = self.routes[path]
        if callable(body):
            body = body(request)
        return body if isinstance(body, httpx.Response) else httpx.Response(200, json=body)

    @property
    def reads(self) -> list[tuple[str, str]]:
        """Every request except the login, in order."""
        return [call for call in self.calls if call not in LOGIN]

    @property
    def methods(self) -> set[str]:
        """The HTTP methods sent, the login included."""
        return {method for method, _ in self.calls}


def shared_client(controller: FakeController) -> SharedControllerClient:
    """The read-only shared client the MCP lifespan and ``_guarded`` would build."""
    return SharedControllerClient(CREDENTIALS, inner_transport=controller)


@asynccontextmanager
async def serving(controller: FakeController) -> AsyncIterator[SharedControllerClient]:
    """Install a read-only shared client over ``controller`` for ``UniFiClient()`` to borrow."""
    shared = shared_client(controller)
    try:
        with use_shared_controller_client(shared):
            yield shared
    finally:
        await shared.aclose()


def route_cli(monkeypatch: pytest.MonkeyPatch, controller: FakeController) -> None:
    """Make every CLI command's ``_guarded`` holder use ``controller``; load no config."""
    from unifi_mapper import typer_cli

    monkeypatch.setattr(typer_cli, '_shared_client_factory', lambda: shared_client(controller))
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
