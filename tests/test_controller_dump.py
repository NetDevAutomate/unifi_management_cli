"""``scripts/controller_dump.py`` and ``scripts/network-audit.sh`` (design section 4.13).

The dump reads through the real read-only guard over the house fake session (no socket),
writes only stripped payloads and a manifest with the guard's request audit, and refuses an
``--output`` inside the repository. The audit script is only syntax-checked and its
argument handling run: every step it runs needs a controller.
"""

import json
import os
import pytest
import shlex
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


def test_an_endpoint_error_is_redacted_in_the_manifest_and_on_stderr(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """M4 council NBF-001: the error text is redacted where it is made (diagnostic_reads)."""
    body = 'upstream said password=FAKE-DUMP-HTTP-BODY-PW'  # pragma: allowlist secret
    session = FakeSession({('GET', rf'^{API_RE}/stat/sta$'): (500, body)})
    monkeypatch.setattr(mod, '_login', lambda _path: (fake_client(session), 'default'))
    output = tmp_path / 'out'
    assert mod.main(['--output', str(output), '--endpoint', 'sta']) == 1
    err = capsys.readouterr().err
    manifest = (output / 'manifest.json').read_text(encoding='utf-8')
    assert 'FAKE-DUMP-HTTP-BODY-PW' not in err and 'FAKE-DUMP-HTTP-BODY-PW' not in manifest
    assert 'sta: GET' in err and '***redacted***' in err and 'HTTP 500' in manifest


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
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in ('link.json', 'plain.json'):
            with pytest.raises(FileExistsError):
                mod._write_private(dir_fd, name, {'a': 1})
    finally:
        os.close(dir_fd)
    assert victim.read_text(encoding='utf-8') == 'keep me\n'
    assert plain.read_text(encoding='utf-8') == 'old\n'


def test_a_symlinked_output_directory_is_refused(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """M4 council BF-004: the checks followed a link to an empty private directory."""
    target = tmp_path / 'elsewhere'
    target.mkdir(mode=0o700)
    link = tmp_path / 'out'
    link.symlink_to(target, target_is_directory=True)
    attempts = _no_login(mod, monkeypatch)
    assert mod.main(['--output', str(link)]) == 2 and attempts == []
    assert 'symbolic link' in capsys.readouterr().err
    assert list(target.iterdir()) == []


def test_a_dump_writes_only_into_the_directory_it_opened(mod: Any, tmp_path: Path) -> None:
    """A directory swapped for a link after the checks is refused when the dump opens it."""
    target = tmp_path / 'elsewhere'
    target.mkdir(mode=0o700)
    link = tmp_path / 'out'
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        mod.dump(fake_client(_session()), 'default', link, ['wlanconf'])
    assert list(target.iterdir()) == []


def test_an_output_directory_that_cannot_be_checked_is_refused(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """M4 council NBF-002: an unreadable directory ended in a traceback, not one line."""
    output = tmp_path / 'out'
    output.mkdir(mode=0o700)
    output.chmod(0o300)  # no read bit: listing it fails
    attempts = _no_login(mod, monkeypatch)
    try:
        assert mod.main(['--output', str(output)]) == 2 and attempts == []
    finally:
        output.chmod(0o700)
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'cannot check --output' in err


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


def test_a_failed_logout_is_one_redacted_line_never_a_traceback(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """M4 council BF-001: the logout ran in a bare finally, outside the redacted paths."""
    client = fake_client(_session())

    def _logout() -> bool:
        raise RuntimeError(
            'logout failed password=FAKE-DUMP-LOGOUT-PW'
        )  # pragma: allowlist secret

    monkeypatch.setattr(client, 'logout', _logout)
    monkeypatch.setattr(mod, '_login', lambda _path: (client, 'default'))
    output = tmp_path / 'out'
    assert mod.main(['--output', str(output), '--endpoint', 'wlanconf']) == 0
    err = capsys.readouterr().err
    assert 'FAKE-DUMP-LOGOUT-PW' not in err and 'Traceback' not in err
    assert [line for line in err.splitlines() if 'logout' in line] == [
        'controller_dump: logout failed (the dump is complete): logout failed '
        'password=***redacted***'
    ]


# --- scripts/network-audit.sh ---------------------------------------------------------------


AUDIT = SCRIPTS / 'network-audit.sh'


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
def test_the_audit_script_refuses_bad_arguments_with_exit_2(
    tmp_path: Path, args: list[str]
) -> None:
    result = _run_audit(tmp_path, *args)
    assert result.returncode == 2 and result.stderr.startswith('network-audit:')
    assert not (tmp_path / 'uv.log').exists()  # refused before any step


def test_the_audit_script_has_help(tmp_path: Path) -> None:
    result = _run_audit(tmp_path, '--help')
    assert result.returncode == 0 and not (tmp_path / 'uv.log').exists()
    for flag in ('--config', '--output-dir', '--planned-switches'):
        assert flag in result.stdout
    flat = ' '.join(result.stdout.split())
    assert 'also check 10G uplink readiness for N planned switches' in flat  # review N1
    assert '--planned-switches 3' in flat  # an example value
    assert 'Rebuilt from' not in flat  # the maintainers' note is not help


def _fake_uv_env(tmp_path: Path) -> dict[str, str]:
    """An environment whose ``uv`` only records its arguments: no step reaches anything."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    fake = bin_dir / 'uv'
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_UV_LOG"\n', encoding='utf-8')
    fake.chmod(0o700)
    return {
        'PATH': f'{bin_dir}:/usr/bin:/bin',
        'HOME': str(tmp_path),
        'FAKE_UV_LOG': str(tmp_path / 'uv.log'),
    }


def test_a_relative_xdg_state_home_is_ignored_for_the_default_output(tmp_path: Path) -> None:
    """Review N2: the XDG spec ignores a relative path; honoured, it was the working directory."""
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    env = {**_fake_uv_env(tmp_path), 'XDG_STATE_HOME': 'state'}
    result = subprocess.run(
        ['bash', str(AUDIT)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=cwd,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    audits = tmp_path / '.local' / 'state' / 'unifi_mapper' / 'audits'
    assert [p.name for p in audits.iterdir()] and list(cwd.iterdir()) == []
    assert f'Reports: {audits}/' in result.stdout


def _run_audit(tmp_path: Path, *args: str, cwd: Path | None = None) -> Any:
    """Run the audit script with a fake ``uv`` (``_fake_uv_env``), never the real one.

    Review SR6-S1: every case runs through this, so no case inherits the developer's PATH,
    HOME or UNIFI_* variables, which could reach the live controller.
    """
    return subprocess.run(
        ['bash', str(AUDIT), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=_fake_uv_env(tmp_path),
        cwd=cwd,
        check=False,
    )


@pytest.mark.parametrize(
    ('prepare', 'message'),
    [
        (lambda d: (d.mkdir(mode=0o700), (d / 'audit.log').write_text('x\n')), 'new or empty'),
        (lambda d: (d.mkdir(), d.chmod(0o770)), 'writable by other users'),
        (lambda d: (d.mkdir(), d.chmod(0o703)), 'writable by other users'),
        (
            lambda d: (
                d.with_name('target').mkdir(mode=0o700),
                d.symlink_to(d.with_name('target'), target_is_directory=True),
            ),
            'symbolic link',
        ),
        (lambda d: d.write_text('x\n'), 'not a directory'),
    ],
    ids=['not empty', 'group-writable', 'other-writable', 'a symlink', 'a file'],
)
def test_an_unsafe_existing_output_dir_is_refused_before_any_step(
    tmp_path: Path, prepare: Any, message: str
) -> None:
    """M4 council BF-002: the reports and audit.log went into whatever directory was given,
    appending to a log already there; nothing planted there may receive them."""
    out = tmp_path / 'audit'
    prepare(out)
    result = _run_audit(tmp_path, '--output-dir', str(out))
    assert result.returncode == 2 and message in result.stderr
    assert not (tmp_path / 'uv.log').exists()  # no step ran


def test_an_empty_private_output_dir_is_used(tmp_path: Path) -> None:
    out = tmp_path / 'audit'
    out.mkdir(mode=0o700)
    result = _run_audit(tmp_path, '--output-dir', str(out))
    assert result.returncode == 0, result.stderr
    assert (out / 'audit.log').exists()
    assert stat.S_IMODE((out / 'audit.log').stat().st_mode) == 0o600


def test_the_printed_apply_commands_carry_the_audits_own_config(tmp_path: Path) -> None:
    """Review B6: pasted with --apply, a bare command acted on the default config's controller."""
    config = tmp_path / 'site a.env'  # a space: the printed command must quote it
    config.write_text('UNIFI_URL=https://192.0.2.1\n', encoding='utf-8')
    out = tmp_path / 'audit out'
    result = subprocess.run(
        ['bash', str(AUDIT), '--config', str(config), '--output-dir', str(out)],
        capture_output=True,
        text=True,
        timeout=60,
        env=_fake_uv_env(tmp_path),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    printed = [shlex.split(line) for line in result.stdout.splitlines() if line.startswith('  ')]
    mapper = ['uv', 'run', '--project', str(REPO), 'unifi-mapper', '--config', str(config)]
    assert [argv[:7] for argv in printed] == [mapper, mapper]
    assert printed[0][7:] == ['ports', 'refresh']
    assert printed[1][7:] == ['stp', 'apply', '--plan', str(out / 'stp-plan.json')]
    ran = (tmp_path / 'uv.log').read_text(encoding='utf-8').splitlines()
    assert len(ran) == 6 and all(f'--config {config}' in line for line in ran)
    assert not any('--apply' in line or '--no-dry-run' in line for line in ran)


def test_relative_paths_are_printed_absolute(tmp_path: Path) -> None:
    """M4 council BF-003: a relative --config was printed as given, so the pasted command
    read another file from another directory; the guide says it works from any directory."""
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    (run_dir / 'site.env').write_text('UNIFI_URL=https://192.0.2.1\n', encoding='utf-8')
    result = _run_audit(tmp_path, '--config', 'site.env', '--output-dir', 'out', cwd=run_dir)
    assert result.returncode == 0, result.stderr
    printed = [shlex.split(line) for line in result.stdout.splitlines() if line.startswith('  ')]
    assert [argv[6] for argv in printed] == [str(run_dir / 'site.env')] * 2
    assert printed[1][-1] == str(run_dir / 'out' / 'stp-plan.json')
    assert f'Reports: {run_dir / "out"}' in result.stdout


# A uv that records its arguments as _fake_uv_env's does, and whose discover step then writes
# the files `unifi-mapper discover` writes: the report's and the diagram's directories first
# (./reports/ and ./diagrams/ without -o and -d), then the DOT source at the diagram path
# minus .png, which graphviz replaces with the PNG only once Graphviz's dot has drawn it, and
# then the report. With dot missing it exits 1, the DOT source left behind.
FAKE_DISCOVER_UV = """#!/bin/sh
printf "%s\\n" "$*" >> "$FAKE_UV_LOG"
case " $* " in *" discover "*) ;; *) exit 0 ;; esac
diagram="$PWD/diagrams/network_diagram.png"
report="$PWD/reports/port_mapping_report.md"
while [ $# -gt 0 ]; do
    case "$1" in
        -d | --diagram) diagram="$2"; shift 2 ;;
        -o | --output) report="$2"; shift 2 ;;
        *) shift ;;
    esac
done
mkdir -p "$(dirname "$report")" "$(dirname "$diagram")"
printf 'digraph {}\\n' > "${diagram%.png}"
[ "$FAKE_DOT" = present ] || exit 1
mv "${diagram%.png}" "$diagram"
printf 'report\\n' > "$report"
"""


@pytest.mark.parametrize('dot', ['present', 'missing'], ids=['dot present', 'dot missing'])
def test_the_audit_draws_its_diagram_in_its_output_dir_never_the_cwd(
    tmp_path: Path, dot: str
) -> None:
    """Review AGG-1: step 1 ran discover with no -d, so its diagram, or without Graphviz's
    dot the DOT source naming the site's devices, landed in the caller's directory."""
    env = _fake_uv_env(tmp_path)
    (tmp_path / 'bin' / 'uv').write_text(FAKE_DISCOVER_UV, encoding='utf-8')
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    out = tmp_path / 'out'
    result = subprocess.run(
        ['bash', str(AUDIT), '--output-dir', str(out)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**env, 'FAKE_DOT': dot},
        cwd=cwd,
        check=False,
    )
    assert list(cwd.iterdir()) == []
    ran = (tmp_path / 'uv.log').read_text(encoding='utf-8').splitlines()
    discover = [line.split() for line in ran if ' discover ' in line]
    assert len(discover) == 1
    assert discover[0][discover[0].index('-d') + 1] == str(out / 'network-diagram.png')
    if dot == 'present':
        assert result.returncode == 0, result.stderr
        assert {'network-diagram.png', 'port-mapping.md'} <= {p.name for p in out.iterdir()}
    else:
        assert result.returncode == 1
        assert '-- Port names (preview): FAILED' in result.stdout
        assert (out / 'network-diagram').is_file()  # the DOT source stays in the private dir
