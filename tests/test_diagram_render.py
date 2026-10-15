"""What the topology diagram's formats need from Graphviz (issue 075).

PNG and SVG are drawn by Graphviz's ``dot`` program through the ``graphviz`` package; HTML
is a d3 page written without it. Each case runs the real ``graphviz`` package, with ``dot``
hidden from ``PATH`` or replaced by a fake that writes the file it is asked for, so the
suite needs no Graphviz install and skips nothing. Without ``dot`` a render is a warning and
a placeholder, as it is without the package, and ``discover`` still writes its report.
"""

import graphviz
import logging
import pytest
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional
from unifi_mapper.enhanced_network_topology import NetworkTopology
from unifi_mapper.run_methods import run_port_mapper


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


def _render(topology: NetworkTopology, fmt: str) -> Callable[[str], Optional[str]]:
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
def test_without_dot_a_render_writes_a_placeholder_and_leaves_no_source(
    tmp_path: Path, fmt: str
) -> None:
    """Issue 075: like the missing-package branch, a missing ``dot`` is a warning and a
    placeholder that names the install, not an exception; the DOT source graphviz leaves at the
    diagram path minus its extension (the site's device names) is removed."""
    out = tmp_path / 'diagrams' / f'network.{fmt}'
    out.parent.mkdir()
    _render(_topology(), fmt)(str(out))
    text = out.read_text(encoding='utf-8')
    assert 'brew install graphviz' in text and 'apt install graphviz' in text
    assert '--format html' in text
    assert sorted(p.name for p in out.parent.iterdir()) == [out.name]


@pytest.mark.parametrize('fmt', ['png', 'svg'])
@pytest.mark.usefixtures('no_dot')
def test_without_dot_a_render_warns_with_the_install_command(
    tmp_path: Path, fmt: str, caplog: pytest.LogCaptureFixture
) -> None:
    out = tmp_path / f'network.{fmt}'
    with caplog.at_level(logging.WARNING, logger='unifi_mapper.enhanced_network_topology'):
        _render(_topology(), fmt)(str(out))
    [record] = [r for r in caplog.records if 'graphviz' in r.getMessage().lower()]
    assert record.levelno == logging.WARNING
    assert 'brew install graphviz' in record.getMessage()
    assert '--format html' in record.getMessage()


class _FakeApiClient:
    """The reads ``run_port_mapper`` makes, answered for one gateway and one switch."""

    is_authenticated = True
    base_url = 'https://192.0.2.1'
    is_unifi_os = True
    timeout = 1

    def get_devices(self, site_id: str) -> dict[str, Any]:
        return {
            'data': [
                {
                    '_id': 'gw',
                    'name': 'Gateway',
                    'model': 'UXG',
                    'mac': '02:00:00:00:00:01',
                    'ip': '192.0.2.1',
                    'type': 'ugw',
                },
                {
                    '_id': 'sw',
                    'name': 'Switch A',
                    'model': 'USW-Lite-8',
                    'mac': '02:00:00:00:00:02',
                    'ip': '192.0.2.2',
                    'type': 'usw',
                },
            ]
        }

    def get_device_ports(self, site_id: str, device_id: str) -> list[dict[str, Any]]:
        return []

    def get_lldp_info(self, site_id: str, device_id: str) -> dict[str, Any]:
        return {}

    def get_clients(self, site_id: str) -> dict[str, Any]:
        return {'data': []}


class _FakePortMapper:
    api_client = _FakeApiClient()

    def get_client_port_mapping(self, device_mac: str) -> dict[int, list[Any]]:
        return {}

    def batch_update_port_names(self, *args: object, **kwargs: object) -> bool:
        raise AssertionError('a dry run reached the writer')


@pytest.fixture
def dot_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """graphviz's renderer raising what it raises when ``dot`` is not on PATH."""

    def no_dot(self: graphviz.Source, *_args: object, **_kwargs: object) -> str:
        raise graphviz.ExecutableNotFound(['dot', '-Kdot', '-Tpng'])

    monkeypatch.setattr(graphviz.Source, 'render', no_dot)


@pytest.mark.parametrize('fmt', ['png', 'svg'])
@pytest.mark.usefixtures('dot_missing')
def test_discover_still_writes_its_report_without_dot(tmp_path: Path, fmt: str) -> None:
    """Issue 075: the diagram is drawn before the report, so the render's exception used to
    end the dry run with no report written."""
    report = tmp_path / 'reports' / 'port_mapping_report.md'
    diagram = tmp_path / 'diagrams' / f'network_diagram.{fmt}'

    devices, _connections = run_port_mapper(
        _FakePortMapper(),
        'default',
        dry_run=True,
        output_path=str(report),
        diagram_path=str(diagram),
        diagram_format=fmt,
    )

    assert set(devices) == {'gw', 'sw'}
    assert 'Switch A' in report.read_text(encoding='utf-8')
    assert 'brew install graphviz' in diagram.read_text(encoding='utf-8')


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
    """Review finding: an extension in a directory's name stays, so the image and its DOT
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
