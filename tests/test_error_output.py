"""No CLI or MCP error output prints a secret from a failing frame (issue 058).

Typer before 0.23 prints each frame's local variables in an uncaught exception's traceback,
and loguru's ``diagnose`` annotates a logged traceback with variable values. Both are off
everywhere in ``src/``: every ``typer.Typer(...)`` sets ``pretty_exceptions_show_locals=False``,
every ``logger.add`` sets ``diagnose=False``, no debug path asks for ``show_locals=True``, and
both Typer CLIs replace loguru's default handler (``diagnose`` on) before anything logs.

Every console script's error lines and ``--debug`` traceback go through ``redact_text``, the
argparse CLIs included, and the shared env-file loaders never echo a malformed line.
"""

import ast
import logging
import pytest
import secrets
import sys
from collections.abc import Callable, Iterator
from loguru import logger
from pathlib import Path
from tests.fixtures_unifi import FAKE_PW
from typer.testing import CliRunner
from types import SimpleNamespace
from unifi_mapper import cli as legacy_cli
from unifi_mapper import inventory_cli, network_cli, typer_cli, verify_cli
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
    'controller_app': typer_cli.controller_app,
    'backup_app': typer_cli.backup_app,
    'gateway_app': typer_cli.gateway_app,
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


def _typer_apps(path: Path, base: Path = PACKAGE) -> list[tuple[str, bool]]:
    """(path:line, hides frame locals) for every Typer app a module builds, any import form.

    ``typer.Typer(...)``, an ``import typer as t`` alias's ``t.Typer(...)``, and a name from
    ``from typer import Typer`` (``as`` an alias, or ``*``) called bare.
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    modules, names = {'typer'}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.asname for a in node.names if a.name == 'typer' and a.asname}
        elif isinstance(node, ast.ImportFrom) and node.module == 'typer':
            names |= {a.asname or 'Typer' for a in node.names if a.name in ('Typer', '*')}
    apps = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == 'Typer'
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        ) or (isinstance(func, ast.Name) and func.id in names):
            hides = _keyword(node, 'pretty_exceptions_show_locals') is False
            apps.append((node.lineno, f'{path.relative_to(base)}:{node.lineno}', hides))
    return [(where, hides) for _, where, hides in sorted(apps)]


@pytest.mark.parametrize('name', sorted(APPS))
def test_every_typer_app_hides_frame_locals(name: str) -> None:
    assert APPS[name].pretty_exceptions_show_locals is False


def test_every_typer_app_in_src_is_checked_above() -> None:
    apps = [app for path in sorted(PACKAGE.rglob('*.py')) for app in _typer_apps(path)]
    assert len(apps) == len(APPS)
    assert [where for where, hides in apps if not hides] == []


def test_the_typer_scan_sees_an_alias_and_a_from_import(tmp_path: Path) -> None:
    sample = tmp_path / 'sample.py'
    sample.write_text(
        'import typer\n'
        'import typer as t\n'
        'from typer import Typer\n'
        'from typer import Typer as T\n'
        'a = typer.Typer(pretty_exceptions_show_locals=False)\n'
        'b = t.Typer()\n'
        'c = Typer(help=1)\n'
        'd = T(pretty_exceptions_show_locals=True)\n'
        'e = other.Typer()\n'
    )
    assert _typer_apps(sample, tmp_path) == [
        ('sample.py:5', True),
        ('sample.py:6', False),
        ('sample.py:7', False),
        ('sample.py:8', False),
    ]


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

CLI_MODULES = [
    PACKAGE / name
    for name in (
        'typer_cli.py',
        'inventory_cli.py',
        'cli.py',
        'network_cli.py',
        'verify_cli.py',
        'backup/poc_decrypt.py',  # python -m unifi_mapper.backup.poc_decrypt
    )
]
REDACTING_CALLS = frozenset({'_error_text', 'redact_text', 'redact_traceback', '_fail'})
# Rich and Typer output, plus every stdlib logging and loguru level.
PRINTING_CALLS = frozenset(
    {'print', 'log', 'echo', 'secho', 'debug', 'info', 'warning', 'error', 'exception', 'critical'}
)


def _raw_exception_uses(path: Path, base: Path = PACKAGE) -> list[str]:
    """Return path:line of every print that shows a caught exception without redacting it.

    The path is relative to ``base`` (the package), since ``src/`` repeats basenames.
    """
    where = path.relative_to(base)
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
            if name not in PRINTING_CALLS:
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
                    f'{where}:{node.lineno}'
                    for node in ast.walk(arg)
                    if isinstance(node, ast.Name)
                    and node.id == caught
                    and id(node) not in protected
                ]
    return hits


def test_no_cli_print_shows_a_caught_exception_unredacted() -> None:
    assert [hit for path in CLI_MODULES for hit in _raw_exception_uses(path)] == []


def test_no_cli_debug_path_prints_an_unredacted_traceback() -> None:
    offenders = [
        f'{path.relative_to(PACKAGE)}:{call.lineno}'
        for name in ('print_exception', 'print_exc')
        for path, call in _calls(name)
        if path in CLI_MODULES
    ]
    assert offenders == []


# Every way the traceback module renders an exception; only redact_traceback may use one.
TRACEBACK_RENDERERS = (
    'print_exc',
    'print_exception',
    'print_tb',
    'print_stack',
    'format_exc',
    'format_exception',
    'format_tb',
    'format_stack',
)


def _traceback_renderer_uses(path: Path, base: Path = PACKAGE) -> list[str]:
    """path:line of every traceback renderer a module uses, under any import form.

    ``import traceback`` (or ``as`` an alias) then ``<name>.print_exc()``, and ``from
    traceback import print_exc`` (or ``*``), which needs no attribute call to use it. The
    path is relative to ``base`` (the package), since ``src/`` repeats basenames.
    """
    where = path.relative_to(base)
    tree = ast.parse(path.read_text(encoding='utf-8'))
    aliases = {'traceback'} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == 'traceback' and alias.asname
    }
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'traceback':
            hits += [
                f'{where}:{node.lineno}'
                for alias in node.names
                if alias.name in TRACEBACK_RENDERERS or alias.name == '*'
            ]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in TRACEBACK_RENDERERS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in aliases
        ):
            hits.append(f'{where}:{node.lineno}')
    return hits


def test_every_traceback_in_src_goes_through_redact_traceback() -> None:
    allowed = {PACKAGE / 'core' / 'utils' / 'redact.py'}  # redact_traceback itself
    offenders = [
        hit
        for path in sorted(PACKAGE.rglob('*.py'))
        if path not in allowed
        for hit in _traceback_renderer_uses(path)
    ]
    assert offenders == []
    assert _traceback_renderer_uses(PACKAGE / 'core' / 'utils' / 'redact.py'), (
        'the scan found no renderer at all: it is not looking where it should'
    )


def test_the_traceback_scan_sees_an_alias_and_a_from_import(tmp_path: Path) -> None:
    sample = tmp_path / 'sample.py'
    sample.write_text(
        'import traceback\n'
        'import traceback as tb\n'
        'from traceback import format_exc, extract_stack\n'
        'from traceback import *\n'
        'traceback.print_exc()\n'
        'tb.print_exception(None)\n'
        'other.print_exc()\n'
    )
    assert _traceback_renderer_uses(sample, tmp_path) == [
        'sample.py:3',
        'sample.py:4',
        'sample.py:5',
        'sample.py:6',
    ]


def test_the_raw_exception_scan_finds_an_unredacted_print(tmp_path: Path) -> None:
    sample = tmp_path / 'sample.py'
    sample.write_text(
        'try:\n    pass\nexcept Exception as e:\n'
        "    console.print(f'Error: {e}')\n"
        "    console.print(f'Error: {_error_text(e)}')\n"
        "    console.print(f'{redact_text(e)} and {e}')\n"
        "    log.error(f'Configuration error: {e}')\n"
        "    log.error(f'Configuration error: {redact_text(e)}')\n"
    )
    assert _raw_exception_uses(sample, tmp_path) == [
        'sample.py:4',
        'sample.py:6',
        'sample.py:7',
    ]


def test_the_scans_name_a_module_by_its_path_in_the_package() -> None:
    clients = sorted(PACKAGE.rglob('client.py'))
    assert len(clients) > 1  # why a basename would be ambiguous
    nested = PACKAGE / 'core' / 'utils' / 'redact.py'
    assert _traceback_renderer_uses(nested)[0].startswith('core/utils/redact.py:')


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


def _chained_error(fake: str) -> BaseException:
    try:
        raise KeyError(f'password={fake}')
    except KeyError as cause:
        error = RuntimeError(f'login failed, token={fake}')
        error.add_note(f'hint: retry with api_key={fake}')
        error.__cause__ = cause
        return error


@pytest.mark.parametrize('shape', ['chained cause and note', 'exception group'])
def test_the_debug_traceback_redacts_causes_notes_and_groups(
    monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    fake = secrets.token_hex(16)
    if shape == 'exception group':
        error: BaseException = ExceptionGroup(
            'probes failed', [ValueError(f'secret={fake}'), OSError('timed out')]
        )
    else:
        error = _chained_error(fake)

    async def _raise() -> None:
        raise error

    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setattr('unifi_mapper.analysis.mtu_audit.audit_mtu_consistency', _raise)
    result = CliRunner().invoke(typer_cli.app, ['--debug', 'analyze', 'mtu'])
    assert result.exit_code == 1, result.output
    assert fake not in result.output
    flat = ' '.join(result.output.split())
    assert 'Traceback' in flat
    if shape == 'exception group':
        assert 'probes failed' in flat and 'secret=***redacted***' in flat
    else:
        assert 'direct cause' in flat
        assert 'password=***redacted***' in flat and 'token=***redacted***' in flat
        assert 'api_key=***redacted***' in flat


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


# --- the argparse CLIs and the shared env-file loaders (review B5) ----------------------


def _fake() -> str:
    """A credential-shaped value made up for this run, so no literal needs a pragma."""
    return secrets.token_hex(16)


@pytest.mark.parametrize('loader', ['load_env_from_config', 'UnifiConfig.from_env'])
def test_a_malformed_config_line_is_reported_without_its_text(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    loader: str,
) -> None:
    fake = _fake()
    env_file = tmp_path / 'typo.env'
    # A space where the '=' belongs: the line has no name=value shape to redact.
    lines = [
        'UNIFI_URL=https://192.0.2.1',
        f'UNIFI_CONSOLE_API_TOKEN={_fake()}',
        f'UNIFI_PASSWORD {fake}',
    ]
    env_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    caplog.set_level(logging.WARNING)
    if loader == 'load_env_from_config':
        legacy_cli.load_env_from_config(str(env_file))
    else:
        UnifiConfig.from_env(str(env_file))
    captured = capsys.readouterr()
    assert 'Invalid line in ' in caplog.text
    assert "typo.env:3 (no '=' found)" in caplog.text
    assert fake not in caplog.text + captured.out + captured.err


def _config_error(fake: str) -> Callable[..., object]:
    def _raise(*_args: object, **_kwargs: object) -> object:
        raise ValueError(f'UNIFI_TIMEOUT is not a number; password={fake}')

    return _raise


def _a_config(*_args: object, **_kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        base_url='https://192.0.2.1',
        site='default',
        api_token=None,
        username=None,
        password=None,
        verify_ssl=False,
        timeout=10,
        default_format='png',
        default_output_dir=None,
        default_diagram_dir=None,
    )


def _boom(fake: str) -> Callable[..., object]:
    def _raise(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(f'controller said no, token={fake}')

    return _raise


def _run_argparse_cli(
    monkeypatch: pytest.MonkeyPatch, main: Callable[[], object], argv: list[str]
) -> int:
    monkeypatch.setattr(sys, 'argv', argv)
    try:
        result = main()
    except SystemExit as stop:
        return int(stop.code or 0)
    return int(result or 0)


@pytest.mark.parametrize('cli', ['unifi-network-toolkit', 'legacy unifi-mapper', 'verify'])
@pytest.mark.parametrize('debug', [False, True])
def test_the_argparse_clis_redact_a_configuration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    cli: str,
    debug: bool,
) -> None:
    fake = _fake()
    env_file = tmp_path / 'ok.env'
    env_file.write_text('UNIFI_URL=https://192.0.2.1\n', encoding='utf-8')
    monkeypatch.setattr(UnifiConfig, 'from_env', _config_error(fake))
    flags = ['--debug'] if debug else []
    main, argv = {
        'unifi-network-toolkit': (
            network_cli.main,
            [
                'unifi-network-toolkit',
                *flags,
                '--config',
                str(env_file),
                'analyze',
                'link-quality',
            ],
        ),
        'legacy unifi-mapper': (
            legacy_cli.main,
            ['unifi-mapper', *flags, '--config', str(env_file)],
        ),
        'verify': (verify_cli.main, ['verify', *flags, '--config', str(env_file)]),
    }[cli]
    caplog.set_level(logging.INFO)
    assert _run_argparse_cli(monkeypatch, main, argv) == 1
    captured = capsys.readouterr()
    assert 'Configuration error: ' in caplog.text
    assert 'password=***redacted***' in caplog.text
    assert fake not in caplog.text + captured.out + captured.err


@pytest.mark.parametrize('cli', ['unifi-network-toolkit', 'legacy unifi-mapper', 'verify'])
@pytest.mark.parametrize('debug', [False, True])
def test_the_argparse_clis_redact_an_error_and_its_debug_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    cli: str,
    debug: bool,
) -> None:
    fake = _fake()
    env_file = tmp_path / 'ok.env'
    env_file.write_text('UNIFI_URL=https://192.0.2.1\n', encoding='utf-8')
    monkeypatch.setattr(UnifiConfig, 'from_env', _a_config)
    flags = ['--debug'] if debug else []
    if cli == 'unifi-network-toolkit':
        monkeypatch.setattr(network_cli, 'handle_analyze_command', _boom(fake))
        main = network_cli.main
        argv = [
            'unifi-network-toolkit',
            *flags,
            '--config',
            str(env_file),
            'analyze',
            'link-quality',
        ]
    elif cli == 'legacy unifi-mapper':
        monkeypatch.setattr('unifi_mapper.port_mapper.UnifiPortMapper', _boom(fake))
        main = legacy_cli.main
        argv = [
            'unifi-mapper',
            *flags,
            '--config',
            str(env_file),
            '--output',
            str(tmp_path / 'r.md'),
        ]
        argv += ['--diagram', str(tmp_path / 'd.png')]
    else:
        monkeypatch.setattr(verify_cli, 'UnifiApiClient', _boom(fake))
        main = verify_cli.main
        argv = ['verify', *flags, '--config', str(env_file)]
    caplog.set_level(logging.INFO)
    assert _run_argparse_cli(monkeypatch, main, argv) == 1
    captured = capsys.readouterr()
    assert 'token=***redacted***' in caplog.text
    assert fake not in caplog.text + captured.out + captured.err
    if debug and cli != 'verify':  # verify's client-creation error prints no traceback
        assert 'Traceback' in captured.err and 'RuntimeError' in captured.err
        assert 'token=***redacted***' in captured.err


def test_the_verify_cli_redacts_a_failed_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _fake()
    env_file = tmp_path / 'ok.env'
    env_file.write_text('UNIFI_URL=https://192.0.2.1\n', encoding='utf-8')
    monkeypatch.setattr(UnifiConfig, 'from_env', _a_config)
    monkeypatch.setattr(
        verify_cli, 'UnifiApiClient', lambda **_kwargs: SimpleNamespace(login=lambda: True)
    )
    monkeypatch.setattr(verify_cli, 'analyze_current_state', _boom(fake))
    caplog.set_level(logging.INFO)
    argv = ['verify', '--debug', '--config', str(env_file)]
    assert _run_argparse_cli(monkeypatch, verify_cli.main, argv) == 1
    captured = capsys.readouterr()
    assert 'Verification error: ' in caplog.text and 'token=***redacted***' in caplog.text
    assert 'Traceback' in captured.err
    assert fake not in caplog.text + captured.out + captured.err


@pytest.mark.parametrize(
    'printer', [network_cli.print_link_quality_results, network_cli.print_network_health_results]
)
def test_the_toolkit_redacts_a_tool_s_error_text(
    caplog: pytest.LogCaptureFixture, printer: Callable[[dict[str, object]], None]
) -> None:
    fake = _fake()
    caplog.set_level(logging.INFO)
    printer({'error': f'Failed to fetch devices: api_key={fake}'})
    assert 'api_key=***redacted***' in caplog.text
    assert fake not in caplog.text
