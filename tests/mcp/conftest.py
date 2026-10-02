"""Credential isolation for every MCP test (design §6).

In-process MCP tests run real code that reaches credentials: the server lifespan calls
``resolve_mcp_config()`` and the credential gate calls ``get_credentials()``. The autouse
fixture below gives every test a fresh ``os.environ`` that can't see the real
``~/.config``, Keychain or 1Password, and forbids the credential chain unless the test
carries ``@pytest.mark.credential_chain``.

This conftest must not define ``pytest_plugins`` (only the top-level one may).
"""

import os
import pytest
from pathlib import Path
from typing import NoReturn


# The real os._Environ, captured before any test replaces os.environ.
ORIGINAL_ENVIRON = os.environ


def isolated_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """Env that can't see the real ~/.config, Keychain or 1Password."""
    return {
        'PATH': '/usr/bin:/bin',  # no `op`
        'HOME': str(tmp_path),
        'XDG_CONFIG_HOME': str(tmp_path / 'xdg'),
        'XDG_STATE_HOME': str(tmp_path / 'state'),
        'PYTHON_KEYRING_BACKEND': 'keyring.backends.null.Keyring',
        **extra,
    }


@pytest.fixture(autouse=True)
def _isolate_credentials(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No real ~/.config, Keychain, 1Password or exported creds in any MCP/analysis test."""
    # A fresh mapping: every write (incl. the lifespan's) is discarded when the test ends.
    monkeypatch.setattr(os, 'environ', dict(isolated_env(tmp_path)))
    import keyring.backends.null
    import keyring.core

    monkeypatch.setattr(keyring.core, '_keyring_backend', keyring.backends.null.Keyring())
    monkeypatch.setattr('keyring.get_password', lambda *a, **k: None)
    # _submit_daemon holds no state; resetting _pending is enough to drop any in-flight lookup.
    monkeypatch.setattr('unifi_mapper.mcp.config._pending', None)
    if request.node.get_closest_marker('credential_chain') is None:

        async def _forbidden() -> NoReturn:
            raise AssertionError('get_credentials() called without @pytest.mark.credential_chain')

        monkeypatch.setattr('unifi_mapper.core.utils.auth.get_credentials', _forbidden)
        monkeypatch.setattr('unifi_mapper.core.utils.client.get_credentials', _forbidden)
        monkeypatch.setattr('unifi_mapper.core.get_credentials', _forbidden)
