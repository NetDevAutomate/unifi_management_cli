"""Credential isolation for every analysis test (design §6).

Analysis tests run real handlers that may reach ``get_credentials()``. The autouse
fixture below gives every test a fresh ``os.environ`` that can't see the real
``~/.config``, Keychain or 1Password, and forbids the credential chain unless the test
carries ``@pytest.mark.credential_chain`` (``tests/credential_isolation.py``). Each test
also runs in its own ``tmp_path``, so a path that is wrongly left relative (an unexpanded
``~/…``, say) lands there, never in the working tree the suite was started from.

This conftest must not define ``pytest_plugins`` (only the top-level one may).
"""

import pytest
from pathlib import Path
from tests.credential_isolation import ORIGINAL_ENVIRON, isolate_credentials, isolated_env


__all__ = ['ORIGINAL_ENVIRON', 'isolated_env']


@pytest.fixture(autouse=True)
def _isolate_credentials(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No real ~/.config, Keychain, 1Password or exported creds in any analysis test."""
    isolate_credentials(request, monkeypatch, tmp_path, chdir=True)
