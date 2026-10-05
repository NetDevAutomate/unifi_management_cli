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


# --- every CLI error line and debug traceback is redacted (M2 council M2-BLOCK-001) ------

CLI_MODULES = [PACKAGE / 'typer_cli.py', PACKAGE / 'inventory_cli.py']
REDACTING_CALLS = frozenset({'_error_text', 'redact_text', '_fail'})


def _raw_exception_uses(path: Path) -> list[str]:
    """Return path:line of every print that shows a caught exception without redacting it."""
    hits = []
    for handler in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if not isinstance(handler, ast.ExceptHandler) or handler.name is None:
            continue
        caught = handler.name
        for call in ast.walk(handler):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
            if name not in {'print', 'log', 'echo', 'secho'}:
                continue
            for arg in [*call.args, *(k.value for k in call.keywords)]:
                protected = {
                    id(inner)
                    for node in ast.walk(arg)
                    if isinstance(node, ast.Call)
                    and getattr(node.func, 'id', None) in REDACTING_CALLS
                    for inner in ast.walk(node)
                }
                hits += [
                    f'{path.name}:{node.lineno}'
                    for node in ast.walk(arg)
                    if isinstance(node, ast.Name)
                    and node.id == caught
                    and id(node) not in protected
                ]
    return hits


def test_no_cli_print_shows_a_caught_exception_unredacted() -> None:
    assert [hit for path in CLI_MODULES for hit in _raw_exception_uses(path)] == []


def test_no_cli_debug_path_prints_rich_s_unredacted_traceback() -> None:
    offenders = [
        f'{path.relative_to(PACKAGE)}:{call.lineno}'
        for path, call in _calls('print_exception')
        if path in CLI_MODULES
    ]
    assert offenders == []


def test_the_raw_exception_scan_finds_an_unredacted_print(tmp_path: Path) -> None:
    sample = tmp_path / 'sample.py'
    sample.write_text(
        'try:\n    pass\nexcept Exception as e:\n'
        "    console.print(f'Error: {e}')\n"
        "    console.print(f'Error: {_error_text(e)}')\n"
        "    console.print(f'{redact_text(e)} and {e}')\n"
    )
    assert _raw_exception_uses(sample) == ['sample.py:4', 'sample.py:6']


@pytest.fixture
def failing_mtu(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> None:
        raise RuntimeError(f'controller said no, password={FAKE_PW}')

    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setattr('unifi_mapper.analysis.mtu_audit.audit_mtu_consistency', _boom)


@pytest.mark.usefixtures('failing_mtu')
@pytest.mark.parametrize('args', [['analyze', 'mtu'], ['--debug', 'analyze', 'mtu']])
def test_an_existing_command_s_error_and_debug_traceback_are_redacted(args: list[str]) -> None:
    result = CliRunner().invoke(typer_cli.app, args)
    assert result.exit_code == 1, result.output
    assert 'controller said no, password=***redacted***' in ' '.join(result.output.split())
    assert FAKE_PW not in result.output
    if '--debug' in args:
        assert 'Traceback' in result.output and 'RuntimeError' in result.output


def test_a_tool_error_through_the_analysis_helper_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
    from unifi_mapper.diagnostics import network_health

    async def _refused() -> None:
        raise ToolError(
            message=f'Failed to fetch device list: token={FAKE_PW}',
            error_code=ErrorCodes.API_ERROR,
        )

    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setattr(network_health, 'network_health_check', _refused)
    result = CliRunner().invoke(typer_cli.app, ['diagnose', 'health'])
    assert result.exit_code == 1
    assert 'Failed to fetch device list: token=***redacted***' in result.stderr
    assert FAKE_PW not in result.output
