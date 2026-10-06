"""What the topology diagram's formats need from Graphviz (issue 075; review AGG-8).

PNG and SVG are drawn by Graphviz's ``dot`` program through the ``graphviz`` package; HTML
is a d3 page written without it. Each case runs the real ``graphviz`` package, with ``dot``
hidden from ``PATH`` or replaced by a fake that writes the file it is asked for, so the
suite needs no Graphviz install and skips nothing.
"""

import graphviz
import pytest
from collections.abc import Callable
from pathlib import Path
from unifi_mapper.enhanced_network_topology import NetworkTopology


pytestmark = pytest.mark.usefixtures('block_network')

# Like `dot -Kdot -T<format> -O <source>`, as graphviz runs it: write <source>.<format>.
FAKE_DOT = """#!/bin/sh
for arg in "$@"; do
    case "$arg" in -T*) format="${arg#-T}" ;; esac
    source="$arg"
done
printf 'drawn\\n' > "$source.$format"
"""


def _topology() -> NetworkTopology:
    """Two devices and their link, documentation values only."""
    topology = NetworkTopology()
    topology.add_device('gw', 'Gateway', 'UXG', '02:00:00:00:00:01', '192.0.2.1')
    topology.add_device('sw', 'Switch A', 'USW-Lite-8', '02:00:00:00:00:02', '192.0.2.2')
    topology.add_connection('gw', 'sw', 1, 8)
    return topology


def _render(topology: NetworkTopology, fmt: str) -> Callable[[str], None]:
    """The method that draws ``fmt`` (``png`` or ``svg``)."""
    return topology.generate_png_diagram if fmt == 'png' else topology.generate_svg_diagram


@pytest.fixture
def no_dot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A PATH with no ``dot`` on it."""
    empty = tmp_path / 'no-dot'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))


@pytest.fixture
def fake_dot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A PATH whose ``dot`` writes the requested file and nothing else."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    dot = bin_dir / 'dot'
    dot.write_text(FAKE_DOT, encoding='utf-8')
    dot.chmod(0o700)
    monkeypatch.setenv('PATH', f'{bin_dir}:/usr/bin:/bin')


@pytest.mark.parametrize('fmt', ['png', 'svg'])
@pytest.mark.usefixtures('no_dot')
def test_without_dot_a_render_raises_and_leaves_its_dot_source(tmp_path: Path, fmt: str) -> None:
    """Issue 075: the render fails, no image is written, and the DOT source stays at the
    diagram path minus its extension (the reason everything under diagrams/ is ignored)."""
    out = tmp_path / 'diagrams' / f'network.{fmt}'
    out.parent.mkdir()
    with pytest.raises(graphviz.ExecutableNotFound, match=r"failed to execute PosixPath\('dot'\)"):
        _render(_topology(), fmt)(str(out))
    assert not out.exists()
    assert (out.parent / 'network').is_file()


@pytest.mark.parametrize('fmt', ['png', 'svg'])
@pytest.mark.usefixtures('fake_dot')
def test_with_dot_a_render_writes_the_image_and_removes_the_source(
    tmp_path: Path, fmt: str
) -> None:
    out = tmp_path / 'diagrams' / f'network.{fmt}'
    out.parent.mkdir()
    _render(_topology(), fmt)(str(out))
    assert sorted(p.name for p in out.parent.iterdir()) == [out.name]


@pytest.mark.parametrize('fmt', ['png', 'svg'])
@pytest.mark.parametrize('dir_name', ['site.{fmt}.d', 'run.{fmt}'])
@pytest.mark.usefixtures('fake_dot')
def test_a_render_strips_only_the_final_extension(tmp_path: Path, fmt: str, dir_name: str) -> None:
    """Final council F1: an extension in a directory's name stays, so the image and its DOT
    source go to the directory asked for, the one network-audit.sh checks, and nowhere else."""
    out_dir = tmp_path / dir_name.format(fmt=fmt)
    out_dir.mkdir()
    out = out_dir / f'network.{fmt}'
    _render(_topology(), fmt)(str(out))
    assert sorted(p.name for p in out_dir.iterdir()) == [out.name]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(['bin', out_dir.name])


@pytest.mark.parametrize('fmt', ['png', 'svg'])
@pytest.mark.usefixtures('fake_dot')
def test_a_path_without_the_extension_keeps_its_name(tmp_path: Path, fmt: str) -> None:
    """Only a final extension that matches the format is stripped; any other name gets the
    format's extension appended, as before."""
    out = tmp_path / 'diagrams' / 'network.dot'
    out.parent.mkdir()
    _render(_topology(), fmt)(str(out))
    assert sorted(p.name for p in out.parent.iterdir()) == [f'network.dot.{fmt}']


@pytest.mark.usefixtures('no_dot')
def test_html_is_drawn_without_dot(tmp_path: Path) -> None:
    """The docs' way round a missing dot: --format html needs no Graphviz."""
    out = tmp_path / 'network.html'
    _topology().generate_html_diagram(str(out))
    assert 'Switch A' in out.read_text(encoding='utf-8')
