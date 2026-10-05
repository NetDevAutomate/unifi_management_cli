"""Credential isolation for every MCP test (design §6).

In-process MCP tests run real code that reaches credentials: the server lifespan calls
``resolve_mcp_config()`` and the credential gate calls ``get_credentials()``. The autouse
fixture below gives every test a fresh ``os.environ`` that can't see the real
``~/.config``, Keychain or 1Password, and forbids the credential chain unless the test
carries ``@pytest.mark.credential_chain`` (``tests/credential_isolation.py``).

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
    """No real ~/.config, Keychain, 1Password or exported creds in any MCP test."""
    isolate_credentials(request, monkeypatch, tmp_path)
