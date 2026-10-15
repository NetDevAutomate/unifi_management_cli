"""`scripts/unifi-mcp-launch.sh` ignores a relative ``XDG_CONFIG_HOME`` (issue 068).

The wrapper runs for real under bash with HOME in a temp dir and no config file anywhere, so
it exits 1 before it would source a file or exec ``uv``; the test reads which path it
names. A relative value (``conf``, ``./conf``, ``~/conf``; the shell does not expand ``~``
inside a variable) must send it to ``$HOME/.config``, never to a directory under the
working directory.
"""

from __future__ import annotations

import pytest
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'unifi-mcp-launch.sh'

pytestmark = pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')


def _run(tmp_path: Path, xdg: str | None) -> subprocess.CompletedProcess[str]:
    home = tmp_path / 'home'
    cwd = tmp_path / 'cwd'
    home.mkdir(exist_ok=True)
    cwd.mkdir(exist_ok=True)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(home)}
    if xdg is not None:
        env['XDG_CONFIG_HOME'] = xdg
    return subprocess.run(
        ['bash', str(SCRIPT)],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize('relative', ['conf', './conf', '~/conf'])
def test_a_relative_xdg_config_home_is_ignored(tmp_path: Path, relative: str) -> None:
    # The stray file exists, so the old wrapper would have sourced it (and then looked for uv).
    stray = tmp_path / 'cwd' / 'conf' / 'unifi_management_cli' / 'prod.env'
    stray.parent.mkdir(parents=True)
    stray.write_text('UNIFI_URL=https://192.0.2.1\n', encoding='utf-8')

    result = _run(tmp_path, relative)

    assert result.returncode == 1, result.stderr
    expected = tmp_path / 'home' / '.config' / 'unifi_management_cli' / 'prod.env'
    assert f'config not found or unreadable: {expected}' in result.stderr
    assert 'conf/unifi_management_cli' not in result.stderr.replace(str(expected), '')


def test_an_absolute_xdg_config_home_is_used(tmp_path: Path) -> None:
    xdg = tmp_path / 'xdg'
    result = _run(tmp_path, str(xdg))

    assert result.returncode == 1, result.stderr
    assert f'config not found or unreadable: {xdg / "unifi_management_cli" / "prod.env"}' in (
        result.stderr
    )


def test_unset_xdg_config_home_uses_the_home_config(tmp_path: Path) -> None:
    result = _run(tmp_path, None)

    assert result.returncode == 1, result.stderr
    expected = tmp_path / 'home' / '.config' / 'unifi_management_cli' / 'prod.env'
    assert f'config not found or unreadable: {expected}' in result.stderr
