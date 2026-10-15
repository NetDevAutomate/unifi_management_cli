"""Issue 020: ``python -m unifi_mapper.mcp.server`` prints no runpy warning.

``mcp/__init__.py`` imported ``.server`` eagerly, so running the module with ``-m`` first
imported the package (and with it ``server``), and runpy warned that
``'unifi_mapper.mcp.server' found in sys.modules after import of package 'unifi_mapper.mcp',
but prior to execution``. The package now resolves its ``server`` names lazily (PEP 562), so
``from unifi_mapper.mcp import mcp`` still works and ``-m`` is clean. The ``unifi-mcp``
console script never had the warning; this is the other documented way to start the server.
"""

import subprocess
import sys
from pathlib import Path
from tests.mcp.conftest import isolated_env


def test_running_the_server_module_with_dash_m_prints_no_runpy_warning(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            '-W',
            'error::RuntimeWarning',
            '-m',
            'unifi_mapper.mcp.server',
            '--version',
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=isolated_env(tmp_path),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert 'RuntimeWarning' not in result.stderr and 'found in sys.modules' not in result.stderr
    assert result.stdout.startswith('unifi-mcp (')


def test_importing_the_package_does_not_import_the_server_module(tmp_path: Path) -> None:
    code = (
        'import sys\n'
        'import unifi_mapper.mcp\n'
        "assert 'unifi_mapper.mcp.server' not in sys.modules, 'eager server import'\n"
        "assert 'unifi_mapper.mcp.registry' in sys.modules\n"
        'from unifi_mapper.mcp import ToolRegistry, get_registry, list_categories, mcp, search_tools\n'
        "assert 'unifi_mapper.mcp.server' in sys.modules\n"
        "assert type(mcp).__name__ == 'UnifiFastMCP', type(mcp)\n"
        'assert callable(get_registry) and callable(search_tools) and callable(list_categories)\n'
        'import unifi_mapper.mcp as pkg\n'
        'assert set(pkg.__all__) <= set(dir(pkg))\n'
        'try:\n'
        '    pkg.no_such_name\n'
        'except AttributeError as e:\n'
        "    assert 'no_such_name' in str(e)\n"
        'else:\n'
        "    raise AssertionError('a missing name must still raise AttributeError')\n"
    )
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=isolated_env(tmp_path),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
