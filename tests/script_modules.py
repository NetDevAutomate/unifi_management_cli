"""Load a script from ``scripts/`` in a test; the directory isn't an importable package."""

from __future__ import annotations

import importlib.util
import pytest
import sys
from pathlib import Path
from types import ModuleType


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load_script(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load ``scripts/<name>.py`` and register it in ``sys.modules`` for one test.

    The scripts import each other by bare name (``from site_targets import ...``), so the
    module is registered before it runs. ``monkeypatch`` removes it again after the test.

    Args:
        name: The script's file name, without ``.py``.
        monkeypatch: The test's ``monkeypatch`` fixture.

    Returns:
        The loaded module.
    """
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module
