"""`scripts/unifi-cron.sh` upgrades: stale installed commands are flagged and replaced.

Regression (code-review F5): install copies each TASKS command into a plist or crontab
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

    assert run('update').returncode == 0
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

    install = run('install')
    assert install.returncode == 0, install.stderr
    calls = (root / 'launchctl.log').read_text().splitlines()
    plist_calls = [c for c in calls if c.endswith(str(plist))]
    assert plist_calls == [f'unload {plist}', f'load {plist}']  # unload before load
    assert f'<string>{_command(f"{OLD_NAMING} --apply")}</string>' in plist.read_text()

    assert 'stale' not in run('status').stdout
