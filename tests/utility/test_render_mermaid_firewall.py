"""The firewall-matrix Mermaid renderer reads firewall_check's record list (issue 091)."""

from unifi_mapper.connectivity.firewall_check import _build_vlan_matrix
from unifi_mapper.utility.render_mermaid import render_mermaid


NETWORKS = [
    {'_id': 'n1', 'name': 'IoT-PSK', 'vlan': 30},
    {'_id': 'n2', 'name': 'Office', 'vlan': 10},
]


async def test_firewall_matrix_from_the_builder_draws_the_vlans_and_no_verdict_edges() -> None:
    """The builder's cells are 'not assessed' (issue 093): nodes are drawn, edges are not."""
    matrix = await _build_vlan_matrix(NETWORKS)
    assert len(matrix['connectivity_matrix']) == 4  # one record per ordered pair, self included
    text = await render_mermaid('firewall_matrix', {'vlan_matrix': matrix})
    assert '        V30["IoT-PSK\\n(VLAN 30)"]' in text
    assert '        V10["Office\\n(VLAN 10)"]' in text
    assert [line for line in text.splitlines() if '->' in line] == []
    assert 'not assessed' in text


async def test_firewall_matrix_draws_an_edge_only_for_a_real_verdict() -> None:
    matrix = {
        'vlans': [{'id': 30, 'name': 'IoT-PSK'}, {'id': 10, 'name': 'Office'}],
        'connectivity_matrix': [
            {'source': 'IoT-PSK', 'destination': 'Office', 'verdict': 'deny'},
            {'source': 'Office', 'destination': 'IoT-PSK', 'verdict': 'not assessed'},
        ],
    }
    text = await render_mermaid('firewall_matrix', {'vlan_matrix': matrix})
    edges = [line.strip() for line in text.splitlines() if '->' in line]
    assert edges == ['V30 -.->|❌ DENY| V10']  # the not-assessed cell draws nothing


async def test_firewall_matrix_draws_allow_edges() -> None:
    matrix = {
        'vlans': [{'id': 30, 'name': 'IoT-PSK'}, {'id': 10, 'name': 'Office'}],
        'connectivity_matrix': [
            {'source': 'IoT-PSK', 'destination': 'Office', 'verdict': 'allow'},
            {'source': 'Office', 'destination': 'IoT-PSK', 'verdict': 'deny'},
        ],
    }
    text = await render_mermaid('firewall_matrix', {'vlan_matrix': matrix})
    edges = [line.strip() for line in text.splitlines() if '->' in line]
    assert edges == ['V30 -->|✅ ALLOW| V10', 'V10 -.->|❌ DENY| V30']


async def test_firewall_matrix_without_data_says_so() -> None:
    text = await render_mermaid('firewall_matrix', {'vlan_matrix': None})
    assert 'No firewall matrix data' in text
