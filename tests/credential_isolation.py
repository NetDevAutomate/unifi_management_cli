"""Credential isolation shared by every package that runs real code reaching credentials.

This host can hold the live controller credentials: the default config path names a real
``prod.env``, and a repository's ``./.env`` may link to a local config. A test that misses
one stub could log in to production. ``isolate_credentials`` gives a test a fresh
``os.environ`` that can't see the real ``~/.config``, Keychain or 1Password, and forbids
the credential chain unless the test carries ``@pytest.mark.credential_chain``. With
``chdir=True`` it also moves into the test's ``tmp_path``, so neither ``prod.env`` nor
``./.env`` resolves.

Used by the autouse fixtures in ``tests/mcp/``, ``tests/analysis/``,
``tests/diagnostics/``, ``tests/backup/`` and ``tests/connectivity/``, and by the root
opt-in ``isolated_credentials`` fixture. This module defines no fixture of its own.
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


def isolate_credentials(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    chdir: bool = False,
) -> None:
    """No real ~/.config, Keychain, 1Password or exported creds in this test.

    Args:
        request: The test's request, to read its ``credential_chain`` marker.
        monkeypatch: The test's monkeypatch; every change is undone when it ends.
        tmp_path: The test's directory, used as ``HOME`` and the XDG roots.
        chdir: Also make ``tmp_path`` the working directory, so ``./.env`` can't resolve.
    """
    # A fresh mapping: every write (incl. the lifespan's) is discarded when the test ends.
    monkeypatch.setattr(os, 'environ', dict(isolated_env(tmp_path)))
    if chdir:
        monkeypatch.chdir(tmp_path)
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
