"""The autouse isolation fixture (tests/mcp/conftest.py) really isolates (design §6).

If any of these fail, MCP tests could read the real ~/.config, prompt the Keychain, run
``op`` or leave production credentials in the pytest process's environment.
"""

import os
import pytest
from pathlib import Path
from tests.fixtures_unifi import FAKE_TOKEN
from tests.mcp.conftest import ORIGINAL_ENVIRON
from unifi_mapper.mcp import config, server


def _credential_keys(env: object) -> set[str]:
    return {k for k in env if k.startswith(('UNIFI_', 'PROTECT_'))}  # type: ignore[attr-defined]


async def test_unmarked_test_cannot_reach_the_credential_chain() -> None:
    with pytest.raises(AssertionError, match='credential_chain'):
        await config.ensure_controller_credentials(5)


def test_environ_is_a_fresh_mapping() -> None:
    assert os.environ is not ORIGINAL_ENVIRON
    assert isinstance(os.environ, dict)
    assert os.environ['PATH'] == '/usr/bin:/bin'
    assert os.environ['PYTHON_KEYRING_BACKEND'] == 'keyring.backends.null.Keyring'
    assert _credential_keys(os.environ) == set()


def test_home_and_xdg_point_at_tmp_path(tmp_path: Path) -> None:
    assert Path.home() == tmp_path
    assert Path('~').expanduser() == tmp_path
    assert os.environ['XDG_CONFIG_HOME'] == str(tmp_path / 'xdg')


async def test_real_lifespan_never_leaks_into_the_process_environment(tmp_path: Path) -> None:
    before = _credential_keys(ORIGINAL_ENVIRON)
    prod = tmp_path / 'xdg' / 'unifi_management_cli' / 'prod.env'
    prod.parent.mkdir(parents=True)
    prod.write_text(
        f'UNIFI_URL=https://192.0.2.1\nUNIFI_CONSOLE_API_TOKEN={FAKE_TOKEN}\n'
        'PROTECT_HOST=192.0.2.1\n'
    )
    async with server.lifespan(server.mcp) as state:
        assert state.config.source == 'xdg'
        assert state.config.families['controller'].ready
        assert os.environ['UNIFI_CONSOLE_API_TOKEN'] == FAKE_TOKEN
    assert _credential_keys(ORIGINAL_ENVIRON) == before
    assert ORIGINAL_ENVIRON.get('UNIFI_CONSOLE_API_TOKEN') != FAKE_TOKEN
