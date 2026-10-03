"""T7: what a wheel / uvx install actually contains, resolves and rebuilds.

The slow tests are skipped unless ``--run-slow`` or ``UNIFI_RUN_SLOW=1`` (hook in
``tests/conftest.py``). The build test needs network access or a warm uv cache for
hatchling under build isolation. The resolve test needs network access to PyPI: it ignores
``uv.lock`` the way uvx does, so the SDK pins run against what a fresh uvx install gets. The
rebuild test also needs PyPI: it fills an empty uv cache in ``tmp_path``.

The cache-key test is offline and always runs.
"""

import pytest
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path
from tests.mcp.conftest import ORIGINAL_ENVIRON


ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_SRC = ROOT / 'src' / 'unifi_mapper' / 'mcp' / 'manifests'
ENTRY_POINT = 'unifi-mcp = unifi_mapper.mcp.server:main'
# What a local-path uvx build must be keyed on, so a source edit reaches the next launch.
REQUIRED_CACHE_KEYS = ('pyproject.toml', 'src/**/*.py', 'src/**/*.yaml')
# The interpreter the suite is tested on (plan P13); an unpinned resolve could pick 3.13/3.14.
PYTHON = '3.12'
ISOLATED_TESTS = [
    'tests/mcp/test_cli_entry.py',
    'tests/mcp/test_registry.py',
    'tests/mcp/test_protocol_contract.py',
]


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


def _git_tracked(prefix: str) -> list[str]:
    """Return the git-tracked files under ``prefix``, as POSIX paths relative to ROOT.

    ``GIT_*`` variables are dropped so a git hook's ``GIT_DIR`` or ``GIT_INDEX_FILE`` can't
    point the listing at another index.
    """
    git = shutil.which('git', path=ORIGINAL_ENVIRON.get('PATH'))
    assert git, 'git is not on PATH'
    proc = subprocess.run(
        [git, '-C', str(ROOT), 'ls-files', '-z', '--', prefix],
        capture_output=True,
        text=True,
        env={k: v for k, v in _clean_env().items() if not k.startswith('GIT_')},
        check=True,
        timeout=60,
    )
    return [p for p in proc.stdout.split('\0') if p]


def _uncovered_by_cache_keys(paths: list[str], globs: list[str]) -> list[str]:
    """Return the ``paths`` (relative to ROOT) that no ``globs`` file key matches, sorted."""
    covered = {p.relative_to(ROOT).as_posix() for g in globs for p in ROOT.glob(g) if p.is_file()}
    return sorted(set(paths) - covered)


def test_uv_cache_keys_cover_the_source_and_manifests() -> None:
    """Code-review F1 and F12: the cache keys decide when uvx rebuilds a checkout.

    Every git-tracked file under src/unifi_mapper must match a file key, or uvx serves it stale.
    """
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    keys = config['tool']['uv']['cache-keys']
    files = {k['file'] for k in keys if isinstance(k, dict) and 'file' in k}
    # cache-keys replaces uv's default list, so pyproject.toml must be named explicitly.
    assert set(REQUIRED_CACHE_KEYS) <= files, files

    tracked = _git_tracked('src/unifi_mapper')
    assert tracked, 'git ls-files found nothing under src/unifi_mapper'
    assert any(p.endswith('.yaml') for p in tracked), 'no tracked manifest: the check is vacuous'
    uncovered = _uncovered_by_cache_keys(tracked, sorted(files))
    assert uncovered == [], f'not covered by any [tool.uv] cache-keys file glob: {uncovered}'
    # The helper reports a file outside the globs, so an empty result above means something.
    assert _uncovered_by_cache_keys(['src/unifi_mapper/__init__.py'], ['src/**/*.yaml']) == [
        'src/unifi_mapper/__init__.py'
    ]


def _uvx() -> str:
    """Return the uvx executable found on the real (pre-isolation) PATH."""
    uvx = shutil.which('uvx', path=ORIGINAL_ENVIRON.get('PATH'))
    assert uvx, 'uvx is not on PATH'
    return uvx


def _uvx_probe(project: Path, probe: str, env: dict[str, str]) -> list[str]:
    """Run the documented local-path launch with ``python -c`` and return stdout lines."""
    proc = subprocess.run(
        [_uvx(), '--python', PYTHON, '--from', str(project), 'python', '-c', probe],
        capture_output=True,
        text=True,
        cwd=project.parent,
        env=env,
        timeout=900,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
    return proc.stdout.strip().splitlines()


@pytest.mark.slow
@pytest.mark.network
def test_local_path_uvx_launch_serves_source_edits(tmp_path: Path) -> None:
    """Code-review F1: a plain ``uvx --from <checkout>`` serves an edited .py and .yaml.

    Works on a copy under an empty uv cache, so the user's cache and the worktree are never
    touched. ``unifi-mcp --version`` can't be the probe: it reads importlib.metadata, which a
    source edit doesn't change.
    """
    project = tmp_path / 'checkout'
    project.mkdir()
    for name in ('pyproject.toml', 'README.md'):  # hatchling reads README.md (project.readme)
        shutil.copy2(ROOT / name, project / name)
    shutil.copytree(
        ROOT / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc')
    )
    env = {
        **_clean_env(),
        'UV_CACHE_DIR': str(tmp_path / 'uv-cache'),
        'UV_TOOL_DIR': str(tmp_path / 'uv-tools'),
        'UV_TOOL_BIN_DIR': str(tmp_path / 'uv-bin'),
    }
    py_probe = (
        'import unifi_mapper.core.utils.coerce as m; '
        "print(m.__file__); print(getattr(m, 'CACHE_KEY_PROBE', 'absent'))"
    )
    yaml_probe = (
        'import importlib.resources as r; '
        "t = r.files('unifi_mapper.mcp').joinpath('manifests/analysis.yaml').read_text(); "
        "print('# cache-key-probe' in t)"
    )

    first_file, first_marker = _uvx_probe(project, py_probe, env)
    assert first_marker == 'absent'
    # A build, not the copy's source tree: otherwise the test proves nothing about the cache.
    assert Path(first_file).resolve().is_relative_to((tmp_path / 'uv-cache').resolve())
    # No edit: the cached build is reused rather than rebuilt on every launch.
    again_file, _ = _uvx_probe(project, py_probe, env)
    assert Path(again_file).resolve() == Path(first_file).resolve()

    with (project / 'src/unifi_mapper/core/utils/coerce.py').open('a') as fh:
        fh.write("\nCACHE_KEY_PROBE = 'edited'\n")
    assert _uvx_probe(project, py_probe, env)[1] == 'edited'

    assert _uvx_probe(project, yaml_probe, env) == ['False']
    with (project / 'src/unifi_mapper/mcp/manifests/analysis.yaml').open('a') as fh:
        fh.write('# cache-key-probe\n')
    assert _uvx_probe(project, yaml_probe, env) == ['True']
