"""T6: MCP config resolution per credential family, independent of the CWD.

Every test injects ``env`` and ``home`` (or replaces ``os.environ`` with a plain dict), so
nothing here reads the real ``~/.config`` or writes the pytest process's environment.
"""

import ast
import os
import pytest
from collections.abc import Callable
from pathlib import Path
from tests.fixtures_unifi import FAKE_PW, FAKE_TOKEN
from unifi_mapper.cli import load_env_from_config
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.redact import is_secret_key
from unifi_mapper.mcp import config
from unifi_mapper.mcp.config import (
    CREDENTIAL_KEYS,
    FAMILY_KEYS,
    ConfigFileError,
    apply_file,
    controller_ready,
    family_host,
    parse_env_file,
    resolve_config_path,
    resolve_mcp_config,
)
from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.protect.config import ProtectConfig


SRC = Path(__file__).resolve().parents[2] / 'src' / 'unifi_mapper'
SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
NET_KEY = 'FAKE-NETWORK-KEY-MUST-NOT-APPEAR'  # pragma: allowlist secret
LAB = 'https://lab.example.test'
PROD = 'https://192.0.2.1'

PROD_FILE = {
    'UNIFI_URL': PROD,
    'UNIFI_CONSOLE_API_TOKEN': FAKE_TOKEN,
    'UNIFI_SITE': 'default',
    'UNIFI_NETWORK_HOST': '192.0.2.1',
    'UNIFI_NETWORK_API_KEY': NET_KEY,
    'UNIFI_NETWORK_SITE_ID': SITE_ID,
    'PROTECT_HOST': '192.0.2.1',
    'PROTECT_USERNAME': 'viewer',
    'PROTECT_PASSWORD': FAKE_PW,
    'UNIFI_TIMEOUT': '45',
}


def _write_env(path: Path, values: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    return path


def _collect() -> tuple[list[str], Callable[[str], None]]:
    messages: list[str] = []
    return messages, messages.append


# --- file resolution -----------------------------------------------------------------


def test_unifi_config_wins_over_discovered_files(tmp_path: Path) -> None:
    chosen = _write_env(tmp_path / 'site-a.env', {'UNIFI_URL': PROD})
    _write_env(tmp_path / 'xdg' / 'unifi_management_cli' / 'prod.env', {'UNIFI_URL': LAB})
    env = {'UNIFI_CONFIG': str(chosen), 'XDG_CONFIG_HOME': str(tmp_path / 'xdg')}
    source, path, tried, warning = resolve_config_path(env, tmp_path, Path.is_file)
    assert (source, path, tried, warning) == ('explicit', chosen, (chosen,), None)


def test_unifi_config_tilde_expands_against_injected_home(tmp_path: Path) -> None:
    chosen = _write_env(tmp_path / 'cfg' / 'x.env', {'UNIFI_URL': PROD})
    env = {'UNIFI_CONFIG': '~/cfg/x.env'}
    assert resolve_config_path(env, tmp_path, Path.is_file)[:2] == ('explicit', chosen)


def test_unifi_config_missing_never_falls_through(tmp_path: Path) -> None:
    _write_env(tmp_path / 'xdg' / 'unifi_management_cli' / 'prod.env', PROD_FILE)
    _write_env(tmp_path / '.config' / 'unifi_management_cli' / 'prod.env', PROD_FILE)
    missing = tmp_path / 'gone.env'
    env = {'UNIFI_CONFIG': str(missing), 'XDG_CONFIG_HOME': str(tmp_path / 'xdg')}
    source, path, tried, warning = resolve_config_path(env, tmp_path, Path.is_file)
    assert (source, path, tried) == ('none', None, (missing,))
    assert warning and str(missing) in warning


def test_unifi_config_missing_server_start_path(tmp_path: Path) -> None:
    _write_env(tmp_path / '.config' / 'unifi_management_cli' / 'prod.env', PROD_FILE)
    missing = tmp_path / 'gone.env'
    env = {'UNIFI_CONFIG': str(missing)}
    messages, warn = _collect()
    resolved = resolve_mcp_config(env=env, home=tmp_path, warn=warn)
    assert resolved.source == 'none'
    assert resolved.tried == (missing,)
    assert not any(s.ready for s in resolved.families.values())
    assert env == {'UNIFI_CONFIG': str(missing)}
    assert len(messages) == 1 and str(missing) in messages[0]


@pytest.mark.parametrize(
    ('relative', 'source'),
    [
        ('xdg/unifi_management_cli/prod.env', 'xdg'),
        ('xdg/unifi_management_cli/default.env', 'xdg'),
        ('.config/unifi_management_cli/prod.env', 'home'),
        ('.config/unifi_management_cli/default.env', 'home'),
    ],
)
def test_discovery_order(tmp_path: Path, relative: str, source: str) -> None:
    target = _write_env(tmp_path / relative, {'UNIFI_URL': PROD})
    env = {'XDG_CONFIG_HOME': str(tmp_path / 'xdg')}
    got_source, path, tried, warning = resolve_config_path(env, tmp_path, Path.is_file)
    assert (got_source, path, warning) == (source, target, None)
    assert tried[-1] == target


def test_xdg_prod_beats_home_and_default(tmp_path: Path) -> None:
    xdg_prod = _write_env(tmp_path / 'xdg' / 'unifi_management_cli' / 'prod.env', {'A': '1'})
    _write_env(tmp_path / 'xdg' / 'unifi_management_cli' / 'default.env', {'A': '2'})
    _write_env(tmp_path / '.config' / 'unifi_management_cli' / 'prod.env', {'A': '3'})
    env = {'XDG_CONFIG_HOME': str(tmp_path / 'xdg')}
    assert resolve_config_path(env, tmp_path, Path.is_file)[:2] == ('xdg', xdg_prod)


def test_legacy_location_warns(tmp_path: Path) -> None:
    legacy = _write_env(tmp_path / '.config' / 'unifi_network_mapper' / 'prod.env', {'A': '1'})
    source, path, _, warning = resolve_config_path({}, tmp_path, Path.is_file)
    assert (source, path) == ('legacy', legacy)
    assert warning and 'deprecated' in warning


def test_nothing_found_lists_every_candidate(tmp_path: Path) -> None:
    env = {'XDG_CONFIG_HOME': str(tmp_path / 'xdg')}
    source, path, tried, warning = resolve_config_path(env, tmp_path, Path.is_file)
    assert (source, path, warning) == ('none', None, None)
    assert tried == (
        tmp_path / 'xdg' / 'unifi_management_cli' / 'prod.env',
        tmp_path / 'xdg' / 'unifi_management_cli' / 'default.env',
        tmp_path / '.config' / 'unifi_management_cli' / 'prod.env',
        tmp_path / '.config' / 'unifi_management_cli' / 'default.env',
        tmp_path / '.config' / 'unifi_network_mapper' / 'prod.env',
    )


def test_xdg_equal_to_home_config_is_tried_once(tmp_path: Path) -> None:
    env = {'XDG_CONFIG_HOME': str(tmp_path / '.config')}
    tried = resolve_config_path(env, tmp_path, Path.is_file)[2]
    assert len(tried) == len(set(tried)) == 3


def test_cwd_dotenv_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / 'work'
    _write_env(work / '.env', PROD_FILE)
    monkeypatch.chdir(work)
    env: dict[str, str] = {}
    resolved = resolve_mcp_config(env=env, home=tmp_path / 'home', warn=lambda _m: None)
    assert resolved.source == 'none'
    assert all(p.name != '.env' for p in resolved.tried)
    assert env == {}


def test_explicit_config_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError):
        resolve_mcp_config(tmp_path / 'nope.env', env={}, home=tmp_path)


def test_explicit_config_applies_whole_file(tmp_path: Path) -> None:
    path = _write_env(tmp_path / 'explicit.env', PROD_FILE)
    env: dict[str, str] = {}
    resolved = resolve_mcp_config(path, env=env, home=tmp_path)
    assert (resolved.source, resolved.path, resolved.tried) == ('explicit', path, (path,))
    assert env == PROD_FILE
    assert all(s.ready and s.source == 'file' for s in resolved.families.values())
    assert resolved.settings_from_file == frozenset({'UNIFI_TIMEOUT'})


def test_malformed_lines_warn_with_line_numbers_only(tmp_path: Path) -> None:
    path = tmp_path / 'bad.env'
    path.write_text(f'UNIFI_URL={PROD}\nnot-a-pair {FAKE_TOKEN}\n')
    messages, warn = _collect()
    env: dict[str, str] = {}
    resolve_mcp_config(path, env=env, home=tmp_path, warn=warn)
    assert env == {'UNIFI_URL': PROD}
    assert messages == [f'skipping malformed line 2 in {path}']


def test_status_json_has_key_names_only(tmp_path: Path) -> None:
    path = _write_env(tmp_path / 'explicit.env', PROD_FILE)
    resolved = resolve_mcp_config(path, env={}, home=tmp_path)
    text = repr(resolved.to_json_dict())
    for value in (FAKE_TOKEN, FAKE_PW, NET_KEY):
        assert value not in text
    assert 'UNIFI_CONSOLE_API_TOKEN' in text


# --- apply_file ------------------------------------------------------------------------


def test_exported_keys_are_never_overwritten() -> None:
    env = {'UNIFI_URL': PROD, 'UNIFI_CONSOLE_API_TOKEN': 'exported', 'UNIFI_TIMEOUT': '5'}
    to_set, status, settings = apply_file(env, PROD_FILE, explicit=True)
    assert not set(to_set) & set(env)
    assert status['controller'].source == 'environment'
    assert 'UNIFI_TIMEOUT' not in settings


def test_lab_export_with_prod_discovered_file_is_not_applied() -> None:
    env = {'UNIFI_URL': LAB, 'UNIFI_CONSOLE_API_TOKEN': 'lab-token'}
    to_set, status, settings = apply_file(env, PROD_FILE, explicit=False)
    assert to_set == {}
    assert settings == frozenset()
    assert status['controller'].source == 'environment'
    assert status['controller'].ready
    assert status['network_api'].source == 'none'
    assert status['network_api'].skipped_reason == config.FOREIGN_FILE_REASON
    assert not status['network_api'].ready
    assert status['protect'].skipped_reason == config.FOREIGN_FILE_REASON


def test_foreign_file_warning_is_emitted_once(tmp_path: Path) -> None:
    _write_env(tmp_path / '.config' / 'unifi_management_cli' / 'prod.env', PROD_FILE)
    env = {'UNIFI_URL': LAB, 'UNIFI_CONSOLE_API_TOKEN': 'lab-token'}
    messages, warn = _collect()
    resolved = resolve_mcp_config(env=env, home=tmp_path, warn=warn)
    assert resolved.source == 'home'
    assert len(messages) == 1 and 'UNIFI_CONFIG' in messages[0]
    assert env == {'UNIFI_URL': LAB, 'UNIFI_CONSOLE_API_TOKEN': 'lab-token'}


def test_same_host_fills_unexported_families_from_file() -> None:
    env = {'UNIFI_URL': 'https://192.0.2.1:443/', 'UNIFI_CONSOLE_API_TOKEN': 'exported'}
    to_set, status, settings = apply_file(env, PROD_FILE, explicit=False)
    assert status['controller'].source == 'environment'
    assert status['network_api'].source == 'file' and status['network_api'].ready
    assert status['protect'].source == 'file' and status['protect'].ready
    assert to_set['UNIFI_NETWORK_API_KEY'] == NET_KEY
    assert 'UNIFI_CONSOLE_API_TOKEN' not in to_set
    assert settings == frozenset({'UNIFI_TIMEOUT'})


def test_partial_export_is_never_topped_up() -> None:
    env = {'UNIFI_NETWORK_HOST': '192.0.2.1'}
    to_set, status, _ = apply_file(env, PROD_FILE, explicit=False)
    net = status['network_api']
    assert net.source == 'environment' and not net.ready
    assert 'UNIFI_NETWORK_API_KEY' in net.missing
    assert not any(k.startswith('UNIFI_NETWORK_') for k in to_set)


def test_exported_host_but_file_lacks_that_host_is_foreign() -> None:
    env = {'PROTECT_HOST': '192.0.2.1'}
    file_values = {k: v for k, v in PROD_FILE.items() if k != 'PROTECT_HOST'}
    to_set, status, settings = apply_file(env, file_values, explicit=False)
    assert to_set == {} and settings == frozenset()
    assert status['controller'].skipped_reason == config.FOREIGN_FILE_REASON


def test_explicit_file_with_different_host_is_applied_per_family() -> None:
    env = {'UNIFI_URL': LAB, 'UNIFI_CONSOLE_API_TOKEN': 'lab-token'}
    to_set, status, settings = apply_file(env, PROD_FILE, explicit=True)
    assert status['controller'].source == 'environment'
    assert status['network_api'].source == 'file'
    assert 'UNIFI_URL' not in to_set and to_set['PROTECT_HOST'] == '192.0.2.1'
    assert settings == frozenset({'UNIFI_TIMEOUT'})


def test_settings_rule() -> None:
    file_values = {
        'UNIFI_TIMEOUT': '45',
        'UNIFI_OUTPUT_DIR': '/tmp/out',
        'UNIFI_CONFIG': '/elsewhere.env',
        'UNIFI_MCP_LOG_LEVEL': 'DEBUG',
    }
    to_set, _, settings = apply_file({'UNIFI_TIMEOUT': '5'}, file_values, explicit=False)
    assert settings == frozenset({'UNIFI_OUTPUT_DIR'})
    assert to_set == {'UNIFI_OUTPUT_DIR': '/tmp/out'}


def test_nothing_exported_applies_whole_file_per_family() -> None:
    to_set, status, settings = apply_file({}, PROD_FILE, explicit=False)
    assert to_set == PROD_FILE
    assert {f: s.source for f, s in status.items()} == dict.fromkeys(FAMILY_KEYS, 'file')
    assert all(s.ready for s in status.values())
    assert settings == frozenset({'UNIFI_TIMEOUT'})


def test_empty_file_leaves_families_unready() -> None:
    _, status, _ = apply_file({}, {}, explicit=False)
    assert all(s.source == 'none' and not s.ready for s in status.values())
    assert status['controller'].missing == (
        'UNIFI_URL or UNIFI_HOST',
        'UNIFI_CONSOLE_API_TOKEN or UNIFI_USERNAME+UNIFI_PASSWORD',
    )


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('https://Controller.Example:8443/', 'controller.example'),
        ('http://192.0.2.1', '192.0.2.1'),
        ('192.0.2.1:443', '192.0.2.1'),
        ('', None),
    ],
)
def test_family_host_normalises(value: str, expected: str | None) -> None:
    assert family_host('controller', {'UNIFI_URL': value}) == expected
    assert family_host('protect', {'PROTECT_HOST': value}) == expected


# --- parse_env_file parity -------------------------------------------------------------

PARITY_LINES = [
    'A=1',
    '  B = two  ',
    'C="quoted"',
    "D='single'",
    'E=a=b',
    '# a comment',
    '',
    'F=',
    'G="unbalanced',
    'export H=x',
    'I = "x y" ',
    'novalue',
]


def test_parse_env_file_matches_load_env_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / 'parity.env'
    path.write_text('\n'.join(PARITY_LINES) + '\n')
    loaded: dict[str, str] = {}
    monkeypatch.setattr(os, 'environ', loaded)
    load_env_from_config(str(path))
    values, bad = parse_env_file(path.read_text())
    assert values == loaded
    assert bad == [PARITY_LINES.index('novalue') + 1]


def test_parse_env_file_rejects_empty_key() -> None:
    assert parse_env_file('=value\nA=1\n') == ({'A': '1'}, [1])


# --- parity with the code the families mirror ------------------------------------------

NETWORK_FULL = {
    'UNIFI_NETWORK_HOST': '192.0.2.1',
    'UNIFI_NETWORK_API_KEY': NET_KEY,
    'UNIFI_NETWORK_SITE_ID': SITE_ID,
}
PROTECT_FULL = {
    'PROTECT_HOST': '192.0.2.1',
    'PROTECT_USERNAME': 'viewer',
    'PROTECT_PASSWORD': FAKE_PW,
}


@pytest.mark.parametrize(
    ('family', 'full', 'loader'),
    [
        ('network_api', NETWORK_FULL, NetworkConfig.from_env),
        ('protect', PROTECT_FULL, ProtectConfig.from_env),
    ],
)
def test_credential_keys_match_config_loaders(
    monkeypatch: pytest.MonkeyPatch, family: str, full: dict[str, str], loader: object
) -> None:
    monkeypatch.setattr(os, 'environ', dict(full))
    loader()  # type: ignore[operator]
    listed = [k for group in CREDENTIAL_KEYS[family] for k in group]
    assert sorted(listed) == sorted(full)
    assert all(FAMILY_KEYS[family](k) for k in listed)
    for key in listed:
        monkeypatch.setattr(os, 'environ', {k: v for k, v in full.items() if k != key})
        with pytest.raises(ValueError):
            loader()  # type: ignore[operator]


CONTROLLER_TABLE = [
    {},
    {'UNIFI_URL': PROD},
    {'UNIFI_HOST': '192.0.2.1', 'UNIFI_API_TOKEN': FAKE_TOKEN},
    {'UNIFI_URL': PROD, 'UNIFI_CONSOLE_API_TOKEN': FAKE_TOKEN},
    {'UNIFI_URL': PROD, 'UNIFI_CONSOLE_API_TOKEN': ''},
    {'UNIFI_URL': PROD, 'UNIFI_USERNAME': 'admin'},
    {'UNIFI_URL': PROD, 'UNIFI_PASSWORD': FAKE_PW},
    {'UNIFI_URL': PROD, 'UNIFI_USERNAME': 'admin', 'UNIFI_PASSWORD': FAKE_PW},
    {'UNIFI_URL': '', 'UNIFI_HOST': '192.0.2.1', 'UNIFI_CONSOLE_API_TOKEN': FAKE_TOKEN},
    {'UNIFI_CONSOLE_API_TOKEN': FAKE_TOKEN},
    {'UNIFI_USERNAME': 'admin', 'UNIFI_PASSWORD': FAKE_PW},
]


@pytest.mark.parametrize('env', CONTROLLER_TABLE)
def test_controller_ready_matches_credentials_from_env(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    monkeypatch.setattr(os, 'environ', dict(env))
    try:
        Credentials.from_env()
    except ToolError as e:
        assert e.error_code == ErrorCodes.AUTHENTICATION_FAILED
        expected = False
    else:
        expected = True
    assert controller_ready(env) is expected


def _env_reads(tree: ast.AST) -> set[str]:
    """Return string keys read through os.environ[...], os.environ.get(...), os.getenv(...)."""
    keys: set[str] = set()

    def _is_environ(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == 'environ'
            and isinstance(node.value, ast.Name)
            and node.value.id == 'os'
        )

    for node in ast.walk(tree):
        key: ast.AST | None = None
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            key = node.slice
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in ('get', 'setdefault', 'pop')
                and _is_environ(func.value)
            ) or (
                isinstance(func, ast.Attribute)
                and func.attr == 'getenv'
                and isinstance(func.value, ast.Name)
                and func.value.id == 'os'
            ):
                key = node.args[0]
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
    return keys


def test_family_keys_cover_every_credential_env_read() -> None:
    reads: set[str] = set()
    for path in SRC.rglob('*.py'):
        reads |= _env_reads(ast.parse(path.read_text(), filename=str(path)))
    assert 'UNIFI_CONSOLE_API_TOKEN' in reads, 'scan found nothing; the AST walk is broken'
    credential_like = {
        k for k in reads if k.startswith(('UNIFI_', 'PROTECT_')) and is_secret_key(k)
    }
    unplaced = sorted(
        k for k in credential_like if not any(member(k) for member in FAMILY_KEYS.values())
    )
    assert unplaced == []
