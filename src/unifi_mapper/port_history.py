"""Event, alarm, system-log and counter history for one device or switch port.

Two questions a vendor ticket always asks are "what did the controller log
about this link?" and "are errors still climbing?". This module answers both
with read-only queries:

* :func:`collect_events` pages ``stat/event``, reads ``list/alarm`` once and
  pages four v2 system-log classes. Every source reports how many records it
  returned, whether paging was cut short, and the earliest and latest
  timestamps it returned. The earliest timestamp *is* the controller's observed
  retention, so "how far back does it keep history?" is answered by evidence.
* :func:`sample_port_counters` takes N samples of a port's counters an inform
  interval apart and reports per-minute rates with a verdict that refuses to
  report false zeros from a device that has stopped informing.
* :func:`read_counter_baselines` compares against existing baselines on disk.
  It only reads them; it never writes or replaces a baseline.
"""

import json
import re
import time
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any, Callable, Iterable, Iterator, Optional
from unifi_mapper.analysis.port_counter_baseline import (
    PortCounterBaselineStore,
    PortCounterSnapshot,
    default_baseline_path,
    diff_snapshots,
    port_counter_key,
)
from unifi_mapper.core.utils.redact import redact_text, strip_secrets
from unifi_mapper.diagnostic_reads import (
    Collection,
    DiagnosticModel,
    api_path,
    crc_errors,
    epoch_ms,
    find_port_entry,
    int_or_none,
    iso_from_ms,
    load_device,
    local_iso,
    normalise_mac,
    rows,
    str_or_none,
    v2_path,
)


DEFAULT_SINCE_DAYS = 365
DEFAULT_MAX_EVENTS = 500
DEFAULT_MAX_PAGES = 20
STAT_EVENT_PAGE_SIZE = 1000
SYSTEM_LOG_PAGE_SIZE = 100
MAX_SINCE_DAYS = 3650
MAX_EVENTS_LIMIT = 5000

# Same default as `unifi-mapper analyze link-errors`.
DEFAULT_LINK_ERROR_BASELINE = 'reports/link-error-baseline.json'

# Devices inform roughly every 75-90 s (see analysis/device_freshness.py). Sampling
# closer than that reads unchanged counters as false zeros.
MIN_INTERVAL_SECONDS = 30
MAX_INTERVAL_SECONDS = 300
MAX_SAMPLES = 5

# Class-specific filters for the v2 system-log query, copied from Art-of-WiFi
# UniFi-API-client `Client::get_system_log()` (MIT licence,
# https://github.com/Art-of-WiFi/UniFi-API-client), so these queries match a
# client known to work against current Network applications.
SYSTEM_LOG_CLASS_FILTERS: dict[str, dict[str, list[str]]] = {
    'device-alert': {},
    'admin-activity': {
        'activity_keys': [
            'ACCESSED_NETWORK_WEB',
            'ACCESSED_NETWORK_IOS',
            'ACCESSED_NETWORK_ANDROID',
        ],
        'change_keys': [
            'CLIENT',
            'DEVICE',
            'HOTSPOT',
            'INTERNET',
            'NETWORK',
            'PROFILE',
            'ROUTING',
            'SECURITY',
            'SYSTEM',
            'VPN',
            'WIFI',
        ],
    },
    'update-alert': {
        'systemLogDeviceTypes': [
            'GATEWAYS',
            'SWITCHES',
            'ACCESS_POINT',
            'SMART_POWER',
            'BUILDING_TO_BUILDING_BRIDGES',
            'UNIFI_LTE',
        ],
    },
    'client-alert': {
        'clientType': ['GUEST', 'TELEPORT', 'VPN', 'WIRELESS', 'RADIUS', 'WIRED'],
        'guestAuthorizationMethod': [
            'FACEBOOK_SOCIAL_GATEWAY',
            'FREE_TRIAL',
            'GOOGLE_SOCIAL_GATEWAY',
            'NONE',
            'PASSWORD',
            'PAYMENT',
            'RADIUS',
            'VOUCHER',
        ],
    },
}

_TIME_KEYS = ('time', 'timestamp', 'datetime', 'date', 'occurred_at')
_KEY_KEYS = ('key', 'event', 'type', 'category')
_MESSAGE_KEYS = ('msg', 'message', 'title', 'text', 'description')
_PORT_FIELD_KEYS = frozenset({'port', 'sw_port', 'port_idx'})
_TOTAL_KEYS = ('totalElements', 'total_elements', 'total_element_count', 'totalCount', 'total')

COUNTER_KEYS = (
    'rx_bytes',
    'tx_bytes',
    'rx_packets',
    'tx_packets',
    'rx_errors',
    'tx_errors',
    'rx_dropped',
    'tx_dropped',
    'rx_broadcast',
    'tx_broadcast',
    'rx_multicast',
    'tx_multicast',
    'link_down_count',
)
RATE_KEYS = (
    'rx_errors',
    'tx_errors',
    'rx_dropped',
    'tx_dropped',
    'rx_crc_errors',
    'rx_bytes',
    'tx_bytes',
    'link_down_count',
)
_LINK_BASELINE_KEYS = (
    'rx_errors',
    'tx_errors',
    'rx_dropped',
    'tx_dropped',
    'rx_bytes',
    'tx_bytes',
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SourceResult(BaseModel):
    """How one history source answered."""

    status: str = 'ok'  # ok | unavailable | error
    http_status: Optional[int] = None
    records_returned: int = 0
    pages: int = 0
    truncated: bool = False
    earliest: Optional[str] = None
    latest: Optional[str] = None
    matched: int = 0
    error: Optional[str] = None


class EventWindow(BaseModel):
    """The time window that was queried."""

    since: str
    until: str
    since_days: int


class EventMatchCriteria(BaseModel):
    """What an entry was matched against."""

    switch_mac: Optional[str] = None
    switch_id: Optional[str] = None
    switch_name: Optional[str] = None
    port: Optional[int] = None
    client_macs: list[str] = Field(default_factory=lambda: [])


class EventSources(BaseModel):
    """Per-source results."""

    stat_event: SourceResult
    alarms: SourceResult
    system_log: dict[str, SourceResult]


class MatchedEvent(BaseModel):
    """One history entry that mentions the switch, port or a client."""

    source: str
    time: Optional[str] = None
    epoch_ms: Optional[int] = None
    key: Optional[str] = None
    message: Optional[str] = None
    matched_on: list[str]
    switch_matched_by: Optional[str] = None  # mac | id | name (name is the weakest)
    raw: dict[str, Any]


class EventHistory(DiagnosticModel):
    """Events, alarms and system-log entries that mention a device, port or client."""

    window: EventWindow
    match: EventMatchCriteria
    sources: EventSources
    matched: list[MatchedEvent] = Field(default_factory=lambda: [])
    matched_total: int = 0
    returned: int = 0
    truncated: bool = False


class CounterSample(BaseModel):
    """One read of a port's counters."""

    taken_at: str
    epoch: float
    device_last_seen: Optional[int] = None
    device_uptime: Optional[int] = None
    counters: dict[str, Any] = Field(default_factory=lambda: {})


class LinkErrorBaselineView(BaseModel):
    """Comparison against the ``analyze link-errors`` baseline file (read only)."""

    path: str
    found: bool = False
    baseline_timestamp: Optional[str] = None
    device_present: bool = False
    port_present: bool = False
    deltas: dict[str, Optional[int]] = Field(default_factory=lambda: {})
    reboot_detected: Optional[bool] = None
    error: Optional[str] = None


class PortCounterBaselineView(BaseModel):
    """Comparison against the persisted port-counter baseline store (read only)."""

    path: str
    found: bool = False
    key: str
    baseline_timestamp: Optional[str] = None
    delta: dict[str, Any] = Field(default_factory=lambda: {})
    error: Optional[str] = None


class CounterBaselines(BaseModel):
    """Both on-disk baselines."""

    link_error_tracking: LinkErrorBaselineView
    port_counter_baseline: PortCounterBaselineView


class CounterTrend(DiagnosticModel):
    """Counter samples for one port, per-minute rates and a trust verdict."""

    port_idx: int
    interval_seconds: int
    samples: list[CounterSample] = Field(default_factory=lambda: [])
    rates_per_minute: dict[str, Optional[float]] = Field(default_factory=lambda: {})
    rate_basis: Optional[str] = None  # device_last_seen | wall_clock
    elapsed_seconds: Optional[float] = None
    # single_sample | ok | inconclusive_not_informing | counter_reset
    verdict: str = 'single_sample'
    verdict_reason: str = ''
    baselines: Optional[CounterBaselines] = None


# ---------------------------------------------------------------------------
# Event matching
# ---------------------------------------------------------------------------


def validate_event_window(since_days: int, max_events: int) -> None:
    """Raise ValueError unless 1 <= since_days <= 3650 and 1 <= max_events <= 5000."""
    if not 1 <= since_days <= MAX_SINCE_DAYS:
        raise ValueError(f'since_days must be between 1 and {MAX_SINCE_DAYS}, got {since_days}')
    if not 1 <= max_events <= MAX_EVENTS_LIMIT:
        raise ValueError(f'max_events must be between 1 and {MAX_EVENTS_LIMIT}, got {max_events}')


def validate_sampling(samples: int, interval_seconds: int) -> None:
    """Raise ValueError unless 1 <= samples <= 5 and 30 <= interval_seconds <= 300."""
    if not 1 <= samples <= MAX_SAMPLES:
        raise ValueError(f'samples must be between 1 and {MAX_SAMPLES}, got {samples}')
    if not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS:
        raise ValueError(
            f'interval_seconds must be between {MIN_INTERVAL_SECONDS} and '
            f'{MAX_INTERVAL_SECONDS}, got {interval_seconds}'
        )


def _iter_strings(value: Any) -> Iterator[str]:
    """Yield every string value in a nested record (keys are not yielded)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def _port_field_equals(value: Any, port_idx: int) -> bool:
    """Return True if any ``port``/``sw_port``/``port_idx`` field equals ``port_idx``."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _PORT_FIELD_KEYS and not isinstance(item, (dict, list, bool)):
                if str(item).strip() == str(port_idx):
                    return True
            if _port_field_equals(item, port_idx):
                return True
    elif isinstance(value, list):
        return any(_port_field_equals(item, port_idx) for item in value)
    return False


class EventMatcher:
    """Decide whether a history entry mentions the switch, its port, or a client.

    * ``switch``: any value equals the switch MAC or ``_id`` (case-insensitive),
      or contains the switch name. A name hit is ignored when the same text
      contains a *longer* known device name that includes it, so 'USW Flex XG'
      does not match entries about 'Hotel3 USW Flex XG 10G'.
    * ``port``: needs a switch match, then a ``port``/``sw_port``/``port_idx``
      field equal to N, or text matching ``port N`` / ``port #N``. 'Port 15'
      never matches port 5.
    * ``client``: any value equals one of the client MACs.
    """

    def __init__(
        self,
        device: dict[str, Any],
        port_idx: Optional[int] = None,
        client_macs: Iterable[str] = (),
        known_device_names: Iterable[str] = (),
    ) -> None:
        """Build a matcher for one device, optional port and client MACs."""
        self.mac = normalise_mac(device.get('mac'))
        self.device_id = str(device.get('_id') or '').strip().lower() or None
        self.name = str(device.get('name') or '').strip().lower() or None
        self.port_idx = port_idx
        self.client_macs = {m for m in (normalise_mac(c) for c in client_macs) if m}
        name = self.name or ''
        self._shadowing_names = [
            other
            for other in {str(n).strip().lower() for n in known_device_names if n}
            if name and other != name and name in other
        ]
        self._port_re = (
            re.compile(rf'\bport\s*#?\s*{port_idx}\b', re.IGNORECASE)
            if port_idx is not None
            else None
        )

    def _name_hit(self, text: str) -> bool:
        low = text.lower()
        if not self.name or self.name not in low:
            return False
        return not any(other in low for other in self._shadowing_names)

    def match(self, record: dict[str, Any]) -> tuple[list[str], Optional[str]]:
        """Return ``(matched_on, switch_matched_by)`` for one record."""
        strings = list(_iter_strings(record))
        switch_by: Optional[str] = None
        for text in strings:
            if self.mac and normalise_mac(text) == self.mac:
                switch_by = 'mac'
                break
            if self.device_id and text.strip().lower() == self.device_id:
                switch_by = 'id'
                break
        if switch_by is None and any(self._name_hit(text) for text in strings):
            switch_by = 'name'

        matched_on: list[str] = []
        if switch_by:
            matched_on.append('switch')
            port_re = self._port_re
            if self.port_idx is not None and (
                _port_field_equals(record, self.port_idx)
                or (port_re is not None and any(port_re.search(text) for text in strings))
            ):
                matched_on.append('port')
        if self.client_macs and any(normalise_mac(text) in self.client_macs for text in strings):
            matched_on.append('client')
        return matched_on, switch_by


# ---------------------------------------------------------------------------
# Event sources
# ---------------------------------------------------------------------------


def _record_epoch_ms(record: dict[str, Any]) -> Optional[int]:
    for key in _TIME_KEYS:
        value = epoch_ms(record.get(key))
        if value is not None:
            return value
    return None


def _first_text(record: dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and value != '':
            return str(value)
    return None


def _classify_failure(status: Optional[int]) -> str:
    """401/403 (no permission) and 404 (not on this version) are 'unavailable'."""
    return 'unavailable' if status in (401, 403, 404) else 'error'


def _span(result: SourceResult, records: list[dict[str, Any]]) -> None:
    stamps = [t for t in (_record_epoch_ms(r) for r in records) if t is not None]
    if stamps:
        result.earliest = iso_from_ms(min(stamps))
        result.latest = iso_from_ms(max(stamps))


def _total_elements(data: Any) -> Optional[int]:
    if isinstance(data, dict):
        for key in _TOTAL_KEYS:
            total = int_or_none(data.get(key))
            if total is not None:
                return total
    return None


def _read_stat_event(
    client: Any, site: str, ctx: Collection, within_hours: int, max_pages: int
) -> tuple[SourceResult, list[dict[str, Any]]]:
    """Page ``POST stat/event`` newest first. Paging uses ``_start`` / ``_limit``."""
    result = SourceResult()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    path = api_path(client, site, 'stat/event')
    for page in range(max_pages):
        body = {
            '_sort': '-time',
            'within': within_hours,
            'type': None,
            '_start': page * STAT_EVENT_PAGE_SIZE,
            '_limit': STAT_EVENT_PAGE_SIZE,
        }
        fetched = ctx.fetch(
            client, path, section='events.stat_event', method='POST', json_body=body
        )
        result.http_status = fetched.status
        if not fetched.ok:
            if page == 0:
                result.status = _classify_failure(fetched.status)
            else:
                result.truncated = True
            result.error = fetched.error
            break
        page_rows = rows(fetched.data)
        result.pages += 1
        fresh = [r for r in page_rows if str(r.get('_id') or id(r)) not in seen_ids]
        seen_ids.update(str(r.get('_id') or id(r)) for r in fresh)
        records.extend(fresh)
        if len(page_rows) < STAT_EVENT_PAGE_SIZE:
            break
        if not fresh:
            # The controller ignored _start and repeated a page: stop, more may exist.
            result.truncated = True
            break
    else:
        result.truncated = True
    result.records_returned = len(records)
    _span(result, records)
    return result, records


def _read_alarms(client: Any, site: str, ctx: Collection) -> tuple[SourceResult, list[dict]]:
    """Read ``GET list/alarm`` once (the controller does not page it)."""
    result = SourceResult()
    fetched = ctx.fetch(client, api_path(client, site, 'list/alarm'), section='events.alarms')
    result.http_status = fetched.status
    if not fetched.ok:
        result.status = _classify_failure(fetched.status)
        result.error = fetched.error
        return result, []
    records = rows(fetched.data)
    result.pages = 1
    result.records_returned = len(records)
    _span(result, records)
    return result, records


def _read_system_log(
    client: Any,
    site: str,
    ctx: Collection,
    log_class: str,
    since_ms: int,
    until_ms: int,
    max_pages: int,
) -> tuple[SourceResult, list[dict[str, Any]]]:
    """Page one v2 system-log class with ``pageNumber`` / ``pageSize``."""
    result = SourceResult()
    records: list[dict[str, Any]] = []
    path = v2_path(client, site, f'system-log/{log_class}')
    for page in range(max_pages):
        body: dict[str, Any] = {
            'pageNumber': page,
            'pageSize': SYSTEM_LOG_PAGE_SIZE,
            'timestampFrom': since_ms,
            'timestampTo': until_ms,
            **SYSTEM_LOG_CLASS_FILTERS[log_class],
        }
        fetched = ctx.fetch(
            client,
            path,
            section=f'events.system_log.{log_class}',
            method='POST',
            json_body=body,
        )
        result.http_status = fetched.status
        if not fetched.ok:
            if page == 0:
                result.status = _classify_failure(fetched.status)
            else:
                result.truncated = True
            result.error = fetched.error
            break
        page_rows = rows(fetched.data)
        result.pages += 1
        records.extend(page_rows)
        total = _total_elements(fetched.data)
        if len(page_rows) < SYSTEM_LOG_PAGE_SIZE or (total is not None and len(records) >= total):
            break
    else:
        result.truncated = True
    result.records_returned = len(records)
    _span(result, records)
    return result, records


def collect_events(
    client: Any,
    site: str,
    device: dict[str, Any],
    *,
    port_idx: Optional[int] = None,
    client_macs: Iterable[str] = (),
    since_days: int = DEFAULT_SINCE_DAYS,
    max_events: int = DEFAULT_MAX_EVENTS,
    max_pages: int = DEFAULT_MAX_PAGES,
    known_device_names: Iterable[str] = (),
    now: Callable[[], float] = time.time,
    ctx: Optional[Collection] = None,
) -> EventHistory:
    """Collect events, alarms and system-log entries mentioning a device, port or client.

    Args:
        client: Authenticated, read-only-guarded ``UnifiApiClient``.
        site: Site name.
        device: The device record (needs ``mac``, ``_id`` and ``name``).
        port_idx: Port to look for; entries must also mention the device.
        client_macs: Client MACs to look for, independent of the device.
        since_days: How far back to ask for history.
        max_events: Cap on returned matches. The newest are kept.
        max_pages: Page cap per source; hitting it sets ``truncated``.
        known_device_names: Every adopted device name, so a shorter name is not
            matched inside a longer one.
        now: Clock, injectable for tests.
        ctx: Shared collection context. A fresh one is used when omitted.

    Returns:
        The :class:`EventHistory`, matches newest first.

    Raises:
        ValueError: ``since_days`` or ``max_events`` is out of range.
    """
    validate_event_window(since_days, max_events)
    if max_pages < 1:
        raise ValueError(f'max_pages must be at least 1, got {max_pages}')
    ctx = ctx or Collection()
    first_error, first_path = len(ctx.errors), len(ctx.sanitised_paths)
    client_macs = list(client_macs)
    until_ms = int(now() * 1000)
    since_ms = until_ms - since_days * 86_400_000
    matcher = EventMatcher(device, port_idx, client_macs, known_device_names)

    stat_result, stat_records = _read_stat_event(client, site, ctx, since_days * 24, max_pages)
    alarm_result, alarm_records = _read_alarms(client, site, ctx)
    log_results: dict[str, SourceResult] = {}
    batches: list[tuple[str, SourceResult, list[dict[str, Any]], bool]] = [
        ('stat_event', stat_result, stat_records, False),
        (
            'alarms',
            alarm_result,
            alarm_records,
            True,
        ),  # alarms are not window-filtered server-side
    ]
    for log_class in SYSTEM_LOG_CLASS_FILTERS:
        result, records = _read_system_log(
            client, site, ctx, log_class, since_ms, until_ms, max_pages
        )
        log_results[log_class] = result
        batches.append((f'system_log.{log_class}', result, records, False))

    candidates: list[tuple[MatchedEvent, list[str]]] = []
    for source, result, records, filter_window in batches:
        for index, record in enumerate(records):
            clean, removed = strip_secrets(record, f'events.{source}[{index}]')
            matched_on, switch_by = matcher.match(clean)
            if not matched_on:
                continue
            stamp = _record_epoch_ms(clean)
            if filter_window and stamp is not None and not since_ms <= stamp <= until_ms:
                continue
            result.matched += 1
            event = MatchedEvent(
                source=source,
                time=iso_from_ms(stamp),
                epoch_ms=stamp,
                key=_first_text(clean, _KEY_KEYS),
                message=_first_text(clean, _MESSAGE_KEYS),
                matched_on=matched_on,
                switch_matched_by=switch_by,
                raw=clean,
            )
            candidates.append((event, removed))

    candidates.sort(key=lambda item: item[0].epoch_ms or 0, reverse=True)
    kept = candidates[:max_events]
    for _, removed in kept:
        ctx.sanitised_paths.extend(removed)

    return EventHistory(
        window=EventWindow(
            since=iso_from_ms(since_ms) or '',
            until=iso_from_ms(until_ms) or '',
            since_days=since_days,
        ),
        match=EventMatchCriteria(
            switch_mac=matcher.mac,
            switch_id=str_or_none(device.get('_id')),
            switch_name=str_or_none(device.get('name')),
            port=port_idx,
            client_macs=sorted(matcher.client_macs),
        ),
        sources=EventSources(stat_event=stat_result, alarms=alarm_result, system_log=log_results),
        matched=[event for event, _ in kept],
        matched_total=len(candidates),
        returned=len(kept),
        truncated=len(candidates) > len(kept),
        errors=ctx.errors[first_error:],
        sanitised_paths=ctx.sanitised_paths[first_path:],
    )


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


def _counter_values(entry: dict[str, Any]) -> dict[str, Any]:
    values = {key: entry.get(key) for key in COUNTER_KEYS}
    values['rx_crc_errors'] = crc_errors(entry)[0]
    return values


def _take_sample(
    client: Any, site: str, switch: dict[str, Any], port_idx: int, now: Callable[[], float]
) -> CounterSample:
    device = load_device(client, site, switch)
    entry = find_port_entry(device, port_idx)
    taken = now()
    return CounterSample(
        taken_at=local_iso(lambda: taken),
        epoch=taken,
        device_last_seen=int_or_none(device.get('last_seen')),
        device_uptime=int_or_none(device.get('uptime')),
        counters=_counter_values(entry),
    )


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _verdict(samples: list[CounterSample]) -> tuple[str, str]:
    """Classify whether the samples can be trusted for a rate."""
    if len(samples) < 2:
        return 'single_sample', 'one sample only: no rate can be computed'
    for before, after in zip(samples, samples[1:]):
        if (
            before.device_uptime is not None
            and after.device_uptime is not None
            and after.device_uptime < before.device_uptime
        ):
            return 'counter_reset', 'device uptime went down between samples (reboot)'
        for key in RATE_KEYS:
            a, b = _numeric(before.counters.get(key)), _numeric(after.counters.get(key))
            if a is not None and b is not None and b < a:
                return 'counter_reset', f'{key} went down between samples (counters cleared)'
    first, last = samples[0], samples[-1]
    if first.device_last_seen is None or last.device_last_seen is None:
        return 'inconclusive_not_informing', 'device last_seen missing: cannot prove fresh data'
    if last.device_last_seen <= first.device_last_seen:
        return (
            'inconclusive_not_informing',
            'device last_seen did not advance: counters are a stale snapshot, not zero errors',
        )
    return 'ok', 'device informed between samples'


def _rates(
    samples: list[CounterSample],
) -> tuple[dict[str, Optional[float]], Optional[str], Optional[float]]:
    first, last = samples[0], samples[-1]
    if (
        first.device_last_seen is not None
        and last.device_last_seen is not None
        and last.device_last_seen > first.device_last_seen
    ):
        basis, elapsed = 'device_last_seen', float(last.device_last_seen - first.device_last_seen)
    else:
        basis, elapsed = 'wall_clock', last.epoch - first.epoch
    if elapsed <= 0:
        return dict.fromkeys(RATE_KEYS), basis, elapsed
    rates: dict[str, Optional[float]] = {}
    for key in RATE_KEYS:
        a, b = _numeric(first.counters.get(key)), _numeric(last.counters.get(key))
        rates[key] = (
            round((b - a) / (elapsed / 60), 3) if a is not None and b is not None else None
        )
    return rates, basis, round(elapsed, 3)


def read_counter_baselines(
    switch: dict[str, Any],
    port_idx: int,
    current: dict[str, Any],
    current_uptime: Optional[int],
    link_error_baseline_path: str = DEFAULT_LINK_ERROR_BASELINE,
    port_counter_store_path: Optional[Path] = None,
) -> CounterBaselines:
    """Compare current counters with the baselines on disk, reading them only.

    Never calls a ``snapshot_*`` function or ``PortCounterBaselineStore.save``:
    reading a baseline must not replace it.
    """
    device_id = str(switch.get('_id') or '')
    link = LinkErrorBaselineView(path=str(link_error_baseline_path))
    path = Path(link_error_baseline_path)
    if path.exists():
        link.found = True
        try:
            baseline = json.loads(path.read_text(encoding='utf-8'))
            link.baseline_timestamp = str_or_none(baseline.get('timestamp'))
            entry = next(
                (d for d in baseline.get('devices', []) if d.get('device_id') == device_id), None
            )
            if entry is not None:
                link.device_present = True
                previous_uptime = int_or_none(entry.get('uptime'))
                if previous_uptime is not None and current_uptime is not None:
                    link.reboot_detected = current_uptime < previous_uptime
                port = next(
                    (p for p in entry.get('ports', []) if p.get('port_idx') == port_idx), None
                )
                if port is not None:
                    link.port_present = True
                    for key in _LINK_BASELINE_KEYS:
                        now_value, then_value = _numeric(current.get(key)), _numeric(port.get(key))
                        link.deltas[key] = (
                            int(now_value - then_value)
                            if now_value is not None and then_value is not None
                            else None
                        )
        except (OSError, ValueError, AttributeError, TypeError) as e:
            link.error = redact_text(f'{type(e).__name__}: {e}')

    key = port_counter_key(device_id, port_idx)
    store = PortCounterBaselineStore(port_counter_store_path or default_baseline_path())
    stored = PortCounterBaselineView(path=str(store.path), key=key)
    if store.path.exists():
        stored.found = True
        try:
            snapshot = store.load().get(key)
            if snapshot is not None:
                current_snapshot = PortCounterSnapshot(
                    rx_errors=int_or_none(current.get('rx_errors')) or 0,
                    tx_errors=int_or_none(current.get('tx_errors')) or 0,
                    crc_errors=int_or_none(current.get('rx_crc_errors')) or 0,
                    rx_dropped=int_or_none(current.get('rx_dropped')) or 0,
                    tx_dropped=int_or_none(current.get('tx_dropped')) or 0,
                )
                stored.baseline_timestamp = snapshot.timestamp
                delta = diff_snapshots(snapshot, current_snapshot).model_dump(mode='json')
                delta.pop('timestamp', None)
                stored.delta = delta
        except (OSError, ValueError) as e:
            # Pydantic validation errors quote the offending input from the file.
            stored.error = redact_text(f'{type(e).__name__}: {e}')
    return CounterBaselines(link_error_tracking=link, port_counter_baseline=stored)


def sample_port_counters(
    client: Any,
    site: str,
    switch: dict[str, Any],
    port_idx: int,
    *,
    samples: int = 2,
    interval_seconds: int = 100,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    link_error_baseline_path: str = DEFAULT_LINK_ERROR_BASELINE,
    port_counter_store_path: Optional[Path] = None,
    ctx: Optional[Collection] = None,
) -> CounterTrend:
    """Sample one port's counters ``samples`` times, ``interval_seconds`` apart.

    Blocks for ``(samples - 1) * interval_seconds`` seconds.

    Verdicts:
        * ``single_sample``: one sample, so no rate.
        * ``ok``: the device informed between samples, so the rates are real.
        * ``inconclusive_not_informing``: ``last_seen`` did not advance. The
          counters are a stale snapshot, and rates are withheld rather than
          reported as false zeros.
        * ``counter_reset``: uptime or a counter went down (reboot or clear),
          so rates are withheld.

    Raises:
        ValueError: ``samples`` is outside 1-5 or ``interval_seconds`` outside 30-300.
        PortNotFound: The port does not exist on the switch.
    """
    validate_sampling(samples, interval_seconds)
    ctx = ctx or Collection()
    first_error, first_path = len(ctx.errors), len(ctx.sanitised_paths)
    taken: list[CounterSample] = []
    for index in range(samples):
        if index:
            sleep(interval_seconds)
        taken.append(_take_sample(client, site, switch, port_idx, now))

    verdict, reason = _verdict(taken)
    rates: dict[str, Optional[float]] = dict.fromkeys(RATE_KEYS)
    basis: Optional[str] = None
    elapsed: Optional[float] = None
    if len(taken) > 1:
        computed, basis, elapsed = _rates(taken)
        if verdict == 'ok':
            rates = computed

    last = taken[-1]
    baselines = read_counter_baselines(
        switch,
        port_idx,
        last.counters,
        last.device_uptime,
        link_error_baseline_path,
        port_counter_store_path,
    )
    return CounterTrend(
        port_idx=port_idx,
        interval_seconds=interval_seconds,
        samples=taken,
        rates_per_minute=rates,
        rate_basis=basis,
        elapsed_seconds=elapsed,
        verdict=verdict,
        verdict_reason=reason,
        baselines=baselines,
        errors=ctx.errors[first_error:],
        sanitised_paths=ctx.sanitised_paths[first_path:],
    )
