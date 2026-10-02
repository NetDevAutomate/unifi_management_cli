"""T7: what a wheel / uvx install actually contains and resolves.

Both tests are skipped unless ``--run-slow`` or ``UNIFI_RUN_SLOW=1`` (hook in
``tests/conftest.py``). The build test needs network access or a warm uv cache for
hatchling under build isolation. The resolve test needs network access to PyPI: it ignores
``uv.lock`` the way uvx does, so the SDK pins run against what a fresh uvx install gets.
"""

import pytest
import shutil
import subprocess
import zipfile
from pathlib import Path
from tests.mcp.conftest import ORIGINAL_ENVIRON


ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_SRC = ROOT / 'src' / 'unifi_mapper' / 'mcp' / 'manifests'
ENTRY_POINT = 'unifi-mcp = unifi_mapper.mcp.server:main'
# The interpreter the suite is tested on (plan P13); an unpinned resolve could pick 3.13/3.14.
PYTHON = '3.12'
ISOLATED_TESTS = ['tests/mcp/test_cli_entry.py', 'tests/mcp/test_registry.py']


def _uv() -> str:
    """Return the uv executable found on the real (pre-isolation) PATH."""
    uv = shutil.which('uv', path=ORIGINAL_ENVIRON.get('PATH'))
    assert uv, 'uv is not on PATH'
    return uv


def _clean_env() -> dict[str, str]:
    """Return the real environment without controller/Protect credentials or venv."""
    return {
        k: v
        for k, v in ORIGINAL_ENVIRON.items()
        if not k.startswith(('UNIFI_', 'PROTECT_')) and k != 'VIRTUAL_ENV'
    }


@pytest.mark.slow
def test_wheel_ships_every_manifest_and_the_entry_point(tmp_path: Path) -> None:
    proc = subprocess.run(
        [_uv(), 'build', '--wheel', '--out-dir', str(tmp_path), str(ROOT)],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr
    [wheel] = tmp_path.glob('*.whl')
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        [entry_points] = [n for n in names if n.endswith('.dist-info/entry_points.txt')]
        entry_text = zf.read(entry_points).decode()

    expected = {f'unifi_mapper/mcp/manifests/{p.name}' for p in MANIFESTS_SRC.glob('*.yaml')}
    assert expected, 'no source manifests found'
    shipped = {n for n in names if n.startswith('unifi_mapper/mcp/manifests/')}
    assert shipped == expected
    assert ENTRY_POINT in entry_text.splitlines()


@pytest.mark.slow
@pytest.mark.network
def test_unlocked_isolated_resolve_passes_entry_and_registry_tests() -> None:
    code = (
        'import importlib.metadata, sys, pytest\n'
        "print('MCP_VERSION=' + importlib.metadata.version('mcp'), flush=True)\n"
        f"sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', *{ISOLATED_TESTS!r}]))\n"
    )
    proc = subprocess.run(
        [
            _uv(),
            'run',
            '--isolated',
            '--no-project',
            '--python',
            PYTHON,
            '--with',
            str(ROOT),
            '--with',
            'pytest',
            '--with',
            'pytest-asyncio',
            '--with',
            'jsonschema',
            'python',
            '-c',
            code,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=_clean_env(),
        timeout=900,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
    [line] = [ln for ln in proc.stdout.splitlines() if ln.startswith('MCP_VERSION=')]
    assert line.removeprefix('MCP_VERSION=').startswith('1.30.'), line
    assert ' passed' in proc.stdout
    assert ' failed' not in proc.stdout
