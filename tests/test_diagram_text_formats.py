"""`--format dot` and `--format mermaid` write a diagram, not a placeholder (issue 044).

DOT is the source the PNG and SVG renderers already build; Mermaid is the topology renderer
in ``utility/render_mermaid.py`` fed from the same devices and connections. Both are text, so
each test reads the file back and looks for the fake topology's own nodes and edges.
"""

import pytest
from pathlib import Path
from unifi_mapper.enhanced_network_topology import NetworkTopology


pytestmark = pytest.mark.usefixtures('block_network')


def _topology() -> NetworkTopology:
    """A gateway, a switch on its port 1 and an AP on the switch's port 3."""
    topology = NetworkTopology()
    topology.add_device('gw', 'Gateway', 'UDM-Pro', '02:00:00:00:00:01', '192.0.2.1')
    topology.add_device('sw', 'Switch A', 'USW-Lite-8', '02:00:00:00:00:02', '192.0.2.2')
    topology.add_device('ap', 'Loft AP', 'U6-LR', '02:00:00:00:00:03', '192.0.2.3')
    topology.add_connection('gw', 'sw', 1, 8)
    topology.add_connection('sw', 'ap', 3, 1)
    return topology


def test_dot_writes_the_graphviz_source(tmp_path: Path) -> None:
    out = tmp_path / 'network.dot'
    _topology().generate_dot_diagram(str(out))
    text = out.read_text(encoding='utf-8')

    assert text.startswith('digraph NetworkTopology {')
    assert text.rstrip().endswith('}')
    assert '"gw" -> "sw" [dir=none];' in text
    assert '"sw" -> "ap" [dir=none];' in text
    assert 'Gateway' in text and 'Switch A' in text and 'Loft AP' in text
    assert 'would be generated here' not in text


def test_dot_equals_the_source_the_image_renderers_use(tmp_path: Path) -> None:
    topology = _topology()
    out = tmp_path / 'network.dot'
    topology.generate_dot_diagram(str(out))
    assert out.read_text(encoding='utf-8').rstrip('\n') == topology._generate_dot_source()


def test_mermaid_writes_a_graph_with_the_devices_and_their_links(tmp_path: Path) -> None:
    out = tmp_path / 'network.mermaid'
    _topology().generate_mermaid_diagram(str(out))
    text = out.read_text(encoding='utf-8')

    assert text.startswith('graph TB')
    assert '020000000001["Gateway<br/><small>UDM-Pro</small>"]' in text
    assert '020000000002["Switch A<br/><small>USW-Lite-8</small>"]' in text
    assert '020000000003(("Loft AP<br/><small>U6-LR</small>"))' in text
    assert '020000000001 -->|P1| 020000000002' in text
    assert '020000000002 -->|P3| 020000000003' in text
    assert 'class 020000000001 gateway' in text
    assert 'class 020000000002 switch' in text
    assert 'class 020000000003 ap' in text
    assert 'would be generated here' not in text


def test_mermaid_is_bare_source_without_a_markdown_fence(tmp_path: Path) -> None:
    """The file is what `mmdc -i` reads and what a Markdown ```mermaid fence wraps; the fence
    the MCP renderer adds for chat output stays out of it."""
    out = tmp_path / 'network.mermaid'
    _topology().generate_mermaid_diagram(str(out))
    text = out.read_text(encoding='utf-8')
    assert '```' not in text
    assert text.endswith('\n')


def test_mermaid_places_a_device_without_a_mac_by_its_id(tmp_path: Path) -> None:
    """An unadopted AP from the client list can carry 'Unknown MAC'; a space would break the
    node id, so the device id stands in for it."""
    topology = _topology()
    topology.add_device('stray', 'Stray AP', 'Unadopted AP', 'Unknown MAC', '192.0.2.9')
    topology.add_connection('sw', 'stray', 5, 1)
    out = tmp_path / 'network.mermaid'
    topology.generate_mermaid_diagram(str(out))
    text = out.read_text(encoding='utf-8')
    assert 'Unknown MAC' not in text.replace('"Stray AP<br/>', '')
    assert '020000000002 -->|P5| stray' in text


def test_mermaid_with_no_devices_is_still_a_diagram(tmp_path: Path) -> None:
    out = tmp_path / 'network.mermaid'
    NetworkTopology().generate_mermaid_diagram(str(out))
    assert 'No devices found' in out.read_text(encoding='utf-8')
