"""Issue 091: an operator-chosen name that looks like a secret survives every output path.

The output redactors (``strip_secrets`` on the CLI's ``--json``, ``mask_secrets`` in the MCP
runner) act on mapping KEYS, which is right for controller objects and wrong for a report
keyed by names the operator chose. The 2026-10-15 audit drove six cases through the real
paths over the fake controller and proved loss in the two name-keyed outputs. 0.4.0 reshapes
both into lists of records, and these are the audit's cases inverted: each one now asserts
that a network named ``IoT-PSK`` keeps its name and its verdicts.

3. ``diagnose firewall Office IoT-PSK --json`` through ``_emit_json``.
4. ``firewall_check`` through the MCP runner, both surfaces.
5. ``snapshot_stp_topology``: keyed by device id, so a secret-looking switch name survives.
6. The pair rule: the new records carry no ``key``/``name``/``value`` field, so the rule that
   rightly strips a controller ``{name: <secret>, value: ...}`` pair cannot touch them.
"""

import json
import pydantic_core
import pytest
from pathlib import Path
from tests.credential_isolation import isolate_credentials
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.core.utils.redact import REDACTED, mask_secrets, strip_secrets
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir
from unifi_mapper.mcp.runner import ToolRunner
from unifi_mapper.typer_cli import app


runner = CliRunner()
LOOKALIKE_NETWORK = 'IoT-PSK'
GATE_ENV = {
    'UNIFI_URL': 'https://192.0.2.1',
    'UNIFI_CONSOLE_API_TOKEN': 'FAKE-091-CONSOLE-TOKEN',  # pragma: allowlist secret
}


@pytest.fixture(autouse=True)
def _isolated(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No real config, Keychain or 1Password; the MCP credential gate sees fake creds."""
    isolate_credentials(request, monkeypatch, tmp_path, chdir=True)
    for key, value in GATE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def shipped() -> ToolRunner:
    """The MCP runner over the shipped manifests, masking exactly as the server does."""
    return ToolRunner(
        ToolRegistry(default_manifests_dir(), strict=True), settings=ServerSettings()
    )


async def _through_runner(shipped: ToolRunner, name: str, params: dict[str, Any]) -> list[Any]:
    """The tool's result as each MCP surface sends it (execute_tool envelope, then direct)."""
    results = []
    out = await shipped.run(name, params, 'execute_tool')
    assert out.structuredContent is not None and out.structuredContent['ok'] is True, out
    results.append(out.structuredContent['result'])
    direct = await shipped.run(name, params, 'direct')
    assert not direct.isError, direct
    results.append(json.loads(direct.content[0].text))
    return results


def _mcp_masked(result: Any) -> Any:
    """What the MCP runner's direct surface sends for ``result`` (``runner._success``)."""
    return mask_secrets(
        pydantic_core.to_jsonable_python(result, by_alias=True, fallback=str), frozenset()
    )


def _untouched_by_both_redactors(payload: Any) -> None:
    """``strip_secrets`` removes nothing and ``mask_secrets`` masks nothing in ``payload``."""
    stripped, removed = strip_secrets(payload)
    assert stripped == payload and removed == []
    assert _mcp_masked(payload) == payload


# --- the firewall check: connectivity_matrix is a list of {source, destination, verdict} -----

NETWORKS = [
    {'_id': 'n1', 'name': LOOKALIKE_NETWORK, 'vlan': 30, 'purpose': 'corporate',
     'ip_subnet': '192.0.2.1/26'},
    {'_id': 'n2', 'name': 'Office', 'vlan': 10, 'purpose': 'corporate',
     'ip_subnet': '198.51.100.1/24'},
]  # fmt: skip
RULES = [
    {'_id': 'r1', 'name': 'Block IoT to Office', 'action': 'deny', 'enabled': True,
     'rule_index': 2000, 'ruleset': 'LAN_IN'},
]  # fmt: skip
MATRIX = [
    {'source': LOOKALIKE_NETWORK, 'destination': LOOKALIKE_NETWORK, 'verdict': 'allow'},
    {'source': LOOKALIKE_NETWORK, 'destination': 'Office', 'verdict': 'deny'},
    {'source': 'Office', 'destination': LOOKALIKE_NETWORK, 'verdict': 'deny'},
    {'source': 'Office', 'destination': 'Office', 'verdict': 'allow'},
]


def _firewall_controller() -> FakeController:
    return FakeController(
        {f'{API}/rest/networkconf': legacy(NETWORKS), f'{API}/rest/firewallrule': legacy(RULES)}
    )


def test_cli_diagnose_firewall_json_keeps_the_secret_looking_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 3: through _emit_json's strip_secrets, the IoT-PSK row and cells are all there."""
    controller = _firewall_controller()
    route_cli(monkeypatch, controller)
    result = runner.invoke(app, ['diagnose', 'firewall', 'Office', LOOKALIKE_NETWORK, '--json'])
    assert result.exit_code == 0, result.output
    matrix = json.loads(result.stdout)['vlan_matrix']
    assert matrix['connectivity_matrix'] == MATRIX
    assert [v['name'] for v in matrix['vlans']] == [LOOKALIKE_NETWORK, 'Office']
    assert controller.methods == {'GET'}


async def test_mcp_firewall_check_keeps_every_verdict(shipped: ToolRunner) -> None:
    """Case 4: through the real runner's masking, no IoT-PSK verdict reads ***redacted***."""
    controller = _firewall_controller()
    async with serving(controller):
        results = await _through_runner(
            shipped, 'firewall_check', {'source': 'Office', 'destination': LOOKALIKE_NETWORK}
        )
    for result in results:
        assert result['vlan_matrix']['connectivity_matrix'] == MATRIX
        assert REDACTED not in json.dumps(result)
    assert controller.methods == {'GET'}


# --- the maps the audit cleared, and the pair rule ----------------------------------------


def test_stp_snapshot_keeps_a_secret_looking_switch_name() -> None:
    """Case 5: the snapshot is keyed by device id, so the name survives as a value."""
    from unifi_mapper.analysis.stp_snapshot import snapshot_stp_topology
    from unifi_mapper.core.models.stp import STPPortConfig, STPTopology, SwitchSTPConfig

    ports = [STPPortConfig(port_idx=1, link_speed_mbps=10000, path_cost=2000)]
    switches = [
        SwitchSTPConfig(device_id=i, name=n, mac=m, current_priority=p, port_states=ports)
        for i, n, m, p in [('a', 'Core-Token-Ring', 'aa', 4096), ('b', 'Flex', 'bb', 32768)]
    ]
    topology = STPTopology(
        root_bridge_id='a', root_bridge_name='Core-Token-Ring', switches=switches
    )
    masked = _mcp_masked(snapshot_stp_topology(topology))
    assert masked['switches']['a'] == {'name': 'Core-Token-Ring', 'priority': 4096}
    assert masked['root_bridge_name'] == 'Core-Token-Ring'


async def test_the_matrix_records_are_out_of_the_pair_rules_reach() -> None:
    """Case 6, the matrix: both redactors keep every field; the pair rule itself stays.

    The pair rule strips ``value`` from ``{name|key: <secret-looking>, value: ...}``, which is
    right for a controller setting. A matrix record has no ``name``, ``key`` or ``value``.
    """
    from unifi_mapper.connectivity.firewall_check import _build_vlan_matrix

    matrix = await _build_vlan_matrix(NETWORKS, RULES)
    assert matrix['connectivity_matrix'] == MATRIX
    _untouched_by_both_redactors({'vlan_matrix': matrix})

    # The rule itself is unchanged: a controller pair named like a secret still loses value.
    stripped, _ = strip_secrets({'rows': [{'name': 'Guest-Token', 'value': 42}]})
    assert stripped['rows'] == [{'name': 'Guest-Token'}]
    masked = mask_secrets({'rows': [{'name': 'Guest-Token', 'value': 'up'}]}, frozenset())
    assert masked['rows'][0]['value'] == REDACTED
