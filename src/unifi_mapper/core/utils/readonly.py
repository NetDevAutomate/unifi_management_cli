"""Transport-level read-only guard for the synchronous UniFi API client.

Diagnostic commands reuse helpers (``UnifiApiClient`` methods, ``inspect_port``)
that share a session with code paths able to write. Rather than trusting every
reused helper, :func:`install_read_only_guard` wraps the client's session so a
write is refused *before* any I/O happens:

* ``GET`` and ``HEAD`` are allowed, except for any path with a ``cmd`` or
  ``upd`` segment.
* ``POST`` is allowed only to the read-only query endpoints below. Everything
  under ``rest/``, ``cmd/``, ``upd/`` and ``set/`` is unreachable.
* ``PUT``, ``PATCH``, ``DELETE`` and any other method raise
  :class:`ReadOnlyViolation`.

POST allowlist (anchored after the site prefix, optional ``/proxy/network``):

* legacy ``api/s/{site}/stat/event`` and ``api/s/{site}/list/alarm``
* v2 ``v2/api/site/{site}/system-log/{device-alert,admin-activity,update-alert,client-alert}``
* session teardown ``/api/auth/logout`` and ``/api/logout``

Every request that is sent is appended to an audit list as ``{method, path}``:
no host, query string, headers, cookies or body. Diagnostic output ships that
list as proof that collection was read-only.

The same policy, as the pure :func:`request_allowed`, backs
:class:`ReadOnlyAsyncTransport`, the httpx twin used by the MCP server's shared
async client. Both guards also append ``{"t", "method", "path"}`` JSON lines to
an opt-in file sink set with :func:`configure_request_audit`.

The guard must be installed *after* ``login()``, because ``_perform_login``
replaces ``client.session`` and would silently discard it. Once installed it
survives a later login (for example after ``logout()``): the client's
``login``/``_perform_login`` are wrapped so that whatever session they leave
behind is wrapped again, with the same audit list, whether the login succeeded,
failed or raised. Login traffic itself runs on the fresh session before it is
wrapped, so it is never audited, exactly as for the first login.
"""

import functools
import httpx
import json
import re
import threading
from datetime import UTC, datetime
from loguru import logger
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit


_FORBIDDEN_GET_SEGMENTS = frozenset({'cmd', 'upd'})
_SYSTEM_LOG_CLASSES = ('device-alert', 'admin-activity', 'update-alert', 'client-alert')
# Client methods that may replace ``client.session``, and the marker that lets a
# re-install find the original method instead of stacking wrappers.
_LOGIN_METHODS = ('login', '_perform_login')
_ORIGINAL_LOGIN_ATTR = '_read_only_original_login'
# The async client's own login, allowed by ReadOnlyAsyncTransport and never audited
# (the sync guard is installed after login, so its login is never audited either).
_LOGIN_PATH_RE = re.compile(r'^/api/(?:auth/)?login/?$')

_audit_lock = threading.Lock()
_audit_path: Path | None = None


class ReadOnlyViolation(PermissionError):
    """A request that could change controller state was refused before any I/O."""


@functools.lru_cache(maxsize=32)
def _post_allowlist(site: str) -> tuple[re.Pattern[str], ...]:
    """Return the anchored POST allowlist for one site."""
    s = re.escape(site)
    classes = '|'.join(re.escape(c) for c in _SYSTEM_LOG_CLASSES)
    return (
        re.compile(rf'^(?:/proxy/network)?/api/s/{s}/(?:stat/event|list/alarm)/?$'),
        re.compile(rf'^(?:/proxy/network)?/v2/api/site/{s}/system-log/(?:{classes})/?$'),
        re.compile(r'^/api/auth/logout/?$'),
        re.compile(r'^/api/logout/?$'),
    )


def _normalised_path(method: str, url: object) -> tuple[str, str]:
    """Return ``(decoded_path, query)`` for a URL, refusing path tricks.

    Raises:
        ReadOnlyViolation: The path contains a ``.``/``..`` segment, a backslash
            or a still-encoded character after one round of decoding.
    """
    parts = urlsplit(str(url))
    path = unquote(parts.path)
    segments = path.split('/')
    if '\\' in path or '%' in path or any(seg in ('.', '..') for seg in segments):
        raise ReadOnlyViolation(f'refused {method} {path!r}: path traversal or encoded path')
    return path, parts.query


def request_allowed(method: str, url: object, site: str) -> tuple[bool, str]:
    """Decide whether one request is read-only under the guard's policy. Pure.

    Args:
        method: HTTP method, any case.
        url: Absolute or relative URL (a query string is allowed except on POST).
        site: Site the POST allowlist is anchored to.

    Returns:
        ``(True, decoded_path)`` when allowed, else ``(False, refusal_message)``.
    """
    verb = str(method).upper()
    try:
        path, query = _normalised_path(verb, url)
    except ReadOnlyViolation as e:
        return False, str(e)
    if verb in ('GET', 'HEAD'):
        segments = {seg.lower() for seg in path.split('/') if seg}
        if segments & _FORBIDDEN_GET_SEGMENTS:
            return False, f'refused {verb} {path!r}: cmd/upd endpoints are writes'
    elif verb == 'POST':
        if query or not any(p.match(path) for p in _post_allowlist(site)):
            return False, f'refused POST {path!r}: not on the read-only query allowlist'
    else:
        return False, f'refused {verb} {path!r}: method can change controller state'
    return True, path


def configure_request_audit(path: Path | None) -> None:
    """Set (or clear, with ``None``) the opt-in request audit file for both guards.

    When set, every request a guard lets through is appended as one JSON line
    ``{"t": <UTC ISO time>, "method": ..., "path": ...}``: no host, query string,
    headers, cookies or body.

    Args:
        path: The JSON-lines file to append to, or ``None`` to stop auditing.
    """
    global _audit_path
    if path is not None:
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
    with _audit_lock:
        _audit_path = path


def audit_request(method: str, path: str) -> None:
    """Append one request to the configured audit file, if any.

    A write failure is logged and never fails the request.

    Args:
        method: Upper-case HTTP method.
        path: Decoded request path (no host or query).
    """
    with _audit_lock:
        target = _audit_path
        if target is None:
            return
        line = json.dumps(
            {
                't': datetime.now(UTC).isoformat(timespec='milliseconds'),
                'method': method,
                'path': path,
            }
        )
        try:
            with target.open('a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError as e:
            logger.warning(f'request audit write to {target} failed: {type(e).__name__}')


class ReadOnlySession:
    """A session wrapper that only lets read-only requests through.

    Exposes the subset of the ``requests.Session`` interface the UniFi client
    uses: ``get``, ``head``, ``post``, ``request``, ``headers``, ``cookies``,
    ``verify`` and ``close``. Every other attribute raises ``AttributeError``,
    so code cannot bypass the guard with ``send`` or ``mount``.
    """

    def __init__(self, inner: Any, site: str, audit: list[dict[str, str]]) -> None:
        """Wrap ``inner`` for ``site``, appending sent requests to ``audit``."""
        self._inner = inner
        self._site = site
        self._audit = audit

    # --- pass-through session state ----------------------------------------
    @property
    def audit(self) -> list[dict[str, str]]:
        """Return the live audit list of requests sent through this session."""
        return self._audit

    @property
    def headers(self) -> Any:
        """Return the wrapped session's headers (mutable, as with requests)."""
        return self._inner.headers

    @property
    def cookies(self) -> Any:
        """Return the wrapped session's cookie jar."""
        return self._inner.cookies

    @property
    def verify(self) -> Any:
        """Return the wrapped session's TLS verification setting."""
        return self._inner.verify

    @verify.setter
    def verify(self, value: Any) -> None:
        self._inner.verify = value

    def close(self) -> None:
        """Close the wrapped session."""
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        """Refuse every attribute that is not part of the read-only surface."""
        raise AttributeError(
            f'{type(self).__name__} does not expose {name!r}; only read-only requests are allowed'
        )

    # --- policy -------------------------------------------------------------
    def check(self, method: str, url: object) -> str:
        """Validate one request against the read-only policy and audit it.

        Args:
            method: HTTP method, any case.
            url: Absolute or relative URL.

        Returns:
            The decoded request path that was audited.

        Raises:
            ReadOnlyViolation: The request could change controller state.
        """
        verb = str(method).upper()
        allowed, detail = request_allowed(verb, url, self._site)
        if not allowed:
            raise ReadOnlyViolation(detail)
        self._audit.append({'method': verb, 'path': detail})
        audit_request(verb, detail)
        return detail

    # --- verbs ----------------------------------------------------------------
    def get(self, url: Any, **kwargs: Any) -> Any:
        """Send a GET after the policy check."""
        self.check('GET', url)
        return self._inner.get(url, **kwargs)

    def head(self, url: Any, **kwargs: Any) -> Any:
        """Send a HEAD after the policy check."""
        self.check('HEAD', url)
        return self._inner.head(url, **kwargs)

    def post(self, url: Any, data: Any = None, json: Any = None, **kwargs: Any) -> Any:
        """Send a POST to an allowlisted query endpoint after the policy check."""
        self.check('POST', url)
        return self._inner.post(url, data=data, json=json, **kwargs)

    def put(self, url: Any, *args: Any, **kwargs: Any) -> Any:
        """Refuse a PUT: it always writes controller state."""
        self.check('PUT', url)

    def patch(self, url: Any, *args: Any, **kwargs: Any) -> Any:
        """Refuse a PATCH: it always writes controller state."""
        self.check('PATCH', url)

    def delete(self, url: Any, *args: Any, **kwargs: Any) -> Any:
        """Refuse a DELETE: it always writes controller state."""
        self.check('DELETE', url)

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        """Send an arbitrary-method request only if the policy allows it."""
        verb = str(method).upper()
        self.check(verb, url)
        return self._inner.request(verb, url, **kwargs)


def install_read_only_guard(client: Any, site: str | None = None) -> list[dict[str, str]]:
    """Wrap ``client.session`` in a :class:`ReadOnlySession` and return its audit list.

    Idempotent: a client that is already guarded keeps its guard and audit list.
    The guard also survives a later login: the client's ``login`` and
    ``_perform_login`` are wrapped so that the session they leave behind is
    wrapped again, appending to the same audit list.

    Args:
        client: An authenticated ``UnifiApiClient`` (or compatible object).
        site: Site the POST allowlist is anchored to. Defaults to ``client.site``.

    Returns:
        The live audit list. Each sent request appends ``{method, path}``.

    Raises:
        RuntimeError: The client is not authenticated yet. Installing before
            ``login()`` would be undone when login replaces the session.
    """
    session = client.session
    if isinstance(session, ReadOnlySession):
        return session.audit
    if not getattr(client, 'is_authenticated', False):
        raise RuntimeError(
            'install the read-only guard after login(): login replaces client.session'
        )
    audit: list[dict[str, str]] = []
    guarded_site = site or getattr(client, 'site', 'default')
    client.session = ReadOnlySession(session, guarded_site, audit)
    _keep_guard_across_login(client, guarded_site, audit)
    return audit


def _keep_guard_across_login(client: Any, site: str, audit: list[dict[str, str]]) -> None:
    """Re-wrap ``client.session`` after every call to the client's login methods.

    ``UnifiApiClient._perform_login`` assigns a fresh ``requests.Session`` before
    it authenticates, so any later login would otherwise leave the client
    unguarded and unaudited for the rest of the run. Each login method that the
    client has is replaced, on the instance only, by a wrapper that runs it
    unchanged and then wraps whatever session it left behind. A wrapper from an
    earlier install is unwrapped first, so wrappers never stack.

    Args:
        client: The client whose session was just wrapped.
        site: Site the POST allowlist is anchored to.
        audit: The audit list the re-wrapped session must keep appending to.
    """
    for name in _LOGIN_METHODS:
        method = getattr(client, name, None)
        if callable(method):
            original = getattr(method, '__dict__', {}).get(_ORIGINAL_LOGIN_ATTR, method)
            setattr(client, name, _login_then_guard(original, client, site, audit))


def _login_then_guard(
    original: Callable[..., Any], client: Any, site: str, audit: list[dict[str, str]]
) -> Callable[..., Any]:
    """Return a wrapper that runs ``original``, then guards the session it left behind."""

    def login_then_guard(*args: Any, **kwargs: Any) -> Any:
        """Run the original login, then put the guard back on ``client.session``."""
        try:
            return original(*args, **kwargs)
        finally:
            if not isinstance(client.session, ReadOnlySession):
                client.session = ReadOnlySession(client.session, site, audit)

    setattr(login_then_guard, _ORIGINAL_LOGIN_ATTR, original)
    return login_then_guard


def assert_guarded(client: Any) -> None:
    """Raise if the client's session is no longer behind the read-only guard.

    Raises:
        ReadOnlyViolation: Something assigned ``client.session`` directly,
            bypassing the login methods the guard re-wraps, so further requests
            would be unguarded.
    """
    if not isinstance(getattr(client, 'session', None), ReadOnlySession):
        raise ReadOnlyViolation('the read-only guard is no longer installed on this client')


class ReadOnlyAsyncTransport(httpx.AsyncBaseTransport):
    """An httpx transport that only lets read-only requests reach the controller.

    Allows what :func:`request_allowed` allows, plus ``POST /api/auth/login`` and
    ``POST /api/login`` (the async client's own login, which is not audited). Anything
    else raises :class:`ReadOnlyViolation` before the inner transport sees it, so no
    I/O happens. Allowed requests (other than login) go to the opt-in audit sink.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, site: str) -> None:
        """Wrap ``inner`` for ``site``.

        Args:
            inner: The transport that performs the I/O.
            site: Site the POST allowlist is anchored to.
        """
        self._inner = inner
        self._site = site

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Check the request against the policy, then forward it to the inner transport.

        Raises:
            ReadOnlyViolation: The request could change controller state.
        """
        verb = request.method.upper()
        raw = request.url.raw_path.decode('ascii', errors='replace')
        path_only, _, query = raw.partition('?')
        if verb == 'POST' and not query and _LOGIN_PATH_RE.match(path_only):
            return await self._inner.handle_async_request(request)
        allowed, detail = request_allowed(verb, raw, self._site)
        if not allowed:
            raise ReadOnlyViolation(detail)
        audit_request(verb, detail)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        """Close the inner transport."""
        await self._inner.aclose()
