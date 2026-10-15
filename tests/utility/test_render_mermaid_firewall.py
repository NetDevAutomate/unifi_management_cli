"""The firewall-matrix Mermaid renderer reads firewall_check's record list (issue 091)."""

from unifi_mapper.connectivity.firewall_check import _build_vlan_matrix
from unifi_mapper.utility.render_mermaid import render_mermaid


NETWORKS = [
    {'_id': 'n1', 'name': 'IoT-PSK', 'vlan': 30},
    {'_id': 'n2', 'name': 'Office', 'vlan': 10},
]
RULES = [{'_id': 'r1', 'name': 'Block IoT to Office', 'action': 'deny', 'enabled': True}]


async def test_firewall_matrix_draws_one_edge_per_cross_network_record() -> None:
    matrix = await _build_vlan_matrix(NETWORKS, RULES)
    text = await render_mermaid('firewall_matrix', {'vlan_matrix': matrix})
    assert '        V30["IoT-PSK\\n(VLAN 30)"]' in text
    assert '        V10["Office\\n(VLAN 10)"]' in text
    edges = [line.strip() for line in text.splitlines() if '->' in line]
    assert edges == ['V30 -.->|❌ DENY| V10', 'V10 -.->|❌ DENY| V30']  # no self edges


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
