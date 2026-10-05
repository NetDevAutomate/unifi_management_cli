"""``scripts/controller_dump.py`` and ``scripts/network-audit.sh`` (design section 4.13).

The dump reads through the real read-only guard over the house fake session (no socket),
writes only stripped payloads and a manifest with the guard's request audit, and refuses an
``--output`` inside the repository. The audit script is only syntax-checked and its
argument handling run: every step it runs needs a controller.
"""

import json
import pytest
import stat
import subprocess
from pathlib import Path
from tests.fixtures_unifi import API_RE, V2_RE, FakeSession, fake_client
from tests.script_modules import SCRIPTS, load_script
from typing import Any


FAKE_PSK = 'FAKE-DUMP-WLAN-PASSPHRASE'  # pragma: allowlist secret
FAKE_COMMUNITY = 'FAKE-DUMP-SNMP-COMMUNITY'  # pragma: allowlist secret
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_script('controller_dump', monkeypatch)


def _session() -> FakeSession:
    return FakeSession(
        {
            ('GET', rf'^{API_RE}/rest/wlanconf$'): {
                'meta': {'rc': 'ok'},
                'data': [{'name': 'SSID A', 'x_passphrase': FAKE_PSK}],
            },
            ('GET', rf'^{API_RE}/rest/setting$'): {
                'meta': {'rc': 'ok'},
                'data': [{'key': 'snmp', 'community': FAKE_COMMUNITY}],
            },
            ('GET', rf'^{V2_RE}/apgroups$'): [{'name': 'All APs'}],
        }
    )


def test_an_output_inside_the_repository_exits_2(mod: Any, capsys: pytest.CaptureFixture) -> None:
    for inside in (REPO, REPO / 'reports' / 'dump', REPO / 'scripts'):
        assert mod.main(['--output', str(inside)]) == 2
    assert 'outside the repository' in capsys.readouterr().err


def test_an_output_that_is_a_file_exits_2(mod: Any, tmp_path: Path) -> None:
    blocker = tmp_path / 'a-file'
    blocker.write_text('x', encoding='utf-8')
    assert mod.main(['--output', str(blocker)]) == 2


def test_the_dump_writes_stripped_payloads_and_the_manifest(mod: Any, tmp_path: Path) -> None:
    session = _session()
    client = fake_client(session)
    names = ['wlanconf', 'setting', 'apgroups', 'sta']
    manifest = mod.dump(client, 'default', tmp_path, names)

    written = {p.name for p in tmp_path.iterdir()}
    assert written == {'wlanconf.json', 'setting.json', 'apgroups.json', 'manifest.json'}
    text = ''.join(p.read_text(encoding='utf-8') for p in tmp_path.iterdir())
    assert FAKE_PSK not in text and FAKE_COMMUNITY not in text
    assert {p: stat.S_IMODE((tmp_path / p).stat().st_mode) for p in written} == dict.fromkeys(
        written, 0o600
    )

    assert manifest['endpoints']['wlanconf'] == {'status': 200, 'records': 1}
    assert manifest['endpoints']['apgroups'] == {'status': 200, 'records': 1}
    assert (
        manifest['endpoints']['sta']['status'] == 404 and 'error' in manifest['endpoints']['sta']
    )
    assert {'wlanconf.data[0].x_passphrase', 'setting.data[0].community'} <= set(
        manifest['sanitised_paths']
    )
    methods = {entry['method'] for entry in manifest['request_audit']}
    assert methods == {'GET'} and len(manifest['request_audit']) == len(names)
    assert {call['method'] for call in session.calls} == {'GET'}
    saved = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert saved['endpoints'] == manifest['endpoints']


def test_the_table_is_the_designs_and_reads_only(mod: Any) -> None:
    assert set(mod.ENDPOINTS) == {
        'wlanconf',
        'networkconf',
        'setting',
        'firewallrule',
        'firewallgroup',
        'sta',
        'device',
        'health',
        'firewall-policies',
        'firewall-zone',
        'trafficrules',
        'apgroups',
    }
    for dropped in ('stat/event', 'stat/alarm', 'stat/dhcp', 'stat/rogueap', 'events', 'mdns'):
        assert dropped not in {path for _, path in mod.ENDPOINTS.values()}


def test_the_config_is_the_flag_then_unifi_config_then_the_default(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('UNIFI_CONFIG', str(tmp_path / 'env.env'))
    assert mod.config_path(str(tmp_path / 'flag.env')) == tmp_path / 'flag.env'
    assert mod.config_path(None) == tmp_path / 'env.env'
    monkeypatch.delenv('UNIFI_CONFIG')
    monkeypatch.setattr(mod, 'get_default_config_path', lambda: tmp_path / 'default.env')
    assert mod.config_path(None) == tmp_path / 'default.env'


def test_a_failed_login_is_one_redacted_line_and_exit_1(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    def _refused(_path: Path) -> Any:
        raise RuntimeError('login refused password=FAKE-DUMP-LOGIN-PW')  # pragma: allowlist secret

    monkeypatch.setattr(mod, '_login', _refused)
    assert mod.main(['--output', str(tmp_path / 'out')]) == 1
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'FAKE-DUMP-LOGIN-PW' not in err
    assert stat.S_IMODE((tmp_path / 'out').stat().st_mode) == 0o700


# --- the output directory (review B5): nothing planted there can redirect a write ----------


def _no_login(mod: Any, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record any login attempt: a refused --output must stop before the controller."""
    attempts: list[Path] = []

    def _login(path: Path) -> Any:
        attempts.append(path)
        raise AssertionError('login attempted')

    monkeypatch.setattr(mod, '_login', _login)
    return attempts


def test_a_symlink_in_the_output_directory_is_refused_and_its_target_unchanged(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    victim = tmp_path / 'victim.txt'
    victim.write_text('keep me\n', encoding='utf-8')
    victim.chmod(0o644)
    output = tmp_path / 'out'
    output.mkdir(mode=0o700)
    (output / 'wlanconf.json').symlink_to(victim)
    attempts = _no_login(mod, monkeypatch)
    assert mod.main(['--output', str(output)]) == 2
    assert 'new or empty directory' in capsys.readouterr().err
    assert victim.read_text(encoding='utf-8') == 'keep me\n'
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644 and attempts == []


def test_a_write_never_follows_or_truncates_an_existing_path(mod: Any, tmp_path: Path) -> None:
    """Each file is opened O_EXCL | O_NOFOLLOW, so a link planted mid-run is refused too."""
    victim = tmp_path / 'victim.txt'
    victim.write_text('keep me\n', encoding='utf-8')
    link, plain = tmp_path / 'link.json', tmp_path / 'plain.json'
    link.symlink_to(victim)
    plain.write_text('old\n', encoding='utf-8')
    for path in (link, plain):
        with pytest.raises(FileExistsError):
            mod._write_private(path, {'a': 1})
    assert victim.read_text(encoding='utf-8') == 'keep me\n'
    assert plain.read_text(encoding='utf-8') == 'old\n'


@pytest.mark.parametrize('mode', [0o770, 0o707, 0o777], ids=['group', 'other', 'everyone'])
def test_an_output_directory_others_can_write_is_refused(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int
) -> None:
    output = tmp_path / 'out'
    output.mkdir()
    output.chmod(mode)
    attempts = _no_login(mod, monkeypatch)
    assert mod.main(['--output', str(output)]) == 2 and attempts == []


def test_an_output_directory_of_another_user_is_refused(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    output = tmp_path / 'out'
    output.mkdir(mode=0o700)
    monkeypatch.setattr(mod.os, 'getuid', lambda: output.stat().st_uid + 1)
    attempts = _no_login(mod, monkeypatch)
    assert mod.main(['--output', str(output)]) == 2 and attempts == []
    assert 'not your directory' in capsys.readouterr().err


def test_an_empty_private_output_directory_is_used(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / 'out'
    output.mkdir(mode=0o700)
    session = _session()
    monkeypatch.setattr(mod, '_login', lambda _path: (fake_client(session), 'default'))
    assert mod.main(['--output', str(output), '--endpoint', 'wlanconf']) == 0
    assert {p.name for p in output.iterdir()} == {'wlanconf.json', 'manifest.json'}


# --- scripts/network-audit.sh ---------------------------------------------------------------


AUDIT = SCRIPTS / 'network-audit.sh'


def _audit(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['bash', str(AUDIT), *args], capture_output=True, text=True, timeout=30, check=False
    )


def test_the_audit_script_parses_and_has_no_apply_step() -> None:
    assert subprocess.run(['bash', '-n', str(AUDIT)], check=False).returncode == 0
    text = AUDIT.read_text(encoding='utf-8')
    code = [line for line in text.splitlines() if not line.lstrip().startswith('#')]
    run_lines = [line for line in code if line.strip().startswith('step ')]
    assert run_lines and not any('--apply' in line or 'apply --plan' in line for line in run_lines)
    assert 'read -' not in text  # no confirmation prompt: nothing to confirm


@pytest.mark.parametrize(
    'args',
    [['--planned-switches', '0'], ['--planned-switches', 'x'], ['--bogus'], ['--config']],
    ids=['zero switches', 'not a number', 'unknown', 'no config value'],
)
def test_the_audit_script_refuses_bad_arguments_with_exit_2(args: list[str]) -> None:
    result = _audit(*args)
    assert result.returncode == 2 and result.stderr.startswith('network-audit:')


def test_the_audit_script_has_help() -> None:
    result = _audit('--help')
    assert result.returncode == 0
    for flag in ('--config', '--output-dir', '--planned-switches'):
        assert flag in result.stdout
