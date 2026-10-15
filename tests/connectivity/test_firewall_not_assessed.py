"""Issue 093: `diagnose firewall` says `not assessed`, never a heuristic `allow` or `deny`.

Until the rule engine evaluates each rule's source and destination against the pair (0.5.0,
after a live capture of classic and zone-based rule shapes), the honest output is a verdict of
``not assessed`` with a ``basis`` that names exactly what was checked, on every surface: the
result dict (CLI JSON and the MCP tool), the human rendering, the VLAN matrix and its Mermaid
drawing, and the recommendations.
"""

from __future__ import annotations

import json
import pytest
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from tests.fixtures_unifi import FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.connectivity.firewall_check import NOT_ASSESSED, firewall_check
from unifi_mapper.typer_cli import app
from unifi_mapper.utility.render_mermaid import render_mermaid


NETWORKS: list[dict[str, Any]] = [
    {
        '_id': 'n1',
        'name': 'Office',
        'vlan': 10,
        'purpose': 'corporate',
        'ip_subnet': '192.0.2.0/24',
    },
    {
        '_id': 'n2',
        'name': 'IoT',
        'vlan': 20,
        'purpose': 'corporate',
        'ip_subnet': '198.51.100.0/24',
    },
]
# A rule whose NAME says block: the old heuristic turned every matrix cell 'deny' on this alone.
RULES: list[dict[str, Any]] = [
    {
        '_id': 'r1',
        'name': 'Block IoT to Office',
        'enabled': True,
        'action': 'deny',
        'ruleset': 'LAN_IN',
        'rule_index': 2000,
        'protocol': 'all',
        'src_networkconf_id': 'n2',
        'dst_networkconf_id': 'n1',
    }
]


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)


def _controller() -> FakeController:
    return FakeController(
        {
            f'{API}/rest/networkconf': legacy(NETWORKS),
            f'{API}/rest/firewallrule': legacy(RULES),
        }
    )


def _assert_no_heuristic_verdict(result: dict[str, Any]) -> None:
    assert result['verdict'] == NOT_ASSESSED
    basis = result['basis'].lower()
    assert 'protocol' in basis and 'port' in basis
    assert 'not evaluated' in basis and 'rule' in basis, (
        'the basis says the rules were not evaluated per pair'
    )
    matrix = result['vlan_matrix']['connectivity_matrix']
    assert matrix, 'the pair records are still listed'
    assert {record['verdict'] for record in matrix} == {NOT_ASSESSED}
    # a listed rule's own `action` may say deny; the VERDICT fields never do
    assert result['verdict'] not in ('allow', 'deny')


@pytest.mark.usefixtures('_env')
async def test_the_result_never_carries_a_heuristic_verdict() -> None:
    async with serving(_controller()):
        result = await firewall_check(
            source='Office', destination='IoT', protocol='tcp', port='443'
        )
    _assert_no_heuristic_verdict(result)
    # the rules that matched on protocol/port are still listed, qualified
    assert (
        result['matching_rules'] and result['matching_rules'][0]['name'] == 'Block IoT to Office'
    )
    assert any('not' in r and 'rule' in r for r in result['recommendations']), result[
        'recommendations'
    ]


@pytest.mark.usefixtures('_env')
def test_the_cli_prints_not_assessed_and_why(monkeypatch: pytest.MonkeyPatch) -> None:
    route_cli(monkeypatch, _controller())
    out = CliRunner().invoke(app, ['diagnose', 'firewall', 'Office', 'IoT', '--json'])
    assert out.exit_code == 0, out.output
    _assert_no_heuristic_verdict(json.loads(out.stdout))

    human = CliRunner().invoke(app, ['diagnose', 'firewall', 'Office', 'IoT'])
    assert human.exit_code == 0, human.output
    assert 'not assessed' in human.output
    assert 'ALLOW' not in human.output and 'DENY' not in human.output


async def test_the_mermaid_matrix_draws_no_verdict_edges() -> None:
    data = {
        'vlan_matrix': {
            'vlans': [{'id': 10, 'name': 'Office'}, {'id': 20, 'name': 'IoT'}],
            'connectivity_matrix': [
                {'source': 'Office', 'destination': 'IoT', 'verdict': NOT_ASSESSED},
                {'source': 'IoT', 'destination': 'Office', 'verdict': NOT_ASSESSED},
            ],
        }
    }
    text = await render_mermaid('firewall_matrix', data)
    assert 'ALLOW' not in text and 'DENY' not in text
    assert 'not assessed' in text
    assert 'V10' in text and 'V20' in text  # the VLANs are still drawn, without verdict edges


def test_the_help_text_does_not_promise_a_verdict() -> None:
    out = CliRunner().invoke(app, ['diagnose', 'firewall', '--help'])
    assert out.exit_code == 0
    text = ' '.join(out.output.split())  # the help wraps across lines
    assert 'allow/deny' not in text
    assert 'not assessed' in text
