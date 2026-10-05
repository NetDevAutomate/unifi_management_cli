"""Credential isolation for every test in this package (design §8, rule 3).

Tests here run real CLI and controller code. The autouse fixture gives each test a fresh
``os.environ`` that can't see the real ``~/.config``, Keychain or 1Password, forbids the
credential chain unless the test carries ``@pytest.mark.credential_chain``, and makes the
test's ``tmp_path`` the working directory, so neither ``prod.env`` nor ``./.env`` resolves
(``tests/credential_isolation.py``).

This conftest must not define ``pytest_plugins`` (only the top-level one may).
"""

import pytest
from pathlib import Path
from tests.credential_isolation import isolate_credentials


@pytest.fixture(autouse=True)
def _isolate_credentials(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No real config, Keychain, 1Password or exported creds; tmp_path is the cwd."""
    isolate_credentials(request, monkeypatch, tmp_path, chdir=True)
