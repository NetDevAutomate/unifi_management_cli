"""MCP tools for read-only switch-port diagnostics.

Thin async wrappers over :mod:`unifi_mapper.port_diagnostics` and
:mod:`unifi_mapper.port_history`, the same code behind the ``unifi-mapper
ports`` commands. Each tool runs its blocking collector in a worker thread (as
``inspect_switch_port`` does), behind the read-only transport guard, and returns
the report's sanitised JSON. None of these tools can write to the controller:
the guard refuses any write before it leaves the machine.

The controller session (issue 021). Every sync tool borrows one process-wide
``UnifiApiClient`` through :func:`_readonly_sync_client`: built lazily under a lock from
``Credentials.from_env()`` and the ``UNIFI_TIMEOUT`` / ``UNIFI_MAX_RETRIES`` /
``UNIFI_RETRY_DELAY`` settings (issue 087), logged in once, guarded straight after the login
(:class:`_SharedSession`, a ``ReadOnlySession``), and kept until the server's shutdown drain
(:func:`shutdown_shared_sync_session`) logs it out. A client is bound to the credentials and
settings it was built from: when the environment changes, the next call retires it (logged
out once it is idle) and builds a new one. A build that fails leaves nothing behind, so the
next call retries.

Per-call ``request_audit``. The guard appends ``{method, path}`` to the list it was built
with, and ``build_port_diagnostic_bundle`` ships that list as the bundle's ``request_audit``.
With one session for every call, that list is :class:`_CallAudit`: it forwards each append,
and every read, to the collector in :data:`_request_audit`, a ``contextvars.ContextVar`` the
async handler sets just before the thread hop (:func:`_run`; the context is copied into the
worker) and resets with its token when the call ends. A worker the runner's deadline
abandoned keeps its own copy of the context, so its late requests land in its own
collector, never in another call's, and a record already published is a list snapshot.

Re-authentication. When the controller answers a borrowed request with 401, the session
logs in again once (under the client's refresh lock; a concurrent 401 that finds the login
already done does not log in again) and replays the failed request once; the replay's
answer is returned as it is, so there is never a loop. The guard is put back on the client
after any login, the refresh or one the client runs itself.

Concurrency. Worker threads share the one ``requests.Session`` for their GET and POST
reads without a lock. The paths used are safe for that: urllib3's connection pool is
thread-safe; the cookie jar takes its own lock to read and to store cookies; the client's
per-request ``session.headers.update(...)`` writes the same constant values from every
thread (a dict update under the GIL). Only login and refresh, which replace the session,
run under a lock. The read code does not touch anything else on the session.

Errors are raised as :class:`ToolError` with a specific code, so a failure is
never mislabelled by a generic exception handler:

* ``DEVICE_NOT_FOUND``: the switch or device is unknown or ambiguous
* ``INVALID_PORT``: the port does not exist on the switch
* ``PROFILE_NOT_FOUND``: a port profile name or id is unknown
* ``CONFIG_INVALID``: a parameter is out of range
* ``CONTROLLER_UNREACHABLE``: authentication failed
* ``READ_ONLY_VIOLATION``: a collector attempted a write (a bug)
"""

import contextvars
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from loguru import logger
from pydantic import Field
from typing import Annotated, Any, Callable, Iterator, Optional, SupportsIndex, TypeVar
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.readonly import ReadOnlySession, assert_guarded
from unifi_mapper.core.utils.workers import run_blocking


T = TypeVar('T')

# How long the shutdown drain waits for active workers before leaving the session open.
DRAIN_TIMEOUT_S = 2.0
# The login methods that replace ``client.session`` (the same two the read-only guard
# re-wraps after); each is wrapped on the shared client so the guard comes back on top.
_LOGIN_METHODS = ('login', '_perform_login')

# The current call's request collector. Set by :func:`_run` before the thread hop, reset
# with its token when the call ends; None outside any call.
_request_audit: contextvars.ContextVar[list[dict[str, str]] | None] = contextvars.ContextVar(
    'port_diagnostics_request_audit', default=None
)

_NO_COLLECTOR: list[dict[str, str]] = []


class _CallAudit(list[dict[str, str]]):
    """The shared session's audit list: every operation goes to the calling call's collector.

    ``ReadOnlySession`` takes a plain list and appends to it; ``build_port_diagnostic_bundle``
    reads it back as ``list(install_read_only_guard(client, site))``. This list holds nothing
    itself: ``append`` and every read forward to the collector :data:`_request_audit` names in
    the current context, so one guard serves every call and each call sees only its own
    requests. With no collector (a request outside any call, such as the drain's logout) an
    append is dropped; the opt-in ``UNIFI_MCP_REQUEST_AUDIT`` sink still sees the request.
    """

    @staticmethod
    def _current() -> list[dict[str, str]]:
        collector = _request_audit.get()
        return collector if collector is not None else _NO_COLLECTOR

    def append(self, item: dict[str, str]) -> None:
        """Record one request in the current call's collector (none: dropped)."""
        collector = _request_audit.get()
        if collector is not None:
            collector.append(item)

    def __iter__(self) -> Iterator[dict[str, str]]:
        return iter(list(self._current()))

    def __len__(self) -> int:
        return len(self._current())

    def __bool__(self) -> bool:
        return bool(self._current())

    def __getitem__(self, index: SupportsIndex | slice) -> Any:
        return self._current()[index]

    def __eq__(self, other: object) -> bool:
        return list(self._current()) == other

    def __ne__(self, other: object) -> bool:
        return not self == other

    __hash__ = None  # type: ignore[assignment] - a list is unhashable; so is this

    def __repr__(self) -> str:
        return repr(list(self._current()))


@dataclass(eq=False)
class _Record:
    """One shared client: what it was built from, its raw session, its guard, its workers."""

    api: Any
    site: str
    key: tuple[Any, ...]
    raw: Any  # the requests.Session behind the guard; replaced by every login
    guarded: '_SharedSession | None' = None
    generation: int = 0  # bumped by each refresh; a 401 seen before a refresh does not repeat it
    active: int = 0
    retired: bool = False
    closing: bool = False
    # Re-entrant: refresh() holds it across api.login(), whose wrapper takes it again.
    refresh_lock: threading.RLock = field(default_factory=threading.RLock)


class _RawSession:
    """The guard's inner session: whatever ``requests.Session`` the record holds right now.

    Each login (:meth:`UnifiApiClient._perform_login`) builds a new ``requests.Session``. The
    guard object stays the same, so a worker in the middle of a request keeps a valid
    session and the client's ``session`` identity never changes; this indirection points
    the guard at the current one.
    """

    def __init__(self, record: _Record) -> None:
        self._record = record

    @property
    def headers(self) -> Any:
        return self._record.raw.headers

    @property
    def cookies(self) -> Any:
        return self._record.raw.cookies

    @property
    def verify(self) -> Any:
        return self._record.raw.verify

    @verify.setter
    def verify(self, value: Any) -> None:
        self._record.raw.verify = value

    def close(self) -> None:
        self._record.raw.close()

    def get(self, url: Any, **kwargs: Any) -> Any:
        return self._record.raw.get(url, **kwargs)

    def head(self, url: Any, **kwargs: Any) -> Any:
        return self._record.raw.head(url, **kwargs)

    def post(self, url: Any, **kwargs: Any) -> Any:
        return self._record.raw.post(url, **kwargs)

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        return self._record.raw.request(method, url, **kwargs)


class _SharedSession(ReadOnlySession):
    """The read-only guard over the shared session, with one refresh and one replay on a 401.

    A read answered 401 (an expired controller session) logs in again once
    (:meth:`_SharedSyncSession.refresh`) and is sent once more through the guard, so the
    replay is checked and audited like any request; its answer is returned as it is. Writes
    never reach a response: the guard refuses them first.
    """

    handles_reauth = True  # the client's own 401 branches stand down (one owner of the bound)

    def __init__(self, record: _Record, site: str, audit: list[dict[str, str]]) -> None:
        super().__init__(_RawSession(record), site, audit)
        self._record = record

    def _send(self, send: Callable[[], Any]) -> Any:
        record = self._record
        generation = record.generation
        response = send()
        if getattr(response, 'status_code', None) != 401 or record.closing:
            return response
        _SHARED.refresh(record, generation)
        return send()

    def get(self, url: Any, **kwargs: Any) -> Any:
        """Send a GET after the policy check; one refresh and one replay on a 401."""
        parent = super()
        return self._send(lambda: parent.get(url, **kwargs))

    def head(self, url: Any, **kwargs: Any) -> Any:
        """Send a HEAD after the policy check; one refresh and one replay on a 401."""
        parent = super()
        return self._send(lambda: parent.head(url, **kwargs))

    def post(self, url: Any, data: Any = None, json: Any = None, **kwargs: Any) -> Any:
        """Send an allowlisted POST after the policy check; one refresh and one replay on a 401."""
        parent = super()
        return self._send(lambda: parent.post(url, data=data, json=json, **kwargs))

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        """Send an allowed request after the policy check; one refresh and one replay on a 401."""
        parent = super()
        return self._send(lambda: parent.request(method, url, **kwargs))


def _client_settings() -> tuple[Credentials, int, int, float]:
    """The credentials and client settings the environment holds now.

    Raises:
        ToolError: ``AUTHENTICATION_FAILED`` (no controller address) from ``Credentials``;
            ``CONFIG_INVALID`` when a setting is not a number.
    """
    from unifi_mapper.core.utils.redact import redact_text

    creds = Credentials.from_env()
    # The settings UnifiConfig.from_env reads for every config-built client, under the same
    # names and defaults; UnifiApiClient clamps them to the same ranges (issue 087).
    try:
        timeout = int(os.environ.get('UNIFI_TIMEOUT', '10'))
        max_retries = int(os.environ.get('UNIFI_MAX_RETRIES', '3'))
        retry_delay = float(os.environ.get('UNIFI_RETRY_DELAY', '1.0'))
    except ValueError as e:
        raise ToolError(
            message=f'A client setting is not a number: {redact_text(e)}',
            error_code=ErrorCodes.CONFIG_INVALID,
            suggestion='Set UNIFI_TIMEOUT and UNIFI_MAX_RETRIES to whole numbers and '
            'UNIFI_RETRY_DELAY to a number of seconds, or remove them for the defaults.',
        ) from e
    return creds, timeout, max_retries, retry_delay


def _login(api: Any, host: str) -> None:
    """Log the client in, mapping any failure to ``CONTROLLER_UNREACHABLE``."""
    from unifi_mapper.core.utils.redact import redact_text

    suggestion = (
        'Check UNIFI_URL and UNIFI_CONSOLE_API_TOKEN (or UNIFI_USERNAME/UNIFI_PASSWORD). '
        'The account must be local to the controller, not a UniFi Cloud account.'
    )
    try:
        authenticated = api.login()
    except Exception as e:  # noqa: BLE001 - any login failure is an unreachable controller
        raise ToolError(
            message=f'Could not authenticate to the UniFi controller at {host}: {redact_text(e)}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=suggestion,
        ) from e
    if not authenticated:
        raise ToolError(
            message=f'Could not authenticate to the UniFi controller at {host}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=suggestion,
        )


def _adopt_session(record: _Record) -> None:
    """Put the shared guard back on the client after a login replaced its session."""
    session = record.api.session
    if session is record.guarded:
        return
    record.raw = session
    record.api.session = record.guarded


def _publish_session(record: _Record, session: Any) -> None:
    """Receive a freshly authenticated session from the client: swap the raw one, keep the guard.

    ``api.session`` stays ``record.guarded`` throughout; only ``record.raw`` changes, in one
    store, so a worker mid-request finishes on the session it started on and the next request
    from any worker uses the new one. No thread ever sees a raw ``requests.Session``.
    """
    record.raw = session
    if record.api.session is not record.guarded:
        record.api.session = record.guarded


def _guard_after_login(record: _Record, original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a login method: one login at a time, and the guard back however the login ends.

    The lock is the record's ``refresh_lock``, so a worker whose getter found
    ``is_authenticated`` False while :meth:`_SharedSyncSession.refresh` is logging in waits
    for that login and then takes ``login()``'s already-authenticated short-cut, instead of
    logging in beside it (a second session per concurrent worker, and a controller that
    rate-limits logins).
    """

    def login_then_guard(*args: Any, **kwargs: Any) -> Any:
        with record.refresh_lock:
            try:
                return original(*args, **kwargs)
            finally:
                _adopt_session(record)

    return login_then_guard


class _SharedSyncSession:
    """The process's one shared sync client: lazy, locked, guarded, drained at shutdown."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._record: _Record | None = None

    def acquire(self) -> _Record:
        """Return the shared client for one call, building it first if there is none.

        The build (one login) runs under the lock, so concurrent first calls wait for it
        rather than each logging in. A client built from other credentials or settings than
        the environment holds now is retired first.

        Raises:
            ToolError: ``CONTROLLER_UNREACHABLE`` when the login fails or raises;
                ``CONFIG_INVALID`` or ``AUTHENTICATION_FAILED`` for the settings.
        """
        creds, timeout, max_retries, retry_delay = _client_settings()
        key = (creds, timeout, max_retries, retry_delay)
        to_close: _Record | None = None
        with self._cond:
            record = self._record
            if record is not None and record.key != key:
                # Built from other credentials or settings: retire it. An idle one is closed
                # below, after the lock; one with workers is closed by its last release.
                record.retired = True
                if record.active == 0:
                    record.closing = True
                    to_close = record
                record = self._record = None
            if record is None:
                record = self._record = self._build(key, creds, timeout, max_retries, retry_delay)
            record.active += 1
        if to_close is not None:
            self._close(to_close)
        return record

    def release(self, record: _Record) -> None:
        """Mark one call's use of ``record`` over; close a retired client once it is idle."""
        to_close: _Record | None = None
        with self._cond:
            record.active -= 1
            if record.retired and record.active == 0 and not record.closing:
                record.closing = True
                to_close = record
            self._cond.notify_all()
        if to_close is not None:
            self._close(to_close)

    def refresh(self, record: _Record, generation: int) -> None:
        """Log ``record``'s client in again, once per ``generation``, and verify the guard.

        Args:
            record: The shared client that answered 401.
            generation: The record's generation when the refused request was sent; a refresh
                that already happened since then is not repeated.

        Raises:
            ReadOnlyViolation: The guard is no longer on the client after the login.
        """
        with record.refresh_lock:
            if record.generation != generation:
                return
            api = record.api
            api.is_authenticated = False
            try:
                ok = api.login()  # wrapped: the guard comes back whatever happens
            except Exception as e:  # noqa: BLE001 - the replay reports the failure
                logger.warning(
                    'shared controller session: re-login after 401 raised {}', type(e).__name__
                )
                ok = False
            record.generation += 1
            if not ok:
                logger.warning('shared controller session: re-login after 401 failed')
            assert_guarded(api)

    def drain(self, timeout: float = DRAIN_TIMEOUT_S) -> bool:
        """Wait up to ``timeout`` for active workers, then log out and close. Never under one.

        Returns:
            True when the client was closed (or there was none); False when a worker was
            still active at the bound, in which case the session is left open.
        """
        with self._cond:
            record = self._record
            self._record = None
            if record is None:
                return True
            # Retired and closing from here: no new worker takes it, no refresh is tried, and
            # a release during the wait does not close it under the drain.
            record.retired = True
            record.closing = True
            deadline = time.monotonic() + timeout
            while record.active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            if record.active:
                logger.warning(
                    'shared controller session: {} worker(s) still active after {:g} s; '
                    'the session is left open',
                    record.active,
                    timeout,
                )
                record.closing = False  # the last worker's release closes it instead
                return False
        self._close(record)
        return True

    def reset(self) -> None:
        """Forget the shared client without logging out (tests)."""
        with self._cond:
            self._record = None

    @staticmethod
    def _build(
        key: tuple[Any, ...],
        creds: Credentials,
        timeout: int,
        max_retries: int,
        retry_delay: float,
    ) -> _Record:
        from unifi_mapper.api_client import UnifiApiClient

        scheme = 'https' if creds.port != 80 else 'http'
        # Any: the guard replaces ``session`` (typed requests.Session), as the read-only guard
        # installer does.
        api: Any = UnifiApiClient(
            base_url=f'{scheme}://{creds.host}:{creds.port}',
            site=creds.site,
            verify_ssl=creds.verify_ssl,
            username=creds.username,
            password=creds.password,
            api_token=creds.api_token,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        _login(api, creds.host)
        record = _Record(api=api, site=creds.site, key=key, raw=api.session)
        record.guarded = _SharedSession(record, creds.site, _CallAudit())
        api.session = record.guarded
        api._publish_session = lambda session: _publish_session(record, session)
        for name in _LOGIN_METHODS:
            method = getattr(api, name, None)
            if callable(method):
                setattr(api, name, _guard_after_login(record, method))
        return record

    @staticmethod
    def _close(record: _Record) -> None:
        """Log the retired client out (``closing`` was set by the caller, under the lock)."""
        try:
            record.api.logout()
        except Exception as e:  # noqa: BLE001 - a failed logout is logged, never raised
            logger.debug('shared controller session: logout raised {}', type(e).__name__)


_SHARED = _SharedSyncSession()


def shutdown_shared_sync_session(timeout: float = DRAIN_TIMEOUT_S) -> bool:
    """The server's shutdown hook: drain the shared client's workers, then log out.

    Args:
        timeout: How long to wait for active workers before leaving the session open.

    Returns:
        True when the session was closed or there was none; False when it was left open.
    """
    return _SHARED.drain(timeout)


@contextmanager
def _readonly_sync_client() -> Iterator[tuple[Any, str]]:
    """Yield the shared, read-only-guarded ``UnifiApiClient`` and its site for one call."""
    record = _SHARED.acquire()
    try:
        yield record.api, record.site
    finally:
        _SHARED.release(record)


async def _run(fn: Callable[..., T], *args: Any) -> T:
    """Run ``fn`` under :func:`_mapped` in a worker thread with its own request collector.

    The collector is set here, before the thread hop, so the copied context carries it into
    the worker; it is reset with its token when the call ends, however it ends. A worker the
    runner's deadline abandoned keeps its copy of the context and its own collector. The hop
    takes a permit from the MCP server's worker budget (issue 090), so abandoned collectors
    are bounded with the sync handlers, not stacked on anyio's default pool.
    """
    token = _request_audit.set([])
    try:
        return await run_blocking(_mapped, fn, *args)
    finally:
        _request_audit.reset(token)


def _mapped(fn: Callable[..., T], *args: Any) -> T:
    """Run ``fn`` and convert collector failures into specific ToolErrors."""
    from unifi_mapper.core.utils.readonly import ReadOnlyViolation
    from unifi_mapper.diagnostic_reads import PortNotFound, ProfileNotFound, SwitchNotFound

    try:
        return fn(*args)
    except ToolError:
        raise
    except ReadOnlyViolation as e:
        raise ToolError(
            message=f'A controller write was refused by the read-only guard: {e}',
            error_code=ErrorCodes.READ_ONLY_VIOLATION,
            suggestion='This is a bug in the diagnostic tool; nothing was written. Report it.',
        ) from e
    except SwitchNotFound as e:
        raise ToolError(
            message=str(e),
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion='Pass the exact switch name or its MAC address (listed in the message).',
            related_tools=['find_device', 'get_switch_ports'],
        ) from e
    except PortNotFound as e:
        raise ToolError(
            message=str(e),
            error_code=ErrorCodes.INVALID_PORT,
            suggestion='Use a port index listed in the message.',
            related_tools=['get_switch_ports'],
        ) from e
    except ProfileNotFound as e:
        raise ToolError(
            message=str(e),
            error_code=ErrorCodes.PROFILE_NOT_FOUND,
            suggestion='Use a profile name exactly as listed in the message, or its _id.',
        ) from e
    except ValueError as e:
        raise ToolError(message=str(e), error_code=ErrorCodes.CONFIG_INVALID) from e


# ---------------------------------------------------------------------------
# Blocking implementations
# ---------------------------------------------------------------------------


def _switch_ports_sync(switch: str, include_raw: bool) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device
    from unifi_mapper.port_diagnostics import list_switch_ports

    with _readonly_sync_client() as (api, site):
        target, _, _ = resolve_device(api, site, switch)
        return list_switch_ports(api, site, target, include_raw=include_raw).to_json_dict()


def _profile_diff_sync(profile_a: str, profile_b: str) -> dict[str, Any]:
    from unifi_mapper.port_diagnostics import diff_port_profiles

    with _readonly_sync_client() as (api, site):
        return diff_port_profiles(api, site, profile_a, profile_b).to_json_dict()


def _client_history_sync(
    client: str, switch: Optional[str], port: Optional[int]
) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device
    from unifi_mapper.port_diagnostics import get_client_history as collect_client_history

    if port is not None and switch is None:
        raise ValueError('port needs switch: pass the switch the port belongs to')
    with _readonly_sync_client() as (api, site):
        target = resolve_device(api, site, switch)[0] if switch else None
        return collect_client_history(
            api, site, client, switch=target, port_idx=port
        ).to_json_dict()


def _device_events_sync(
    device: str,
    port: Optional[int],
    clients: Optional[list[str]],
    since_days: int,
    max_events: int,
) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device, rows
    from unifi_mapper.port_history import collect_events, validate_event_window

    validate_event_window(since_days, max_events)
    with _readonly_sync_client() as (api, site):
        target, _, _ = resolve_device(api, site, device, device_types=None)
        names = [str(d.get('name')) for d in rows(api.get_devices(site)) if d.get('name')]
        return collect_events(
            api,
            site,
            target,
            port_idx=port,
            client_macs=clients or [],
            since_days=since_days,
            max_events=max_events,
            known_device_names=names,
        ).to_json_dict()


def _recent_events_sync(
    since_hours: int,
    category: Optional[str],
    severity: Optional[str],
    contains: Optional[str],
    max_events: int,
) -> dict[str, Any]:
    from unifi_mapper.port_history import collect_recent_events, validate_recent_window

    validate_recent_window(since_hours, max_events)
    with _readonly_sync_client() as (api, site):
        return collect_recent_events(
            api,
            site,
            since_hours=since_hours,
            category=category,
            severity=severity,
            contains=contains,
            max_events=max_events,
        ).to_json_dict()


def _counter_rates_sync(
    switch: str, port: int, samples: int, interval_seconds: int
) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device
    from unifi_mapper.port_history import sample_port_counters, validate_sampling

    validate_sampling(samples, interval_seconds)
    with _readonly_sync_client() as (api, site):
        target, _, _ = resolve_device(api, site, switch)
        return sample_port_counters(
            api, site, target, port, samples=samples, interval_seconds=interval_seconds
        ).to_json_dict()


def _diagnose_sync(
    switch: str,
    port: int,
    clients: Optional[list[str]],
    compare_profiles: Optional[list[str]],
    since_days: int,
    counter_samples: int,
    max_events: int,
) -> dict[str, Any]:
    from unifi_mapper.port_diagnostics import BundleQuery, build_port_diagnostic_bundle
    from unifi_mapper.port_history import validate_event_window, validate_sampling

    if compare_profiles and len(compare_profiles) != 2:
        raise ValueError('compare_profiles needs exactly two profile names, or none')
    validate_sampling(counter_samples, 100)
    validate_event_window(since_days, max_events)
    query = BundleQuery(
        switch=switch,
        port=port,
        clients=clients or [],
        compare_profiles=compare_profiles or [],
        since_days=since_days,
        counter_samples=counter_samples,
        max_events=max_events,
    )
    with _readonly_sync_client() as (api, site):
        bundle = build_port_diagnostic_bundle(api, site, query, command='mcp diagnose_switch_port')
        return bundle.to_json_dict()


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


async def get_switch_ports(
    switch: Annotated[
        str, Field(description='Switch name, MAC or IP. An exact name or MAC always wins.')
    ],
    include_raw: Annotated[
        bool, Field(description='Include the full sanitised stat/device record')
    ] = False,
) -> dict[str, Any]:
    """List every port on one switch, with the switch's identity. Read-only.

    When to use this tool:
    - Getting an overview of a switch before drilling into one port
    - Comparing a misbehaving port with its neighbours (speed, autoneg, errors)
    - Finding which port a device or LLDP neighbour is on

    What it reports:
    - Device: model, display model, firmware (and pending upgrade, recorded
      only), uptime, state and whether it is informing, system stats, and every
      temperature/fan/power field the controller exposes
    - Per port: name, media, speed, duplex, autoneg, up, STP state, forward
      mode, effective profile and whether it comes from an override, raw
      speed_caps, PoE mode/power, LLDP neighbour resolved to an adopted device,
      clients on the port, error/drop/CRC counters and link-down count

    Args:
        switch: Switch name, MAC or IP.
        include_raw: Include the full sanitised stat/device record.

    Returns:
        SwitchPortsReport as a dict: schema_version, device, ports, errors,
        sanitised_paths.

    Raises:
        ToolError: DEVICE_NOT_FOUND, CONTROLLER_UNREACHABLE or READ_ONLY_VIOLATION.
    """
    return await _run(_switch_ports_sync, switch, include_raw)


async def diff_port_profiles(
    profile_a: Annotated[str, Field(description='First port profile name or _id')],
    profile_b: Annotated[str, Field(description='Second port profile name or _id')],
) -> dict[str, Any]:
    """Diff two port profiles key by key, and list every port using each. Read-only.

    When to use this tool:
    - Two profiles look identical in the UI but ports behave differently
    - Checking what a profile change will alter before applying it in the UI
    - Seeing whether a profile reaches its intended speed on other ports

    What it reports:
    - differences: dotted keys whose values differ, with both values
    - only_in_a / only_in_b: settings present in one profile only
    - metadata_differences: _id, name, site_id and attr_* kept separate
    - network_refs: referenced networks resolved to names and VLANs
    - used_by: every switch port running each profile, with live speed

    Args:
        profile_a: First profile name (exact, case-insensitive) or _id.
        profile_b: Second profile name or _id.

    Returns:
        ProfileDiff as a dict.

    Raises:
        ToolError: PROFILE_NOT_FOUND (the message lists every profile name).
    """
    return await _run(_profile_diff_sync, profile_a, profile_b)


async def get_client_history(
    client: Annotated[
        str, Field(description='Client MAC (any notation), IP, or a name/hostname substring')
    ],
    switch: Annotated[
        Optional[str], Field(description='Switch to check each record against')
    ] = None,
    port: Annotated[
        Optional[int], Field(description='Port to check against (needs switch)')
    ] = None,
) -> dict[str, Any]:
    """Find where the controller places a client, across every client table. Read-only.

    When to use this tool:
    - Confirming a host is really on the switch port you think it is
    - Finding a client's previous ports and link rates after it went offline
    - Explaining a client that shows on two switches

    Reads stat/sta, v2 clients/active, v2 clients/history, rest/user and
    stat/user. With switch and port, matches_target is judged from each
    record's own location fields (sw_mac/uplink_mac, sw_port), independently
    of how the record was found.

    Args:
        client: MAC, IP, or name/hostname substring.
        switch: Optional switch to check against.
        port: Optional port on that switch.

    Returns:
        ClientHistory as a dict: resolved_macs, records (per-source raw records,
        location, matches_target, link rate, network, VLAN, IP, first/last seen),
        on_target_port and per-source status.

    Raises:
        ToolError: DEVICE_NOT_FOUND for an unknown switch; CONFIG_INVALID when
            port is given without switch.
    """
    return await _run(_client_history_sync, client, switch, port)


async def get_device_events(
    device: Annotated[str, Field(description='Device name, MAC or IP (any adopted device)')],
    port: Annotated[
        Optional[int], Field(description='Only flag entries that mention this port')
    ] = None,
    clients: Annotated[
        Optional[list[str]], Field(description='Client MACs to match as well')
    ] = None,
    since_days: Annotated[int, Field(description='How far back to ask, 1-3650 days')] = 365,
    max_events: Annotated[int, Field(description='Keep at most this many matches')] = 200,
) -> dict[str, Any]:
    """Events, alarms, system log and admin audit for a device, port or client. Read-only.

    When to use this tool:
    - Correlating a link problem with what the controller logged (link
      changes, PoE events, disconnects, profile changes by an admin)
    - Finding out how far back the controller keeps history

    Pages stat/event, reads list/alarm and pages the v2 system-log classes
    device-alert, admin-activity, update-alert and client-alert. Every source
    reports status, record count, pages, truncation and the earliest/latest
    timestamps it returned; the earliest is the observed retention. Matches are
    newest first. A system-log 401/403 is reported as unavailable, not fatal.

    Args:
        device: Device name, MAC or IP.
        port: Optional port; entries must also mention the device.
        clients: Optional client MACs to match independently.
        since_days: History window in days.
        max_events: Cap on returned matches.

    Returns:
        EventHistory as a dict: window, match, sources, matched, matched_total,
        returned, truncated.

    Raises:
        ToolError: DEVICE_NOT_FOUND or CONFIG_INVALID.
    """
    return await _run(_device_events_sync, device, port, clients, since_days, max_events)


async def get_recent_events(
    since_hours: Annotated[
        int, Field(description='How far back to read, 1-8760 hours', ge=1, le=8760)
    ] = 24,
    category: Annotated[
        Optional[str],
        Field(
            description='Only this category (system-log category, else event subsystem)',
            max_length=64,
        ),
    ] = None,
    severity: Annotated[
        Optional[str], Field(description='Only this system-log severity', max_length=64)
    ] = None,
    contains: Annotated[
        Optional[str],
        Field(
            description='Only entries whose key, message or record contains this', max_length=128
        ),
    ] = None,
    max_events: Annotated[
        int,
        Field(description='Keep at most this many entries, newest first, 1-1000', ge=1, le=1000),
    ] = 100,
) -> dict[str, Any]:
    """Site-wide events, alarms and system-log entries from the last since_hours. Read-only.

    When to use this tool:
    - "What happened on the network in the last hour?" without naming a device
    - Correlating an outage window with device, client and admin activity
    - Finding admin edits (system-log class admin-activity), which config-object
      creation times do not show

    Reads the sources get_device_events reads (stat/event, list/alarm and the v2 system-log
    classes device-alert, admin-activity, update-alert and client-alert) for the whole
    site. Alarms are filtered to the window here; one without a timestamp is kept. Every
    record has its secret keys removed. Each source reports its status, record count,
    pages and truncation. For one device, port or client, use get_device_events.

    Args:
        since_hours: History window in hours.
        category: Exact category, case-insensitive.
        severity: Exact system-log severity, case-insensitive.
        contains: Case-insensitive text to find in the key, message or record.
        max_events: Cap on returned entries.

    Returns:
        RecentEvents as a dict: window, sources, events, matched_total, returned,
        truncated, errors and sanitised_paths.

    Raises:
        ToolError: CONTROLLER_UNREACHABLE or CONFIG_INVALID.
    """
    return await _run(_recent_events_sync, since_hours, category, severity, contains, max_events)


async def get_port_counter_rates(
    switch: Annotated[str, Field(description='Switch name, MAC or IP')],
    port: Annotated[int, Field(description='Port index on the switch, 1-based')],
    samples: Annotated[int, Field(description='Number of samples, 1-5')] = 2,
    interval_seconds: Annotated[int, Field(description='Seconds between samples, 30-300')] = 100,
) -> dict[str, Any]:
    """Sample one port's error counters and report per-minute rates. Read-only.

    BLOCKS for (samples - 1) x interval_seconds: about 100 s with the defaults.
    Many MCP clients time out after about 60 s, so use samples=1 for a single
    snapshot, or the `unifi-mapper ports counters` CLI for longer sampling.

    Verdicts:
    - ok: the device informed between samples, so the rates are real
    - inconclusive_not_informing: last_seen did not advance; rates withheld
      rather than reported as false zeros
    - counter_reset: uptime or a counter went down (reboot or clear)
    - single_sample: one sample, no rate

    Existing baselines (analyze link-errors --snapshot, the port-counter store)
    and the recorded counter history (analyze link-errors --record) are
    compared, never written: baselines.history gives the recorded window,
    deltas, resets and first_increase, the first sample in which each counter
    rose.

    Args:
        switch: Switch name, MAC or IP.
        port: Port index.
        samples: Number of samples.
        interval_seconds: Seconds between samples.

    Returns:
        CounterTrend as a dict.

    Raises:
        ToolError: DEVICE_NOT_FOUND, INVALID_PORT or CONFIG_INVALID.
    """
    return await _run(_counter_rates_sync, switch, port, samples, interval_seconds)


async def diagnose_switch_port(
    switch: Annotated[
        str, Field(description='Switch name, MAC or IP. An exact name or MAC always wins.')
    ],
    port: Annotated[int, Field(description='Port index on the switch, 1-based')],
    clients: Annotated[
        Optional[list[str]],
        Field(description='Clients (MAC, IP or name) to locate; default is what is on the port'),
    ] = None,
    compare_profiles: Annotated[
        Optional[list[str]], Field(description='Exactly two port profile names or ids to diff')
    ] = None,
    since_days: Annotated[int, Field(description='History window, 1-3650 days')] = 365,
    counter_samples: Annotated[
        int, Field(description='Counter samples, 1-5, 100 s apart. 1 never blocks')
    ] = 1,
    max_events: Annotated[int, Field(description='Keep at most this many history matches')] = 200,
) -> dict[str, Any]:
    """Collect a read-only evidence bundle for one switch port. Read-only.

    When to use this tool:
    - Preparing evidence for a vendor support ticket about a link that will
      not negotiate the expected speed
    - Capturing everything about a port before and after a change

    The bundle contains the switch identity and Network application version,
    the raw port_table entry with negotiation fields and raw speed_caps, the
    full port override and both profile ids side by side, a diff of
    compare_profiles, where the controller places each client, events and
    system log, counter samples, every port on the switch and the Integration
    API's documented port capability (maxSpeedMbps, connector), and the
    port's recorded counter history (counters.baselines.history). It includes
    request_audit (method and path of every request) as proof of read-only
    collection, and sanitised_paths listing the secret fields stripped. Only
    an unknown switch or port is fatal; any other source that fails (for
    example an unknown compare profile, or a system log that needs extra
    permissions) is recorded in errors and the rest is still collected.

    counter_samples > 1 blocks for (counter_samples - 1) x 100 s.

    Args:
        switch: Switch name, MAC or IP.
        port: Port index.
        clients: Clients to locate.
        compare_profiles: Two profiles to diff.
        since_days: History window.
        counter_samples: Counter samples.
        max_events: History match cap.

    Returns:
        PortDiagnosticBundle as a dict.

    Raises:
        ToolError: DEVICE_NOT_FOUND, INVALID_PORT, CONFIG_INVALID,
            CONTROLLER_UNREACHABLE or READ_ONLY_VIOLATION.
    """
    return await _run(
        _diagnose_sync,
        switch,
        port,
        clients,
        compare_profiles,
        since_days,
        counter_samples,
        max_events,
    )
