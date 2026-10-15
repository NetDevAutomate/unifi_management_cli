"""What the PNG and SVG renderers return: ``None`` when drawn, the reason when not (issue 086).

Since issue 075 a render without Graphviz writes a placeholder and returns normally, so a
caller that must not report success (the ``diagram`` command) needs the outcome. Each case
runs the real ``graphviz`` package with ``dot`` hidden from ``PATH``, or the package itself
hidden, so no Graphviz install is needed.
"""

import builtins
import pytest
from pathlib import Path
from typing import Any
from unifi_mapper.enhanced_network_topology import GRAPHVIZ_MISSING_HINT, NetworkTopology


pytestmark = pytest.mark.usefixtures('block_network')

FAKE_DOT = """#!/bin/sh
for arg in "$@"; do
    case "$arg" in -T*) format="${arg#-T}" ;; esac
    source="$arg"
done
printf 'drawn\\n' > "$source.$format"
"""


def _topology() -> NetworkTopology:
    topology = NetworkTopology()
    topology.add_device('gw', 'Gateway', 'UXG', '02:00:00:00:00:01', '192.0.2.1')
    return topology


def _render(fmt: str, out: Path) -> str | None:
    topology = _topology()
    render = topology.generate_png_diagram if fmt == 'png' else topology.generate_svg_diagram
    return render(str(out))


@pytest.mark.parametrize('fmt', ['png', 'svg'])
def test_without_dot_the_reason_is_returned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fmt: str
) -> None:
    empty = tmp_path / 'no-dot'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))
    out = tmp_path / f'net.{fmt}'

    reason = _render(fmt, out)

    assert reason is not None and GRAPHVIZ_MISSING_HINT in reason
    assert out.read_text(encoding='utf-8') == reason + '\n'


@pytest.mark.parametrize('fmt', ['png', 'svg'])
def test_without_the_graphviz_package_the_reason_is_returned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fmt: str
) -> None:
    real_import = builtins.__import__

    def no_graphviz(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == 'graphviz':
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', no_graphviz)
    out = tmp_path / f'net.{fmt}'

    reason = _render(fmt, out)

    assert reason is not None and 'uv sync' in reason
    assert out.read_text(encoding='utf-8') == reason


@pytest.mark.parametrize('fmt', ['png', 'svg'])
def test_a_drawn_image_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fmt: str
) -> None:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    dot = bin_dir / 'dot'
    dot.write_text(FAKE_DOT, encoding='utf-8')
    dot.chmod(0o755)
    monkeypatch.setenv('PATH', f'{bin_dir}:/bin:/usr/bin')
    out = tmp_path / f'net.{fmt}'

    assert _render(fmt, out) is None
    assert out.read_text(encoding='utf-8') == 'drawn\n'
