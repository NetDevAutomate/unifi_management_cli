"""No CLI or MCP error output prints a secret from a failing frame (issue 058).

Typer before 0.23 prints each frame's local variables in an uncaught exception's traceback,
and loguru's ``diagnose`` annotates a logged traceback with variable values. Both are off
everywhere in ``src/``: every ``typer.Typer(...)`` sets ``pretty_exceptions_show_locals=False``,
every ``logger.add`` sets ``diagnose=False``, no debug path asks for ``show_locals=True``, and
both CLIs replace loguru's default handler (``diagnose`` on) before anything logs.
"""

import ast
import pytest
import sys
from collections.abc import Iterator
from loguru import logger
from pathlib import Path
from tests.fixtures_unifi import FAKE_PW
from typer.testing import CliRunner
from unifi_mapper import inventory_cli, typer_cli
from unifi_mapper.config import UnifiConfig
from unifi_mapper.core.utils.logging import replace_default_loguru_handler
from unifi_mapper.mcp import server


pytestmark = pytest.mark.usefixtures('isolated_credentials')

PACKAGE = Path(__file__).resolve().parents[1] / 'src' / 'unifi_mapper'
APPS = {
    'app': typer_cli.app,
    'find_app': typer_cli.find_app,
    'analyze_app': typer_cli.analyze_app,
    'diagnose_app': typer_cli.diagnose_app,
    'stp_app': typer_cli.stp_app,
    'radio_app': typer_cli.radio_app,
    'ports_app': typer_cli.ports_app,
    'inventory_app': inventory_cli.inventory_app,
}


def _calls(name: str) -> list[tuple[Path, ast.Call]]:
    found = []
    for path in sorted(PACKAGE.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == name
            ):
                found.append((path, node))
    return found


def _keyword(call: ast.Call, name: str) -> object:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


@pytest.mark.parametrize('name', sorted(APPS))
def test_every_typer_app_hides_frame_locals(name: str) -> None:
    assert APPS[name].pretty_exceptions_show_locals is False


def test_every_typer_app_in_src_is_checked_above() -> None:
    typer_calls = [
        (path, call)
        for path, call in _calls('Typer')
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == 'typer'
    ]
    assert len(typer_calls) == len(APPS)
    assert all(_keyword(call, 'pretty_exceptions_show_locals') is False for _, call in typer_calls)


def test_no_debug_path_prints_frame_locals() -> None:
    offenders = [
        f'{path.relative_to(PACKAGE)}:{call.lineno}'
        for path, call in _calls('print_exception')
        if _keyword(call, 'show_locals') is True
    ]
    assert offenders == []


def test_every_loguru_handler_in_src_has_diagnose_off() -> None:
    adds = [
        (path, call)
        for path, call in _calls('add')
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == 'logger'
    ]
    assert adds, 'expected logger.add calls in src'
    offenders = [
        f'{path.relative_to(PACKAGE)}:{call.lineno}'
        for path, call in adds
        if _keyword(call, 'diagnose') is not False
    ]
    assert offenders == []


def test_the_config_repr_holds_no_secret() -> None:
    config = UnifiConfig(
        base_url='https://192.0.2.1', username='admin', password=FAKE_PW, api_token=FAKE_PW
    )
    assert FAKE_PW not in repr(config)
    assert config.password == FAKE_PW  # still there, only hidden from repr


@pytest.fixture
def loguru_handlers() -> Iterator[None]:
    """Leave loguru with one plain stderr handler after the test, whatever it did."""
    yield
    logger.remove()
    logger.add(lambda message: sys.stderr.write(message), level='DEBUG', diagnose=False)


def _log_a_failure_holding_a_credential() -> None:
    credential = FAKE_PW
    try:
        raise RuntimeError('lookup failed') if credential else None
    except RuntimeError:
        logger.exception('tool failed')


@pytest.mark.usefixtures('loguru_handlers')
def test_the_mcp_server_log_writes_no_frame_values(capsys: pytest.CaptureFixture[str]) -> None:
    server._configure_logging('INFO')
    _log_a_failure_holding_a_credential()
    err = capsys.readouterr().err
    assert 'tool failed' in err and 'RuntimeError' in err
    assert FAKE_PW not in err


@pytest.mark.usefixtures('loguru_handlers')
def test_the_cli_handler_swap_writes_no_frame_values(capsys: pytest.CaptureFixture[str]) -> None:
    logger.remove()
    default_like = logger.add(sys.stderr, level='DEBUG', diagnose=True)  # loguru's default
    assert replace_default_loguru_handler(default_like) is not None
    _log_a_failure_holding_a_credential()
    err = capsys.readouterr().err
    assert 'tool failed' in err and 'RuntimeError' in err
    assert FAKE_PW not in err
    assert replace_default_loguru_handler(default_like) is None  # already replaced


@pytest.mark.usefixtures('loguru_handlers')
@pytest.mark.parametrize('cli', ['unifi-mapper', 'unifi-inventory'])
def test_both_clis_replace_the_default_handler_before_running(
    monkeypatch: pytest.MonkeyPatch, cli: str
) -> None:
    swapped: list[int] = []
    monkeypatch.setattr(
        'unifi_mapper.core.utils.logging.replace_default_loguru_handler',
        lambda handler_id=0: swapped.append(handler_id),
    )
    if cli == 'unifi-mapper':
        CliRunner().invoke(typer_cli.app, ['version'])
    else:
        monkeypatch.setattr(inventory_cli, 'inventory_app', lambda: None)
        inventory_cli.main()
    assert swapped == [0]
