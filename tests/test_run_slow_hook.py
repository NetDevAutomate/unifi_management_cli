"""T13: the slow/network deselection hook matches markers, never node names."""

import pytest


SANDBOX_CONFTEST = 'from tests.conftest import pytest_addoption, pytest_collection_modifyitems\n'
SANDBOX_INI = (
    '[pytest]\nasyncio_default_fixture_loop_scope = function\n'
    'markers =\n    slow: slow\n    network: network\n'
)
MARKED = (
    'import pytest\n\n\n@pytest.mark.slow\ndef test_marked_slow():\n    pass\n\n\n'
    '@pytest.mark.network\ndef test_marked_network():\n    pass\n'
)


@pytest.fixture
def sandbox(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """An unmarked test inside a package named ``network``, plus a slow and a network test."""
    monkeypatch.delenv('UNIFI_RUN_SLOW', raising=False)
    pytester.makeini(SANDBOX_INI)
    pytester.makeconftest(SANDBOX_CONFTEST)
    package = pytester.mkpydir('network')
    (package / 'test_plain.py').write_text('def test_unmarked_in_network_package():\n    pass\n')
    pytester.makepyfile(test_marked=MARKED)
    return pytester


def test_unmarked_test_in_network_package_runs_by_default(sandbox: pytest.Pytester) -> None:
    """A directory named network must not deselect its tests; only markers do."""
    result = sandbox.runpytest('-rs', '-v')
    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.fnmatch_lines(
        ['*network/test_plain.py::test_unmarked_in_network_package PASSED*']
    )
    result.stdout.fnmatch_lines(['*slow/network: pass --run-slow*'])


def test_run_slow_flag_runs_marked_tests(sandbox: pytest.Pytester) -> None:
    """--run-slow runs the marked tests too."""
    sandbox.runpytest('--run-slow').assert_outcomes(passed=3)


def test_env_opt_in_runs_marked_tests(
    sandbox: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UNIFI_RUN_SLOW=1 is the same opt-in as --run-slow."""
    monkeypatch.setenv('UNIFI_RUN_SLOW', '1')
    sandbox.runpytest().assert_outcomes(passed=3)
