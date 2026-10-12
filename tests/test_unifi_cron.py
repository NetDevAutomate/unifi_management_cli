"""`scripts/unifi-cron.sh` upgrades: stale installed commands are flagged and replaced.

Regression: install copies each TASKS command into a plist or crontab
line, so a schedule installed before `--apply`/`--record` keeps its old command line.
`status` must say so, and a re-run of `install` on macOS must replace a loaded job
(`launchctl load` of a loaded label fails, and the script swallowed the error).

The script runs for real under bash, with fake `uname`, `launchctl` and `crontab` on
PATH and HOME/LOG_DIR in a temp dir, so nothing on this machine is scheduled or changed.
"""

import pytest
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'unifi-cron.sh'
PROJECT = SCRIPT.parents[1]
UV = '/fake/bin/uv'
OLD_NAMING = '--verify-updates --connected-devices'
OLD_SNAPSHOT = 'analyze link-errors --snapshot'

pytestmark = pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')


def _fake_bin(tmp_path: Path, os_name: str) -> Path:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    scripts = {
        'uname': f'#!/bin/sh\necho {os_name}\n',
        'launchctl': (
            '#!/bin/sh\necho "$@" >> "$FAKE_LAUNCHCTL_LOG"\n[ "$1" = list ] && exit 1\nexit 0\n'
        ),
        'crontab': (
            '#!/bin/sh\n'
            'if [ "$1" = -l ]; then [ -f "$FAKE_CRONTAB" ] || exit 1; cat "$FAKE_CRONTAB"; '
            'else cat > "$FAKE_CRONTAB"; fi\n'
        ),
    }
    for name, body in scripts.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    return bin_dir


@pytest.fixture
def cron(tmp_path):
    """Run the script with one OS faked; returns (run, paths)."""

    def make(os_name: str):
        root = tmp_path / os_name
        root.mkdir()
        bin_dir = _fake_bin(root, os_name)
        env = {
            'PATH': f'{bin_dir}:/usr/bin:/bin',
            'HOME': str(root / 'home'),
            'LOG_DIR': str(root / 'logs'),
            'UV_BIN': UV,
            'FAKE_LAUNCHCTL_LOG': str(root / 'launchctl.log'),
            'FAKE_CRONTAB': str(root / 'crontab.txt'),
        }
        (root / 'home').mkdir()

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ['bash', str(SCRIPT), *args],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        return run, root, env

    return make


def _command(cmd: str) -> str:
    return f'cd {PROJECT} && {UV} run unifi-mapper {cmd}'


def test_linux_status_flags_lines_installed_before_the_current_tasks(cron):
    run, root, env = cron('Linux')
    log_dir = env['LOG_DIR']
    marker = '# UNIFI-MANAGEMENT-CLI'
    snapshot_line = f'{_command(OLD_SNAPSHOT)} >> {log_dir}/link-error-snapshot.log 2>&1'
    (root / 'crontab.txt').write_text(
        '0 0 * * * echo unrelated\n'
        f'*/5 * * * * {snapshot_line} {marker}\n'
        f'*/30 * * * * {_command(OLD_NAMING)} >> {log_dir}/port-naming.log 2>&1 {marker}\n'
    )

    stale = run('status')

    assert stale.returncode == 0, stale.stderr
    assert 'link-error-snapshot: stale or missing' in stale.stdout
    assert 'port-naming: stale or missing' in stale.stdout
    assert "update' to reinstall" in stale.stdout

    assert run('update', '--with-port-naming').returncode == 0
    crontab = (root / 'crontab.txt').read_text()
    assert 'echo unrelated' in crontab
    assert _command('analyze link-errors --record') in crontab
    assert _command(f'{OLD_NAMING} --apply') in crontab
    assert _command(OLD_SNAPSHOT) not in crontab

    current = run('status')
    assert current.returncode == 0, current.stderr
    assert 'stale' not in current.stdout and 'to reinstall' not in current.stdout


def test_macos_status_flags_a_stale_plist_and_install_replaces_a_loaded_job(cron):
    run, root, env = cron('Darwin')
    agents = root / 'home' / 'Library' / 'LaunchAgents'
    agents.mkdir(parents=True)
    plist = agents / 'com.unifi-management.port-naming.plist'
    plist.write_text(f'<plist><string>{_command(OLD_NAMING)}</string></plist>\n')

    stale = run('status')
    assert stale.returncode == 0, stale.stderr
    assert 'stale: installed command differs from: unifi-mapper ' in stale.stdout
    assert f'{OLD_NAMING} --apply' in stale.stdout
    assert "update' to reinstall" in stale.stdout

    install = run('install', '--with-port-naming')
    assert install.returncode == 0, install.stderr
    calls = (root / 'launchctl.log').read_text().splitlines()
    plist_calls = [c for c in calls if c.endswith(str(plist))]
    assert plist_calls == [f'unload {plist}', f'load {plist}']  # unload before load
    escaped = _command(f'{OLD_NAMING} --apply').replace('&', '&amp;')
    assert f'<string>{escaped}</string>' in plist.read_text()

    assert 'stale' not in run('status').stdout


def test_macos_status_accepts_every_plist_that_install_writes(cron):
    """Code-review F10: the stale check must use install's encoding, whatever it becomes.

    Issue 025's fix changes how install writes the command (XML-escaped, or an argv
    ProgramArguments). This round trip doesn't pin the encoding, only that status reads back
    what install wrote, so a fix that changes one side but not the other fails here.
    """
    run, root, _ = cron('Darwin')

    install = run('install')
    assert install.returncode == 0, install.stderr
    plists = sorted((root / 'home' / 'Library' / 'LaunchAgents').glob('*.plist'))
    assert plists, 'install wrote no plists'

    status = run('status')
    assert status.returncode == 0, status.stderr
    assert 'stale' not in status.stdout and 'to reinstall' not in status.stdout


# --- the task tables stay in step (0.2.0 port: wan-speedtest-record) -----------------------


def _bash_array(name: str) -> list[str]:
    text = SCRIPT.read_text(encoding='utf-8')
    body = text.split(f'{name}=(', 1)[1].split('\n)', 1)[0]
    return [line.split('#', 1)[0].strip().strip('"') for line in body.splitlines() if '"' in line]


def _run_all_body() -> str:
    text = SCRIPT.read_text(encoding='utf-8')
    return text.split('run_all() {', 1)[1].split('\n}', 1)[0]


def test_tasks_and_cron_schedules_are_parallel_arrays() -> None:
    tasks, schedules = _bash_array('TASKS'), _bash_array('CRON_SCHEDULES')
    assert len(tasks) == len(schedules) >= 6
    names = [task.split('|')[0] for task in tasks]
    assert schedules[names.index('wan-speedtest-record')] == '0 * * * *'


def test_every_task_command_is_in_run_all() -> None:
    body = _run_all_body()
    for task in _bash_array('TASKS'):
        _name, _interval, command = task.split('|')
        assert f'unifi-mapper {command}' in body, command


def test_the_wan_record_task_reads_only_and_runs_before_port_naming() -> None:
    tasks = _bash_array('TASKS')
    assert 'wan-speedtest-record|3600|diagnose wan --record' in tasks
    body = _run_all_body()
    wan = body.index('unifi-mapper diagnose wan --record')
    naming = body.index('unifi-mapper --verify-updates --connected-devices --apply')
    assert wan < naming
    assert _port_naming_task() == 'port-naming|1800|--verify-updates --connected-devices --apply'


# --- issue 025: valid plists, and port naming is opt-in ------------------------------------


def _port_naming_task() -> str:
    text = SCRIPT.read_text(encoding='utf-8')
    return text.split('PORT_NAMING_TASK="', 1)[1].split('"', 1)[0]


def test_every_plist_install_writes_is_valid_xml_and_keeps_the_command(cron):
    """The command holds `&&`, which an unescaped plist cannot carry; launchd refused every
    job (issue 025). Parse what install writes with plistlib and read the command back."""
    import plistlib

    run, root, _ = cron('Darwin')
    assert run('install', '--with-port-naming').returncode == 0
    plists = sorted((root / 'home' / 'Library' / 'LaunchAgents').glob('*.plist'))
    assert len(plists) == 7
    commands = {}
    for path in plists:
        data = plistlib.loads(path.read_bytes())  # raises on invalid XML
        assert data['ProgramArguments'][:2] == ['/bin/bash', '-c']
        commands[path.name] = data['ProgramArguments'][2]
        assert data['StartInterval'] > 0
    assert commands['com.unifi-management.port-naming.plist'] == _command(f'{OLD_NAMING} --apply')
    assert commands['com.unifi-management.diagnose-all.plist'] == _command('diagnose all')


def test_install_without_the_flag_schedules_no_write(cron):
    """A fresh install runs read-only audits only: no port-naming job is written (macOS) or
    added (Linux), and status says the job is opt-in rather than missing."""
    run, root, _ = cron('Darwin')
    assert run('install').returncode == 0
    agents = root / 'home' / 'Library' / 'LaunchAgents'
    assert not (agents / 'com.unifi-management.port-naming.plist').exists()
    assert len(list(agents.glob('*.plist'))) == 6
    status = run('status')
    assert status.returncode == 0, status.stderr
    assert 'port-naming: not installed' in status.stdout
    assert '--with-port-naming' in status.stdout
    assert 'stale' not in status.stdout

    run, root, _ = cron('Linux')
    assert run('install').returncode == 0
    crontab = (root / 'crontab.txt').read_text()
    assert '--apply' not in crontab
    assert _command('diagnose all') in crontab
    status = run('status')
    assert 'port-naming: not installed' in status.stdout
    assert 'stale' not in status.stdout and 'to reinstall' not in status.stdout


def test_install_with_the_flag_schedules_port_naming_on_both_platforms(cron):
    run, root, _ = cron('Linux')
    assert run('install', '--with-port-naming').returncode == 0
    crontab = (root / 'crontab.txt').read_text()
    assert f'*/30 * * * * {_command(f"{OLD_NAMING} --apply")}' in crontab
    status = run('status')
    assert 'port-naming: not installed' not in status.stdout
    assert 'stale' not in status.stdout

    run, root, _ = cron('Darwin')
    assert run('update', '--with-port-naming').returncode == 0
    assert (
        root / 'home' / 'Library' / 'LaunchAgents' / 'com.unifi-management.port-naming.plist'
    ).exists()


def test_uninstall_removes_an_opted_in_port_naming_job(cron):
    run, root, _ = cron('Darwin')
    assert run('install', '--with-port-naming').returncode == 0
    assert run('uninstall').returncode == 0
    assert not list((root / 'home' / 'Library' / 'LaunchAgents').glob('*.plist'))


def test_run_all_applies_port_names_only_with_the_flag() -> None:
    """`run-all` without `--with-port-naming` must not reach the `--apply` line."""
    body = _run_all_body()
    naming = [line for line in body.splitlines() if '--apply' in line]
    assert naming, 'run_all lost its opt-in port-naming step'
    guard_index = body.index('WITH_PORT_NAMING')
    assert all(body.index(line) > guard_index for line in naming)
    assert _port_naming_task() == 'port-naming|1800|--verify-updates --connected-devices --apply'
    assert all('port-naming' not in task for task in _bash_array('TASKS'))


# --- pass-2 validation: shell quoting of the paths, and a kept opt-in job is reported --------


def test_a_checkout_path_with_a_space_and_an_ampersand_is_shell_quoted(tmp_path):
    """`bash -c` runs the plist command, so an unquoted PROJECT_DIR or UV_BIN with a space
    or `&` would split or fork it. Both are shell-quoted before the XML escaping."""
    import plistlib
    import shlex

    odd = tmp_path / 'Odd & Dir' / 'unifi_management_cli'
    (odd / 'scripts').mkdir(parents=True)
    script = odd / 'scripts' / 'unifi-cron.sh'
    script.write_text(SCRIPT.read_text())
    script.chmod(0o755)
    bin_dir = _fake_bin(tmp_path, 'Darwin')
    uv = tmp_path / 'tools & bins' / 'uv'
    uv.parent.mkdir()
    uv.write_text('#!/bin/sh\nexit 0\n')
    uv.chmod(0o755)
    env = {
        'PATH': f'{bin_dir}:/usr/bin:/bin',
        'HOME': str(tmp_path / 'home'),
        'LOG_DIR': str(tmp_path / 'logs'),
        'UV_BIN': str(uv),
        'FAKE_LAUNCHCTL_LOG': str(tmp_path / 'launchctl.log'),
        'FAKE_CRONTAB': str(tmp_path / 'crontab.txt'),
    }
    (tmp_path / 'home').mkdir()
    result = subprocess.run(
        ['bash', str(script), 'install'], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    plist = (
        tmp_path / 'home' / 'Library' / 'LaunchAgents' / 'com.unifi-management.diagnose-all.plist'
    )
    command = plistlib.loads(plist.read_bytes())['ProgramArguments'][2]
    # The command splits back into exactly the words bash -c will run: cd <dir> && <uv> run …
    words = shlex.split(command)
    assert words[:2] == ['cd', str(odd)]
    assert words[2] == '&&'
    assert words[3:6] == [str(uv), 'run', 'unifi-mapper']
    # And status reads the same encoding back without calling it stale.
    status = subprocess.run(
        ['bash', str(script), 'status'], env=env, capture_output=True, text=True, timeout=30
    )
    assert 'stale' not in status.stdout


def test_install_without_the_flag_keeps_and_reports_an_earlier_opt_in(cron):
    """A plain `install` adds the defaults and leaves an opted-in port-naming job in place,
    but says so, so an upgrade from the old always-on default is not silent."""
    run, root, _ = cron('Darwin')
    assert run('install', '--with-port-naming').returncode == 0
    second = run('install')
    assert second.returncode == 0, second.stderr
    assert 'port-naming' in second.stdout and 'kept' in second.stdout
    assert '--with-port-naming' in second.stdout and 'uninstall' in second.stdout
    agents = root / 'home' / 'Library' / 'LaunchAgents'
    assert (agents / 'com.unifi-management.port-naming.plist').exists()

    run, root, _ = cron('Linux')
    assert run('install', '--with-port-naming').returncode == 0
    second = run('install')
    assert 'port-naming' in second.stdout and 'kept' in second.stdout
    assert '--apply' in (root / 'crontab.txt').read_text()
