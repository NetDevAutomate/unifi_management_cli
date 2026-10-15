"""The ``diagram`` command, driven through the Typer runner over a fake port mapper.

The fake stands in for ``UnifiPortMapper``: its ``api_client`` serves a fixed ``stat/device``
list and no LLDP, so no controller is contacted (``block_network`` would fail the test).
"""

import json
import os
import pytest
from pathlib import Path
from typer.testing import CliRunner
from typing import Any, Iterator
from unifi_mapper import port_mapper
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()

ENV_KEYS = (
    'UNIFI_URL',
    'UNIFI_SITE',
    'UNIFI_USERNAME',
    'UNIFI_PASSWORD',
    'UNIFI_CONSOLE_API_TOKEN',
    'UNIFI_API_TOKEN',
    'UNIFI_CONFIG',
)

# A UXG site: the gateway's stat/device type is 'uxg' (documentation addresses only).
UXG_SITE: list[dict[str, Any]] = [
    {
        '_id': 'gw',
        'type': 'uxg',
        'model': 'UXGPRO',
        'name': 'Edge',
        'mac': '02:00:00:00:00:01',
        'ip': '192.0.2.1',
        'port_table': [],
    },
    {
        '_id': 'sw',
        'type': 'usw',
        'model': 'USFXG',
        'name': 'Core Flex XG',
        'mac': '02:00:00:00:00:02',
        'ip': '192.0.2.2',
        'port_table': [],
    },
    {
        '_id': 'ap',
        'type': 'uap',
        'model': 'UAP6MP',
        'name': 'Hall U6 Pro',
        'mac': '02:00:00:00:00:03',
        'ip': '192.0.2.3',
        'port_table': [],
    },
]


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """A ``--config`` file naming a documentation controller; ``os.environ`` restored after.

    ``load_env_from_config`` writes keys monkeypatch does not know about.
    """
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    saved = dict(os.environ)
    path = tmp_path / 'prod.env'
    path.write_text(
        'UNIFI_URL=https://192.0.2.1\nUNIFI_SITE=default\n'
        'UNIFI_USERNAME=reader\nUNIFI_PASSWORD=fake-password\n',  # pragma: allowlist secret
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)
    try:
        yield path
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Serve ``UXG_SITE`` from a fake ``UnifiPortMapper``; a test may replace the list."""
    devices = [dict(d) for d in UXG_SITE]

    class FakeApi:
        def get_devices(self, _site: str) -> dict[str, Any]:
            return {'data': devices}

        def get_lldp_info(self, _site: str, _device_id: str) -> dict[str, Any]:
            return {}

    class FakeMapper:
        def __init__(self, **_kwargs: Any) -> None:
            self.api_client = FakeApi()

    monkeypatch.setattr(port_mapper, 'UnifiPortMapper', FakeMapper)
    return devices


def _nodes(html: Path) -> dict[str, str]:
    """Each HTML node's name to its drawn type."""
    text = html.read_text(encoding='utf-8')
    start = text.index('[', text.index('const nodes'))
    nodes, _ = json.JSONDecoder().raw_decode(text[start:])
    return {node['name']: node['type'] for node in nodes}


def test_diagram_draws_a_uxg_gateway_as_the_gateway(
    config: Path, site: list[dict[str, Any]], tmp_path: Path
) -> None:
    """Issue 085: a 'uxg' device is drawn, and as a gateway, not dropped or drawn as an AP."""
    out = tmp_path / 'net.html'
    result = runner.invoke(
        app, ['--config', str(config), 'diagram', '--format', 'html', '-o', str(out)]
    )

    assert result.exit_code == 0, result.output
    assert 'Device types: 1 routers, 1 switches, 1 APs' in result.output
    assert 'Devices: 3' in result.output
    assert _nodes(out) == {'Edge': 'router', 'Core Flex XG': 'switch', 'Hall U6 Pro': 'ap'}


# Like `dot -Kdot -T<format> -O <source>`, as graphviz runs it: write <source>.<format>.
FAKE_DOT = """#!/bin/sh
for arg in "$@"; do
    case "$arg" in -T*) format="${arg#-T}" ;; esac
    source="$arg"
done
printf 'drawn\\n' > "$source.$format"
"""


@pytest.fixture
def no_dot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A PATH with no Graphviz ``dot`` on it."""
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
    dot.chmod(0o755)
    monkeypatch.setenv('PATH', f'{bin_dir}:/bin:/usr/bin')


@pytest.mark.usefixtures('site', 'no_dot')
@pytest.mark.parametrize('fmt', ['png', 'svg'])
def test_a_placeholder_is_reported_and_exits_1(config: Path, tmp_path: Path, fmt: str) -> None:
    """Issue 086: without Graphviz the renderer writes a placeholder; diagram says so."""
    out = tmp_path / f'net.{fmt}'
    result = runner.invoke(
        app, ['--config', str(config), 'diagram', '--format', fmt, '-o', str(out)]
    )

    assert result.exit_code == 1, result.output
    assert 'Diagram generated' not in result.output
    assert 'No diagram drawn' in result.stderr
    assert 'placeholder' in result.stderr
    assert "Graphviz's dot program is not on PATH" in ' '.join(result.output.split())
    assert out.read_text(encoding='utf-8').startswith(f'{fmt.upper()} generation needs Graphviz')


@pytest.mark.usefixtures('site', 'fake_dot')
@pytest.mark.parametrize('fmt', ['png', 'svg'])
def test_a_drawn_diagram_is_reported_and_exits_0(config: Path, tmp_path: Path, fmt: str) -> None:
    out = tmp_path / f'net.{fmt}'
    result = runner.invoke(
        app, ['--config', str(config), 'diagram', '--format', fmt, '-o', str(out)]
    )

    assert result.exit_code == 0, result.output
    assert 'Diagram generated' in result.output
    assert 'No diagram drawn' not in result.output
    assert out.read_text(encoding='utf-8') == 'drawn\n'
