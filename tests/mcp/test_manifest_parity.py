"""T2: every shipped manifest entry agrees with its handler (design §4 rules 1-9).

Parametrised over every entry of every manifest present, so new tools are covered with
no edit here. Counts are never pinned except the 7f677f4 name set, which guards against
a tool silently disappearing.
"""

import ast
import importlib
import inspect
import jsonschema
import pytest
import re
import typing
import yaml
from pathlib import Path
from pydantic import BaseModel
from typing import Any
from unifi_mapper.mcp.catalog import annotations_for, build_tool
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.registry import (
    MANIFEST_KEYS,
    ToolMetadata,
    ToolRegistry,
    default_manifests_dir,
)
from unifi_mapper.mcp.runner import ToolRunner


MANIFESTS = default_manifests_dir()
REGISTRY = ToolRegistry(MANIFESTS, strict=True)
ENTRIES = sorted(
    (name, REGISTRY.get_metadata(name))
    for tools in REGISTRY.get_categories().values()
    for name in tools
)
NAMES = [name for name, _ in ENTRIES]
READ_ONLY = [name for name, meta in ENTRIES if meta is not None and not meta.mutates]

# Handlers built without an outputSchema (untyped returns). A new one must be added here
# deliberately; a fixed one must be removed.
NO_OUTPUT_SCHEMA_ALLOWLIST = frozenset({'snapshot_radio_config', 'optimize_radio_channels'})
CLIENT_NAMES = frozenset(
    {'UniFiClient', 'UnifiApiClient', 'NetworkConfig', 'ProtectConfig', 'get_credentials'}
)
SAMPLING_PARAMS = frozenset({'interval_seconds', 'samples', 'counter_samples'})
TOOL_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]{1,128}$')
PROPERTY_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')

NAMES_AT_6ACE7F5 = frozenset(
    """
    analyze_link_quality analyze_mac_table analyze_radio_optimization analyze_traffic_matrix
    apply_radio_optimization apply_stp_changes audit_mtu_consistency audit_power_budget
    audit_sfp_diagnostics audit_stp_guard_recommendations audit_stp_path_costs
    audit_uplink_transparency audit_vlan_coverage calculate_optimal_priorities
    check_device_freshness check_inter_vlan_routing client_trace connectivity_analysis
    create_stp_change_plan detect_foreign_bridges detect_ip_conflicts detect_storms
    detect_stp_config_drift diagnose_switch_port diagnose_vlans diff_port_profiles
    diff_stp_snapshots discover_stp_topology find_device find_ip find_lag_candidates find_mac
    firewall_check format_10g_validation_report_markdown format_stp_report_markdown
    generate_stp_report get_acl_rules get_cameras get_capacity_report get_client_history
    get_clients get_device_events get_dns_policies get_doorbells get_firewall_policies
    get_firewall_zones get_firmware_report get_lights get_networks get_nvr_info
    get_port_counter_rates get_radio_channel_report get_sensors get_switch_ports
    inspect_switch_port monitor_lags network_health_check optimize_radio_channels
    path_analysis performance_analysis restore_radio_config security_audit
    snapshot_radio_config snapshot_stp_topology stp_preflight_simulate_add
    summarise_freshness traceroute validate_10g_expansion_readiness validate_port_profiles
    validate_qos
    """.split()
)


def _meta(name: str) -> ToolMetadata:
    meta = REGISTRY.get_metadata(name)
    assert meta is not None
    return meta


def _handler(meta: ToolMetadata) -> Any:
    return getattr(importlib.import_module(meta.module), meta.handler)


def _signature(meta: ToolMetadata) -> dict[str, inspect.Parameter]:
    params = inspect.signature(_handler(meta), eval_str=True).parameters
    return {
        n: p
        for n, p in params.items()
        if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    }


def _raw_entries() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for path in sorted(MANIFESTS.glob('*.yaml')):
        data = yaml.safe_load(path.read_text())
        out += [(path.stem, name, entry) for name, entry in (data.get('tools') or {}).items()]
    return out


def _contains_model(annotation: Any) -> bool:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return True
    return any(_contains_model(arg) for arg in typing.get_args(annotation))


def _imported_names(module: str) -> set[str]:
    tree = ast.parse(Path(importlib.import_module(module).__file__ or '').read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {alias.name.rsplit('.', 1)[-1] for alias in node.names}
    return names


# ---------------------------------------------------------------------------
# Rules 1-9, one test per rule, parametrised over every entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('name', NAMES)
def test_rule1_handler_imports(name: str) -> None:
    assert callable(_handler(_meta(name)))


@pytest.mark.parametrize('name', NAMES)
def test_rule2_declared_parameters_match_the_signature(name: str) -> None:
    meta = _meta(name)
    signature = _signature(meta)
    required = {n for n, p in signature.items() if p.default is inspect.Parameter.empty}
    if required:
        assert meta.parameters, f'{name} has required parameters {sorted(required)}'
    if not meta.parameters:
        return
    assert set(meta.parameters) == set(signature)
    for param, spec in meta.parameters.items():
        assert bool(spec.get('required')) is (param in required), param


@pytest.mark.parametrize('name', NAMES)
def test_rule3_aliases_are_sound(name: str) -> None:
    meta = _meta(name)
    signature = _signature(meta)
    for alias, canonical in meta.aliases.items():
        assert alias not in signature, alias
        assert alias not in meta.aliases.values(), alias
        assert canonical in signature, canonical


@pytest.mark.parametrize('name', READ_ONLY)
def test_rule4_read_only_handlers_build_valid_schemas(name: str) -> None:
    meta = _meta(name)
    tool = build_tool(_handler(meta), meta)
    jsonschema.Draft202012Validator.check_schema(tool.parameters)
    assert all(PROPERTY_RE.match(p) for p in tool.parameters.get('properties', {}))
    if tool.output_schema is None:
        assert name in NO_OUTPUT_SCHEMA_ALLOWLIST, f'{name} has no outputSchema'
    else:
        assert name not in NO_OUTPUT_SCHEMA_ALLOWLIST, f'{name} gained one; drop it from the list'
        jsonschema.Draft202012Validator.check_schema(tool.output_schema)


def test_rule4_allowlisted_names_still_exist() -> None:
    assert NO_OUTPUT_SCHEMA_ALLOWLIST <= set(READ_ONLY)


@pytest.mark.parametrize('name', READ_ONLY)
def test_rule5_required_model_parameters_mean_pipeline(name: str) -> None:
    meta = _meta(name)
    needs_model = any(
        p.default is inspect.Parameter.empty and _contains_model(p.annotation)
        for p in _signature(meta).values()
    )
    if needs_model:
        assert meta.pipeline, f'{name} needs a model argument: declare pipeline: true'


@pytest.mark.parametrize(('stem', 'name', 'entry'), _raw_entries())
def test_rule6_only_allow_listed_keys(stem: str, name: str, entry: dict[str, Any]) -> None:
    assert set(entry) <= set(MANIFEST_KEYS), f'{stem}.yaml {name}'


def test_rule6_strict_registry_loads_every_manifest() -> None:
    assert len(ToolRegistry(MANIFESTS, strict=True)) == len(_raw_entries())


def test_rule7_names_are_valid_and_unique_across_files() -> None:
    names = [name for _, name, _ in _raw_entries()]
    assert len(names) == len(set(names))
    assert all(TOOL_NAME_RE.match(n) for n in names)


@pytest.mark.parametrize(('stem', 'name', 'entry'), _raw_entries())
def test_rule8_credentials_family(stem: str, name: str, entry: dict[str, Any]) -> None:
    family = entry.get('credentials', 'controller')
    if stem == 'network':
        assert family == 'network_api'
    elif stem == 'protect':
        assert family == 'protect'
    if family == 'none':
        imported = _imported_names(entry['module']) & CLIENT_NAMES
        assert not imported, f'{name} is credentials: none but its module imports {imported}'


@pytest.mark.parametrize('name', NAMES)
def test_rule9_sampling_tools_are_not_idempotent(name: str) -> None:
    meta = _meta(name)
    if SAMPLING_PARAMS & set(_signature(meta)):
        assert meta.idempotent is False, f'{name} samples counters: declare idempotent: false'


def test_named_non_idempotent_and_writes_local_entries() -> None:
    for name in ('get_port_counter_rates', 'diagnose_switch_port', 'check_device_freshness'):
        assert _meta(name).idempotent is False
    assert _meta('snapshot_radio_config').writes_local is True


@pytest.mark.parametrize('name', NAMES)
def test_every_entry_has_an_explicit_title(name: str) -> None:
    raw = {n: e for _, n, e in _raw_entries()}
    assert isinstance(raw[name].get('title'), str) and raw[name]['title']


def test_every_tool_name_from_6ace7f5_is_still_registered() -> None:
    assert len(NAMES_AT_6ACE7F5) == 70
    assert NAMES_AT_6ACE7F5 <= set(NAMES)


# ---------------------------------------------------------------------------
# Every read-only entry reaches its handler through ToolRunner
# ---------------------------------------------------------------------------

GATE_ENV = {
    'UNIFI_URL': 'https://192.0.2.1',
    'UNIFI_CONSOLE_API_TOKEN': 'FAKE-PARITY-CONSOLE-TOKEN',  # pragma: allowlist secret
    'UNIFI_NETWORK_HOST': '192.0.2.1',
    'UNIFI_NETWORK_API_KEY': 'FAKE-PARITY-NETWORK-KEY',  # pragma: allowlist secret
    'UNIFI_NETWORK_SITE_ID': 'site',
    'PROTECT_HOST': '192.0.2.2',
    'PROTECT_USERNAME': 'viewer',
    'PROTECT_PASSWORD': 'FAKE-PARITY-PROTECT-PASS',  # pragma: allowlist secret
}
MINIMAL = {'string': 'x', 'integer': 1, 'number': 1, 'boolean': False, 'array': [], 'object': {}}


def _minimal_args(schema: dict[str, Any]) -> dict[str, Any]:
    """Schema-derived minimal arguments: one plain value per required property."""
    args: dict[str, Any] = {}
    for prop in schema.get('required', []):
        spec = schema['properties'][prop]
        if 'enum' in spec:
            args[prop] = spec['enum'][0]  # a Literal parameter: its first allowed value
            continue
        args[prop] = {} if '$ref' in spec else MINIMAL[spec.get('type', 'object')]
    return args


@pytest.mark.parametrize('name', READ_ONLY)
async def test_every_read_only_entry_reaches_its_handler(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in GATE_ENV.items():
        monkeypatch.setenv(key, value)
    meta = _meta(name)
    module = importlib.import_module(meta.module)
    real = getattr(module, meta.handler)
    received: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        received.append(kwargs)
        return {'reached': True}

    fake.__signature__ = inspect.signature(real, eval_str=True)  # type: ignore[attr-defined]
    fake.__name__ = real.__name__
    monkeypatch.setattr(module, meta.handler, fake)

    runner = ToolRunner(ToolRegistry(MANIFESTS, strict=True), settings=ServerSettings())
    schema = runner.catalog.get(name).parameters
    out = (await runner.run(name, _minimal_args(schema))).structuredContent
    assert out is not None
    assert out.get('error_code') not in {'TOOL_FAILED', 'TOOL_NOT_FOUND'}, out
    if not meta.pipeline:
        assert received, out
        assert out == {'ok': True, 'result': {'reached': True}}
        return
    if not received:
        assert out['error_code'] == 'INVALID_PARAMETERS', out
        assert 'Field required' in out['message'], out
        assert re.search(r'\b[a-z_]+\.[a-z_]+ \(Field required\)', out['message']), out


# ---------------------------------------------------------------------------
# annotations_for (design §2.6 table)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('overrides', 'expected'),
    [
        ({}, (True, False, True, True)),
        ({'open_world': False}, (True, False, True, False)),
        ({'idempotent': False}, (True, False, False, True)),
        ({'writes_local': True}, (False, False, False, True)),
    ],
)
def test_annotations_for_table(overrides: dict[str, Any], expected: tuple[bool, ...]) -> None:
    meta = ToolMetadata('some_tool', 'm', 'h', 'd', 'c', **overrides)
    a = annotations_for(meta)
    assert (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint) == expected
    assert a.title == 'Some Tool'


def test_shipped_annotations_for_the_sampling_and_writing_tools() -> None:
    for name in ('get_port_counter_rates', 'diagnose_switch_port', 'check_device_freshness'):
        assert annotations_for(_meta(name)).idempotentHint is False
    snapshot = annotations_for(_meta('snapshot_radio_config'))
    assert snapshot.readOnlyHint is False and snapshot.idempotentHint is False
    pure = annotations_for(_meta('diff_stp_snapshots'))
    assert pure.openWorldHint is False
