"""Every pipeline tool runs through execute_tool when fed the JSON form of its model inputs.

Regression (code-review F7): the parity net only showed the 11 pipeline entries validate
(their schema-derived minimal arguments are ``{}``, so the call stops at
``INVALID_PARAMETERS``); none was ever run with a valid model. Here each model family
is built by the real pure functions, dumped to JSON as a client would send it, sent
through ``server.execute_tool``, and the result compared with calling the handler
directly. No controller is contacted: these handlers only transform their inputs.
"""

import asyncio
import importlib
import json
import pytest
from pathlib import Path
from typing import Any
from unifi_mapper.analysis.stp_change_plan import create_stp_change_plan
from unifi_mapper.analysis.stp_drift import detect_stp_config_drift
from unifi_mapper.analysis.stp_guard import audit_stp_guard_recommendations
from unifi_mapper.analysis.stp_optimizer import (
    audit_stp_path_costs,
    build_10g_expansion_validation_report,
    calculate_optimal_priorities,
    format_10g_validation_report_markdown,
    format_stp_report_markdown,
    generate_stp_report,
)
from unifi_mapper.analysis.stp_preflight import stp_preflight_simulate_add
from unifi_mapper.analysis.stp_snapshot import diff_stp_snapshots, snapshot_stp_topology
from unifi_mapper.core.models.stp import (
    STPConnection,
    STPPortConfig,
    STPTopology,
    SwitchSTPConfig,
)
from unifi_mapper.mcp import server
from unifi_mapper.mcp.registry import ToolRegistry


pytestmark = pytest.mark.usefixtures('block_network')

MANIFESTS = Path(server.__file__).parent / 'manifests'
# Keys whose values are generated at call time, so a direct call and an execute_tool call
# made a moment apart differ there and nowhere else.
VOLATILE = {'timestamp', 'generated_at', 'taken_at', 'created_at'}


def _topology() -> STPTopology:
    core = SwitchSTPConfig(
        device_id='sw-core',
        name='Core',
        mac='02:00:00:00:02:01',
        model='USW-Pro-Aggregation',
        current_priority=32768,
        connected_to_gateway=True,
        is_root_bridge=False,
        port_states=[
            STPPortConfig(port_idx=1, port_name='Gateway', link_speed_mbps=10000),
            STPPortConfig(port_idx=2, port_name='To Flex', link_speed_mbps=10000),
        ],
    )
    flex = SwitchSTPConfig(
        device_id='sw-flex',
        name='USW Flex XG',
        mac='02:00:00:00:02:02',
        model='USFXG',
        current_priority=4096,
        is_root_bridge=True,
        root_port_idx=None,
        port_states=[
            STPPortConfig(
                port_idx=1,
                port_name='Uplink',
                link_speed_mbps=10000,
                rx_errors=7,
                path_cost=2,  # a legacy short-mode cost on 10G, so the path-cost audit fires
                connected_device_id='sw-core',
                is_up=True,
                is_uplink=True,
            ),
        ],
        uplink_ports=[1],
    )
    return STPTopology(
        root_bridge_id='sw-flex',
        root_bridge_name='USW Flex XG',
        root_bridge_priority=4096,
        gateway_id='gw',
        gateway_name='Gateway',
        switches=[core, flex],
        connections=[
            STPConnection(
                from_device_id='sw-flex',
                from_device_name='USW Flex XG',
                from_port_idx=1,
                to_device_id='sw-core',
                to_device_name='Core',
                to_port_idx=2,
                path_cost=20000,
            )
        ],
    )


def _json(value: Any) -> Any:
    """The JSON form a client would send (pydantic models dumped, lists recursed)."""
    if isinstance(value, list):
        return [_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    return value


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _cases() -> dict[str, tuple[Any, dict[str, Any]]]:
    """name -> (direct result, the arguments as Python objects)."""
    topology = _topology()
    changes = asyncio.run(calculate_optimal_priorities(topology.model_copy(deep=True)))
    report = asyncio.run(generate_stp_report(topology.model_copy(deep=True), changes))
    validation = build_10g_expansion_validation_report(topology.model_copy(deep=True), changes)
    before = snapshot_stp_topology(topology)
    moved = topology.model_copy(deep=True)
    moved.switches[0].current_priority = 4096
    after = snapshot_stp_topology(moved)
    intent = {'Core': {'priority': 4096}}
    planned = {'USFXG': 1}
    targets = ['Core']
    return {
        'calculate_optimal_priorities': (changes, {'topology': topology}),
        'generate_stp_report': (report, {'topology': topology, 'changes': changes}),
        'format_stp_report_markdown': (format_stp_report_markdown(report), {'report': report}),
        'audit_stp_path_costs': (audit_stp_path_costs(topology), {'topology': topology}),
        'format_10g_validation_report_markdown': (
            format_10g_validation_report_markdown(validation),
            {'report': validation},
        ),
        'create_stp_change_plan': (create_stp_change_plan(changes), {'changes': changes}),
        'snapshot_stp_topology': (before, {'topology': topology}),
        'diff_stp_snapshots': (
            diff_stp_snapshots(before, after),
            {'before': before, 'after': after},
        ),
        'stp_preflight_simulate_add': (
            stp_preflight_simulate_add(topology, planned, targets),
            {'topology': topology, 'planned_models': planned, 'uplink_targets': targets},
        ),
        'audit_stp_guard_recommendations': (
            audit_stp_guard_recommendations(topology),
            {'topology': topology},
        ),
        'detect_stp_config_drift': (
            detect_stp_config_drift(topology, intent),
            {'topology': topology, 'intent': intent},
        ),
    }


CASES = _cases()


@pytest.fixture
def real_registry(monkeypatch):
    """The shipped manifests, and env that passes the controller credential gate."""
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv(
        'UNIFI_CONSOLE_API_TOKEN', 'FAKE-PIPELINE-TOKEN'
    )  # pragma: allowlist secret
    monkeypatch.setattr(server, 'get_registry', lambda: ToolRegistry(MANIFESTS, strict=True))


def test_the_cases_cover_every_pipeline_entry():
    registry = ToolRegistry(MANIFESTS, strict=True)
    pipeline = {
        name
        for names in registry.get_categories().values()
        for name in names
        if (meta := registry.get_metadata(name)) is not None and meta.pipeline
    }
    assert pipeline == set(CASES)


@pytest.mark.parametrize('name', sorted(CASES))
async def test_pipeline_tool_round_trips_through_execute_tool(real_registry, name):
    expected, args = CASES[name]
    raw = await server.execute_tool(name, json.loads(json.dumps(_json(args))))
    out = raw.structuredContent
    assert raw.isError is not True, out
    assert out['ok'] is True, out
    assert _stable(out['result']) == _stable(_json(expected))


def test_every_case_handler_is_the_manifest_handler():
    registry = ToolRegistry(MANIFESTS, strict=True)
    for name in CASES:
        meta = registry.get_metadata(name)
        assert meta is not None and meta.mutates is False
        assert callable(getattr(importlib.import_module(meta.module), meta.handler))


def test_the_fixture_gives_every_tool_something_to_carry():
    empty = [name for name, (expected, _) in CASES.items() if not _json(expected)]
    assert empty == []
