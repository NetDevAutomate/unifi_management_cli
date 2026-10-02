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

The guard must be installed *after* ``login()``, because ``_perform_login``
replaces ``client.session`` and would silently discard it.
"""

import re
from typing import Any
from urllib.parse import unquote, urlsplit


_FORBIDDEN_GET_SEGMENTS = frozenset({'cmd', 'upd'})
_SYSTEM_LOG_CLASSES = ('device-alert', 'admin-activity', 'update-alert', 'client-alert')


class ReadOnlyViolation(PermissionError):
    """A request that could change controller state was refused before any I/O."""


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
        self._post_allowed = _post_allowlist(site)

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
        path, query = _normalised_path(verb, url)
        if verb in ('GET', 'HEAD'):
            segments = {seg.lower() for seg in path.split('/') if seg}
            if segments & _FORBIDDEN_GET_SEGMENTS:
                raise ReadOnlyViolation(f'refused {verb} {path!r}: cmd/upd endpoints are writes')
        elif verb == 'POST':
            if query or not any(p.match(path) for p in self._post_allowed):
                raise ReadOnlyViolation(
                    f'refused POST {path!r}: not on the read-only query allowlist'
                )
        else:
            raise ReadOnlyViolation(f'refused {verb} {path!r}: method can change controller state')
        self._audit.append({'method': verb, 'path': path})
        return path

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
    client.session = ReadOnlySession(session, site or getattr(client, 'site', 'default'), audit)
    return audit


def assert_guarded(client: Any) -> None:
    """Raise if the client's session is no longer behind the read-only guard.

    Raises:
        ReadOnlyViolation: Something replaced ``client.session`` (for example a
            re-login), so further requests would be unguarded.
    """
    if not isinstance(getattr(client, 'session', None), ReadOnlySession):
        raise ReadOnlyViolation('the read-only guard is no longer installed on this client')
