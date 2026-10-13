"""`unifi-mapper install-completions` installs what its help offers, or exits 1 (issue 047).

The command hands the shell to the manual installer in ``completions.py``, which knows
``bash``, ``zsh`` and ``both``. Each accepted value runs through the command with the two
installers faked, so the suite touches no completion directory.
"""

import pytest
import re
from typer.testing import CliRunner
from types import SimpleNamespace
from unifi_mapper import completions
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()


@pytest.fixture
def installers(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace both installers with fakes that record their calls and return ``outcome``."""
    calls: list[tuple[str, bool]] = []
    state = SimpleNamespace(calls=calls, outcome=True)

    def fake(shell: str):
        def install(force: bool = False) -> bool:
            calls.append((shell, force))
            return state.outcome

        return install

    monkeypatch.setattr(completions, 'install_bash_completion', fake('bash'))
    monkeypatch.setattr(completions, 'install_zsh_completion', fake('zsh'))
    return state


def _flat(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('│', ' '))


@pytest.mark.parametrize('shell', ['bash', 'zsh', 'Bash'])
def test_a_single_shell_runs_its_installer_only(installers: SimpleNamespace, shell: str) -> None:
    result = runner.invoke(app, ['install-completions', shell])

    assert result.exit_code == 0, result.output
    assert installers.calls == [(shell.lower(), False)]


@pytest.mark.parametrize('shell', ['all', 'both'])
def test_all_and_both_install_bash_and_zsh(installers: SimpleNamespace, shell: str) -> None:
    """``all`` is what the help offered; ``both`` is what the installer and the toolkit take."""
    result = runner.invoke(app, ['install-completions', shell, '--force'])

    assert result.exit_code == 0, result.output
    assert installers.calls == [('bash', True), ('zsh', True)]


def test_fish_is_refused_with_a_pointer_to_typers_installer(installers: SimpleNamespace) -> None:
    result = runner.invoke(app, ['install-completions', 'fish'])

    assert result.exit_code == 1
    assert installers.calls == []
    text = _flat(result.output)
    assert 'fish' in text and 'unifi-mapper --install-completion' in text
    assert 'Unsupported shell' not in text  # fish is not unknown: it has a working path


def test_an_unknown_shell_exits_1_before_any_installer_runs(installers: SimpleNamespace) -> None:
    result = runner.invoke(app, ['install-completions', 'powershell'])

    assert result.exit_code == 1
    assert installers.calls == []
    assert 'bash, zsh, all' in _flat(result.output)


def test_a_failed_installation_exits_1(installers: SimpleNamespace) -> None:
    """Issue 047: a script that checks the exit status could not tell a failure from success."""
    installers.outcome = False
    result = runner.invoke(app, ['install-completions', 'zsh'])

    assert result.exit_code == 1
    assert installers.calls == [('zsh', False)]
    assert 'unifi-mapper --install-completion' in _flat(result.output)


def test_a_raising_installer_exits_1(installers: SimpleNamespace, monkeypatch) -> None:
    def boom(force: bool = False) -> bool:
        raise PermissionError('read-only file system')

    monkeypatch.setattr(completions, 'install_bash_completion', boom)
    result = runner.invoke(app, ['install-completions', 'bash'])

    assert result.exit_code == 1
    assert 'read-only file system' in _flat(result.output)


def test_help_lists_what_works() -> None:
    result = runner.invoke(app, ['install-completions', '--help'])

    assert result.exit_code == 0
    text = _flat(result.output)
    assert 'bash, zsh or all' in text
    assert 'bash/zsh/fish/all' not in text
    assert 'unifi-mapper --install-completion' in text
