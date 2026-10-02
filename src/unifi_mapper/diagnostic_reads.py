"""Read-only controller fetch helpers shared by the port diagnostic collectors.

Collectors go through :meth:`Collection.fetch`, which never raises on an HTTP or
transport error. It records the failure in ``errors`` and returns a
:class:`FetchResult`, so one failed source never loses the rest of the
evidence. :class:`ReadOnlyViolation` is the exception: it always propagates,
because it means a collector tried to write.

Everything a collector ingests passes through :meth:`Collection.clean`, which
strips secret keys and records the dotted path of each one removed.
"""

import ipaddress
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Any, Callable, Optional
from unifi_mapper.core.utils.coerce import float_or_none, int_or_none
from unifi_mapper.core.utils.readonly import ReadOnlyViolation
from unifi_mapper.core.utils.redact import redact_text, strip_secrets
from unifi_mapper.port_inspect import (
    _api_prefix,
    _normalise_mac,
    _v2_prefix,
    resolve_switch_match,
)
from urllib.parse import urlsplit


SCHEMA_VERSION = 1

# Epoch values at or above this are milliseconds; below it they are seconds. 1e11 ms is
# 1973 and 1e11 s is the year 5138, so no real timestamp is ambiguous.
_MS_THRESHOLD = 1e11


class SwitchNotFound(LookupError):
    """The device query matched nothing, or matched more than one device."""


class PortNotFound(LookupError):
    """The requested port index does not exist on the device."""


class ProfileNotFound(LookupError):
    """A port profile name or id matched no profile, or more than one."""


class SectionError(BaseModel):
    """One source or section that failed while collecting."""

    section: str
    error: str


class DiagnosticModel(BaseModel):
    """Base for every top-level diagnostic report.

    Carries ``schema_version`` plus the failures and stripped-secret paths
    recorded while the report was collected.
    """

    schema_version: int = SCHEMA_VERSION
    errors: list[SectionError] = Field(default_factory=lambda: [])
    sanitised_paths: list[str] = Field(default_factory=lambda: [])

    def to_json_dict(self) -> dict[str, Any]:
        """Dump to JSON-safe data, with a final secret-stripping pass over everything.

        Each section was sanitised when it was built, so the final pass should
        find nothing. Anything it does find is removed and its path appended to
        ``sanitised_paths`` under a ``final:`` prefix.
        """
        data, removed = strip_secrets(self.model_dump(mode='json'))
        if removed:
            data.setdefault('sanitised_paths', []).extend(f'final:{p}' for p in removed)
        return data


@dataclass
class FetchResult:
    """The outcome of one read. ``data`` is parsed JSON when ``ok`` is True."""

    ok: bool
    status: Optional[int] = None
    data: Any = None
    error: Optional[str] = None


@dataclass
class Collection:
    """Accumulates per-source failures and stripped-secret paths during collection."""

    errors: list[SectionError] = field(default_factory=lambda: [])
    sanitised_paths: list[str] = field(default_factory=lambda: [])

    def error(self, section: str, message: object) -> None:
        """Record a failure for ``section``. The message is redacted and truncated."""
        self.errors.append(SectionError(section=section, error=redact_text(message)))

    def clean(self, value: Any, path: str) -> Any:
        """Return ``value`` without secret keys, recording each removed path."""
        cleaned, removed = strip_secrets(value, path)
        self.sanitised_paths.extend(removed)
        return cleaned

    def fetch(
        self,
        client: Any,
        path: str,
        *,
        section: str,
        method: str = 'GET',
        json_body: Any = None,
        params: Optional[dict[str, Any]] = None,
        record_error: bool = True,
    ) -> FetchResult:
        """Read one endpoint, recording a failure under ``section``.

        Args:
            client: Authenticated, guarded ``UnifiApiClient``.
            path: Path below the controller base URL (or an absolute URL).
            section: Name the failure is recorded under.
            method: ``GET`` or ``POST`` (POST only for read-only query endpoints).
            json_body: JSON body for a POST query.
            params: Query-string parameters for a GET.
            record_error: Set False when a failure is expected and handled by the
                caller (for example a 404 that triggers a fallback path).

        Returns:
            The :class:`FetchResult`. Never raises except ReadOnlyViolation.
        """
        result = fetch(client, path, method=method, json_body=json_body, params=params)
        if not result.ok and record_error:
            self.error(section, f'{method} {_strip_host(path)}: {result.error}')
        return result


def fetch(
    client: Any,
    path: str,
    *,
    method: str = 'GET',
    json_body: Any = None,
    params: Optional[dict[str, Any]] = None,
) -> FetchResult:
    """Read one controller endpoint without raising on HTTP or transport errors.

    Raises:
        ReadOnlyViolation: The guard refused the request, or ``method`` is
            neither GET nor POST.
    """
    url = path if path.startswith(('http://', 'https://')) else f'{client.base_url}{path}'
    try:
        if method == 'GET':
            response = client.session.get(url, params=params, timeout=client.timeout)
        elif method == 'POST':
            response = client.session.post(url, json=json_body, timeout=client.timeout)
        else:
            raise ReadOnlyViolation(f'diagnostic reads use GET or POST queries only, not {method}')
    except ReadOnlyViolation:
        raise
    except Exception as e:  # noqa: BLE001 - any transport failure becomes a recorded result
        return FetchResult(ok=False, error=redact_text(f'{type(e).__name__}: {e}'))

    status = getattr(response, 'status_code', None)
    if not isinstance(status, int) or status >= 400:
        body = getattr(response, 'text', '') or ''
        return FetchResult(
            ok=False,
            status=status if isinstance(status, int) else None,
            error=redact_text(f'HTTP {status}: {body}'),
        )
    try:
        data = response.json()
    except Exception as e:  # noqa: BLE001 - a non-JSON body is a recorded failure
        return FetchResult(ok=False, status=status, error=redact_text(f'invalid JSON: {e}'))

    meta = data.get('meta') if isinstance(data, dict) else None
    if isinstance(meta, dict) and meta.get('rc') == 'error':
        return FetchResult(
            ok=False, status=status, data=data, error=redact_text(f'rc=error: {meta.get("msg")}')
        )
    return FetchResult(ok=True, status=status, data=data)


def _strip_host(path: str) -> str:
    """Drop scheme and host from a URL so error messages carry only the path."""
    if path.startswith(('http://', 'https://')):
        return urlsplit(path).path or '/'
    return path


def api_path(client: Any, site: str, suffix: str) -> str:
    """Return a legacy-API path such as ``/proxy/network/api/s/default/stat/device``."""
    return f'{_api_prefix(client, site)}/{suffix.lstrip("/")}'


def v2_path(client: Any, site: str, suffix: str) -> str:
    """Return a v2-API path such as ``/proxy/network/v2/api/site/default/clients/active``."""
    return f'{_v2_prefix(client, site)}/{suffix.lstrip("/")}'


def rows(data: Any) -> list[dict[str, Any]]:
    """Return the record list from a legacy ``{data: [...]}`` envelope or a bare list."""
    if isinstance(data, list):
        items: list[Any] = data
    elif isinstance(data, dict):
        inner = data.get('data')
        items = inner if isinstance(inner, list) else []
    else:
        items = []
    return [r for r in items if isinstance(r, dict)]


def normalise_mac(value: Any) -> Optional[str]:
    """Return a full MAC as lower-case colon hex, or None."""
    return _normalise_mac(value)


def is_ip_address(value: str) -> bool:
    """Return True if ``value`` parses as an IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


# --- scalar coercion (controller types vary by model and firmware) -------------------


# ``int_or_none`` and ``float_or_none`` live in ``core.utils.coerce`` (imported above),
# so modules that must not import this one can share them.


def str_or_none(value: Any) -> Optional[str]:
    """Return a non-empty string form of ``value``, or None."""
    if value is None:
        return None
    text = str(value)
    return text if text else None


def bool_or_none(value: Any) -> Optional[bool]:
    """Return ``value`` if it is a real bool, else None."""
    return value if isinstance(value, bool) else None


def dict_or_none(value: Any) -> Optional[dict[str, Any]]:
    """Return ``value`` if it is a dict, else None."""
    return value if isinstance(value, dict) else None


# --- time --------------------------------------------------------------------------


def epoch_ms(value: Any) -> Optional[int]:
    """Normalise an epoch in seconds or milliseconds, or an ISO-8601 string, to ms."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            return None
        return int(number if number >= _MS_THRESHOLD else number * 1000)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return epoch_ms(float(text))
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    return None


def iso_from_ms(value: Optional[int]) -> Optional[str]:
    """Return an epoch in ms as an ISO-8601 UTC string, or None (also when out of range)."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def iso_from_seconds(value: Any) -> Optional[str]:
    """Return an epoch in seconds as an ISO-8601 UTC string, or None (also when out of range)."""
    seconds = float_or_none(value)
    if seconds is None or seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def local_iso(now: Callable[[], float] = time.time) -> str:
    """Return the current time as ISO-8601 with the local UTC offset."""
    return datetime.fromtimestamp(now()).astimezone().isoformat()


# --- devices and ports ------------------------------------------------------------


def resolve_device(
    client: Any,
    site: str,
    query: str,
    *,
    device_types: Optional[tuple[str, ...]] = ('usw',),
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Resolve a device by exact name, MAC, IP, tokens or substring.

    Raises:
        SwitchNotFound: Nothing matched, or the match was ambiguous. The
            message lists every candidate's name, MAC and model.
    """
    try:
        return resolve_switch_match(client, site, query, device_types=device_types)
    except LookupError as e:
        raise SwitchNotFound(str(e)) from e


def load_device(client: Any, site: str, device: dict[str, Any]) -> dict[str, Any]:
    """Return the full ``stat/device`` record for ``device`` (uncleaned).

    Falls back to the record from the device list when the per-device read
    returns nothing useful (``get_device_details`` returns a stub on failure).
    """
    device_id = device.get('_id')
    details = client.get_device_details(site, device_id) if device_id else {}
    if isinstance(details, dict) and isinstance(details.get('port_table'), list):
        return details
    return device


def port_entries(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the device's ``port_table`` entries that are dicts."""
    table = device.get('port_table')
    return [p for p in table if isinstance(p, dict)] if isinstance(table, list) else []


def find_port_entry(device: dict[str, Any], port_idx: int) -> dict[str, Any]:
    """Return the ``port_table`` entry for ``port_idx``.

    Raises:
        PortNotFound: The device has no such port. The message lists valid ports.
    """
    entries = port_entries(device)
    for entry in entries:
        if int_or_none(entry.get('port_idx')) == port_idx:
            return entry
    valid = sorted(i for i in (int_or_none(e.get('port_idx')) for e in entries) if i is not None)
    raise PortNotFound(
        f'Port {port_idx} not found on {device.get("name")!r} (valid ports: {valid})'
    )


def crc_errors(entry: dict[str, Any]) -> tuple[Any, Optional[str]]:
    """Return ``(value, source_key)`` for a port's receive CRC error counter.

    Mirrors ``link_quality``: ``port_stats.rx_crc_errors`` first, then the
    top-level ``rx_crc_errors``. Returns ``(None, None)`` when neither exists.
    """
    stats = entry.get('port_stats')
    if isinstance(stats, dict) and 'rx_crc_errors' in stats:
        return stats['rx_crc_errors'], 'port_stats.rx_crc_errors'
    if 'rx_crc_errors' in entry:
        return entry['rx_crc_errors'], 'rx_crc_errors'
    return None, None
