"""Traffic matrix analysis from UniFi report and statistics payloads."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Iterable, Mapping, cast
from unifi_mapper.core.utils.client import UniFiClient


DEFAULT_HIGH_BANDWIDTH_BYTES = 100 * 1024 * 1024 * 1024
DEFAULT_HIGH_BANDWIDTH_BPS = 1_000_000_000

_SOURCE_KEYS = ('src', 'source', 'from', 'src_client', 'source_client')
_DESTINATION_KEYS = ('dst', 'dest', 'destination', 'to', 'dst_client', 'destination_client')
_IP_KEYS = ('ip', 'ip_address', 'address', 'addr')
_MAC_KEYS = ('mac', 'mac_address', 'hwaddr', 'hw_addr')
_NAME_KEYS = ('name', 'hostname', 'host_name', 'display_name', 'client_name')

_SOURCE_IP_FIELDS = (
    'src_ip',
    'source_ip',
    'srcip',
    'ip_src',
    'src_addr',
    'source_address',
    'src_ip_address',
)
_DESTINATION_IP_FIELDS = (
    'dst_ip',
    'dest_ip',
    'destination_ip',
    'dstip',
    'ip_dst',
    'dst_addr',
    'destination_address',
    'dst_ip_address',
)
_SOURCE_MAC_FIELDS = (
    'src_mac',
    'source_mac',
    'srcmac',
    'mac_src',
    'src_mac_address',
)
_DESTINATION_MAC_FIELDS = (
    'dst_mac',
    'dest_mac',
    'destination_mac',
    'dstmac',
    'mac_dst',
    'dst_mac_address',
)
_SOURCE_NAME_FIELDS = ('src_name', 'source_name', 'src_host', 'source_host')
_DESTINATION_NAME_FIELDS = ('dst_name', 'dest_name', 'destination_name', 'dst_host')
_BYTE_FIELDS = (
    'bytes',
    'total_bytes',
    'byte_count',
    'octets',
    'traffic_bytes',
    'usage_bytes',
    'usage',
    'total',
)
_TX_BYTE_FIELDS = ('tx_bytes', 'bytes_tx', 'sent_bytes', 'upload_bytes')
_RX_BYTE_FIELDS = ('rx_bytes', 'bytes_rx', 'received_bytes', 'download_bytes')
_BPS_FIELDS = (
    'bps',
    'bits_per_second',
    'rate_bps',
    'throughput_bps',
    'bandwidth_bps',
)
_TX_BPS_FIELDS = ('tx_bps', 'upload_bps')
_RX_BPS_FIELDS = ('rx_bps', 'download_bps')


class TrafficEndpoint(BaseModel):
    """A normalized traffic endpoint."""

    identifier: str
    ip: str | None = None
    mac: str | None = None
    name: str | None = None


class TrafficFlow(BaseModel):
    """Aggregated traffic between an endpoint pair."""

    endpoint_a: TrafficEndpoint
    endpoint_b: TrafficEndpoint
    total_bytes: int
    samples: int
    max_bps: float | None = None


class TrafficTalker(BaseModel):
    """Endpoint ranked by observed traffic volume."""

    endpoint: TrafficEndpoint
    total_bytes: int
    flow_count: int


class TrafficMatrixRecommendation(BaseModel):
    """Placement recommendation derived from traffic matrix observations."""

    severity: str
    endpoint_a: TrafficEndpoint
    endpoint_b: TrafficEndpoint
    observed_bytes: int
    observed_bps: float | None = None
    recommendation: str


def _empty_flows() -> list[TrafficFlow]:
    return []


def _empty_talkers() -> list[TrafficTalker]:
    return []


def _empty_recommendations() -> list[TrafficMatrixRecommendation]:
    return []


class TrafficMatrixReport(BaseModel):
    """Traffic matrix analysis result."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    records_analyzed: int = 0
    flow_count: int = 0
    total_bytes: int = 0
    top_flows: list[TrafficFlow] = Field(default_factory=_empty_flows)
    top_talkers: list[TrafficTalker] = Field(default_factory=_empty_talkers)
    recommendations: list[TrafficMatrixRecommendation] = Field(
        default_factory=_empty_recommendations
    )


def analyze_traffic_matrix_from_payloads(
    payloads: Iterable[Any],
    *,
    top_n: int = 10,
    high_bandwidth_threshold_bytes: int = DEFAULT_HIGH_BANDWIDTH_BYTES,
    high_bandwidth_threshold_bps: float = DEFAULT_HIGH_BANDWIDTH_BPS,
) -> TrafficMatrixReport:
    """Analyze endpoint-pair traffic from UniFi report/stat payloads.

    The parser is intentionally defensive: UniFi API payloads vary between
    controller versions, report endpoints, and DPI/statistics surfaces. Records
    are considered traffic flows only when both endpoints and byte/rate metrics
    can be extracted.
    """
    pair_totals: dict[tuple[str, str], int] = defaultdict(int)
    pair_samples: dict[tuple[str, str], int] = defaultdict(int)
    pair_max_bps: dict[tuple[str, str], float] = defaultdict(float)
    endpoints: dict[str, TrafficEndpoint] = {}
    talker_totals: dict[str, int] = defaultdict(int)
    talker_flows: dict[str, set[tuple[str, str]]] = defaultdict(set)
    records_analyzed = 0

    for record in _iter_records(payloads):
        source = _extract_endpoint(record, _SOURCE_KEYS)
        destination = _extract_endpoint(record, _DESTINATION_KEYS)
        traffic_bytes = _extract_bytes(record)
        traffic_bps = _extract_bps(record)

        if not source or not destination:
            continue
        if traffic_bytes is None and traffic_bps is None:
            continue

        source_key = _endpoint_key(source)
        destination_key = _endpoint_key(destination)
        if source_key == destination_key:
            continue

        records_analyzed += 1
        endpoints[source_key] = _merge_endpoint(endpoints.get(source_key), source)
        endpoints[destination_key] = _merge_endpoint(endpoints.get(destination_key), destination)

        sorted_pair = sorted((source_key, destination_key))
        pair_key = (sorted_pair[0], sorted_pair[1])
        observed_bytes = traffic_bytes or 0
        pair_totals[pair_key] += observed_bytes
        pair_samples[pair_key] += 1
        if traffic_bps is not None:
            pair_max_bps[pair_key] = max(pair_max_bps[pair_key], traffic_bps)

        talker_totals[source_key] += observed_bytes
        talker_totals[destination_key] += observed_bytes
        talker_flows[source_key].add(pair_key)
        talker_flows[destination_key].add(pair_key)

    flows = [
        TrafficFlow(
            endpoint_a=endpoints[pair_key[0]],
            endpoint_b=endpoints[pair_key[1]],
            total_bytes=total_bytes,
            samples=pair_samples[pair_key],
            max_bps=pair_max_bps[pair_key] or None,
        )
        for pair_key, total_bytes in pair_totals.items()
    ]
    flows.sort(key=lambda flow: (flow.total_bytes, flow.max_bps or 0), reverse=True)

    talkers = [
        TrafficTalker(
            endpoint=endpoints[endpoint_key],
            total_bytes=total_bytes,
            flow_count=len(talker_flows[endpoint_key]),
        )
        for endpoint_key, total_bytes in talker_totals.items()
    ]
    talkers.sort(key=lambda talker: talker.total_bytes, reverse=True)

    recommendations = _build_recommendations(
        flows,
        high_bandwidth_threshold_bytes=high_bandwidth_threshold_bytes,
        high_bandwidth_threshold_bps=high_bandwidth_threshold_bps,
    )

    return TrafficMatrixReport(
        records_analyzed=records_analyzed,
        flow_count=len(flows),
        total_bytes=sum(pair_totals.values()),
        top_flows=flows[:top_n],
        top_talkers=talkers[:top_n],
        recommendations=recommendations,
    )


async def analyze_traffic_matrix(
    payloads: Iterable[Any] | None = None,
    *,
    top_n: int = 10,
    high_bandwidth_threshold_bytes: int = DEFAULT_HIGH_BANDWIDTH_BYTES,
    high_bandwidth_threshold_bps: float = DEFAULT_HIGH_BANDWIDTH_BPS,
) -> TrafficMatrixReport:
    """Collect available UniFi payloads and run traffic matrix analysis.

    Passing ``payloads`` keeps the function pure from the caller perspective and
    is useful for tests or MCP callers that already have report/stat data.
    """
    if payloads is None:
        collected_payloads: list[Any] = []
        async with UniFiClient() as client:
            collected_payloads.append(await client.get_devices())
            collected_payloads.append(await client.get_clients())

            for endpoint in (
                'stat/report/traffic',
                'stat/report/daily.site',
                'stat/report/hourly.site',
                'stat/sta',
            ):
                try:
                    collected_payloads.append(await client.get(client.build_path(endpoint)))
                except Exception:
                    continue
        payloads = collected_payloads

    return analyze_traffic_matrix_from_payloads(
        payloads,
        top_n=top_n,
        high_bandwidth_threshold_bytes=high_bandwidth_threshold_bytes,
        high_bandwidth_threshold_bps=high_bandwidth_threshold_bps,
    )


def _iter_records(payloads: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    for payload in payloads:
        yield from _iter_mapping_records(payload)


def _iter_mapping_records(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        mapping = cast(Mapping[str, Any], payload)
        yield mapping
        for value in mapping.values():
            yield from _iter_mapping_records(value)
    elif isinstance(payload, list | tuple):
        items = cast(Iterable[Any], payload)
        for item in items:
            yield from _iter_mapping_records(item)


def _extract_endpoint(
    record: Mapping[str, Any],
    container_keys: tuple[str, ...],
) -> TrafficEndpoint | None:
    is_source = container_keys == _SOURCE_KEYS
    ip_fields = _SOURCE_IP_FIELDS if is_source else _DESTINATION_IP_FIELDS
    mac_fields = _SOURCE_MAC_FIELDS if is_source else _DESTINATION_MAC_FIELDS
    name_fields = _SOURCE_NAME_FIELDS if is_source else _DESTINATION_NAME_FIELDS

    ip = _first_text(record, ip_fields)
    mac = _first_text(record, mac_fields)
    name = _first_text(record, name_fields)
    generic_value: str | None = None

    for key in container_keys:
        value = _get_case_insensitive(record, key)
        if isinstance(value, Mapping):
            nested = cast(Mapping[str, Any], value)
            ip = ip or _first_text(nested, _IP_KEYS)
            mac = mac or _first_text(nested, _MAC_KEYS)
            name = name or _first_text(nested, _NAME_KEYS)
        elif generic_value is None:
            generic_value = _text_or_none(value)

    identifier = ip or mac or generic_value
    if not identifier:
        return None

    if mac is None and _looks_like_mac(identifier):
        mac = identifier
    if ip is None and _looks_like_ip(identifier):
        ip = identifier

    return TrafficEndpoint(identifier=identifier, ip=ip, mac=mac, name=name)


def _extract_bytes(record: Mapping[str, Any]) -> int | None:
    direct_value = _first_number(record, _BYTE_FIELDS)
    if direct_value is not None:
        return int(direct_value)

    tx_bytes = _first_number(record, _TX_BYTE_FIELDS)
    rx_bytes = _first_number(record, _RX_BYTE_FIELDS)
    if tx_bytes is None and rx_bytes is None:
        return None
    return int((tx_bytes or 0) + (rx_bytes or 0))


def _extract_bps(record: Mapping[str, Any]) -> float | None:
    direct_value = _first_number(record, _BPS_FIELDS)
    if direct_value is not None:
        return direct_value

    tx_bps = _first_number(record, _TX_BPS_FIELDS)
    rx_bps = _first_number(record, _RX_BPS_FIELDS)
    if tx_bps is None and rx_bps is None:
        return None
    return (tx_bps or 0.0) + (rx_bps or 0.0)


def _first_text(record: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _text_or_none(_get_case_insensitive(record, key))
        if value:
            return value
    return None


def _first_number(record: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number_or_none(_get_case_insensitive(record, key))
        if value is not None:
            return value
    return None


def _get_case_insensitive(record: Mapping[str, Any], key: str) -> Any:
    if key in record:
        return record[key]
    key_lower = key.lower()
    for candidate_key, value in record.items():
        if candidate_key.lower() == key_lower:
            return value
    return None


def _text_or_none(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, int | float):
        return str(value)
    return None


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _endpoint_key(endpoint: TrafficEndpoint) -> str:
    return endpoint.identifier.lower()


def _merge_endpoint(
    existing: TrafficEndpoint | None,
    new: TrafficEndpoint,
) -> TrafficEndpoint:
    if existing is None:
        return new
    return TrafficEndpoint(
        identifier=existing.identifier,
        ip=existing.ip or new.ip,
        mac=existing.mac or new.mac,
        name=existing.name or new.name,
    )


def _looks_like_ip(value: str) -> bool:
    parts = value.split('.')
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def _looks_like_mac(value: str) -> bool:
    normalized = value.replace(':', '').replace('-', '').replace('.', '')
    return len(normalized) == 12 and all(char in '0123456789abcdefABCDEF' for char in normalized)


def _build_recommendations(
    flows: list[TrafficFlow],
    *,
    high_bandwidth_threshold_bytes: int,
    high_bandwidth_threshold_bps: float,
) -> list[TrafficMatrixRecommendation]:
    recommendations: list[TrafficMatrixRecommendation] = []
    for flow in flows:
        byte_trigger = flow.total_bytes >= high_bandwidth_threshold_bytes
        rate_trigger = flow.max_bps is not None and flow.max_bps >= high_bandwidth_threshold_bps
        if not byte_trigger and not rate_trigger:
            continue

        observed = _format_bytes(flow.total_bytes)
        rate = f' and peak {_format_bps(flow.max_bps)}' if flow.max_bps else ''
        recommendations.append(
            TrafficMatrixRecommendation(
                severity='high',
                endpoint_a=flow.endpoint_a,
                endpoint_b=flow.endpoint_b,
                observed_bytes=flow.total_bytes,
                observed_bps=flow.max_bps,
                recommendation=(
                    f'Place {flow.endpoint_a.identifier} and {flow.endpoint_b.identifier} '
                    f'on 10G-capable switching/uplinks; observed {observed}{rate} between '
                    'this endpoint pair.'
                ),
            )
        )
    return recommendations


def _format_bytes(value: int) -> str:
    units = ('B', 'KiB', 'MiB', 'GiB', 'TiB')
    size = float(value)
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    return f'{size:.1f} {unit}'


def _format_bps(value: float | None) -> str:
    if value is None:
        return 'unknown'
    units = ('bps', 'Kbps', 'Mbps', 'Gbps')
    size = float(value)
    unit = units[0]
    for unit in units:
        if size < 1000 or unit == units[-1]:
            break
        size /= 1000
    return f'{size:.1f} {unit}'
