"""The read-only live-check harness (``scripts/live_check.py``, issue 039): its pure parts.

The network-facing parts (the CLI in process, the fresh uvx MCP child) run only by hand
against the maintainer's controller; these tests pin what must hold before anything is sent
and after everything is written: the config is the only source of a switch or a port, a
target the exclusions cover is refused, outputs go under the XDG state root, and a secret
value in any output fails the run.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from tests.script_modules import load_script


CONFIG = """
switch = "core"
port = 7
exclude_switches = ["edge"]
exclude_ports = ["core/1"]
required_vlans = [10, 20]
"""


@pytest.fixture
def live_check(monkeypatch: pytest.MonkeyPatch) -> object:
    return load_script('live_check', monkeypatch)


def test_the_config_names_the_targets_and_nothing_is_hard_coded(
    live_check: object, tmp_path: Path
) -> None:
    (tmp_path / 'c.toml').write_text(CONFIG)
    cfg = live_check.load_config(tmp_path / 'c.toml', tmp_path)  # type: ignore[attr-defined]
    assert (cfg.switch, cfg.port, cfg.required_vlans) == ('core', 7, [10, 20])
    assert cfg.exclude_switches == ['edge'] and cfg.exclude_ports == ['core/1']
    assert cfg.checkout == tmp_path  # the repository the script lives in, unless configured
    assert cfg.cli_commands and cfg.mcp_tools
    source = Path(live_check.__file__).read_text()  # type: ignore[attr-defined]
    assert "'switch': cfg.switch" in source and 'port = ' not in source.split('"""')[2]


@pytest.mark.parametrize(
    'config',
    [
        'switch = "edge"\nport = 3\nexclude_switches = ["edge"]\n',
        'switch = "core"\nport = 1\nexclude_ports = ["core/1"]\n',
    ],
)
def test_a_target_the_exclusions_cover_is_refused(
    live_check: object, tmp_path: Path, config: str
) -> None:
    (tmp_path / 'c.toml').write_text(config)
    with pytest.raises(SystemExit, match='own exclusions'):
        live_check.load_config(tmp_path / 'c.toml', tmp_path)  # type: ignore[attr-defined]


def test_a_missing_or_incomplete_config_is_a_clear_exit(
    live_check: object, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit, match='config not found'):
        live_check.load_config(tmp_path / 'none.toml', tmp_path)  # type: ignore[attr-defined]
    (tmp_path / 'c.toml').write_text('switch = "core"\n')
    with pytest.raises(SystemExit, match="lacks the required key 'port'"):
        live_check.load_config(tmp_path / 'c.toml', tmp_path)  # type: ignore[attr-defined]


def test_the_run_directory_is_under_the_xdg_state_root_and_private(
    live_check: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    out = live_check.run_dir()  # type: ignore[attr-defined]
    assert out.parent == tmp_path / 'state' / 'unifi_mapper' / 'live-check'
    assert (out.stat().st_mode & 0o777) == 0o700


def test_a_secret_value_in_any_output_fails_the_run_naming_the_variable_only(
    live_check: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', 'tok-planted-0001')  # pragma: allowlist secret
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', 'pw-planted-0002')  # pragma: allowlist secret
    monkeypatch.setenv('UNIFI_SITE', 'default')  # not a secret: not scanned
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'out.txt').write_text('fine\n')
    (tmp_path / 'leak.json').write_text(json.dumps({'x': 'tok-planted-0001'}))
    report = live_check.Report()  # type: ignore[attr-defined]
    live_check.scan_outputs(tmp_path, report)  # type: ignore[attr-defined]
    (check,) = report.checks
    assert check.status == 'fail'
    assert 'UNIFI_CONSOLE_API_TOKEN in leak.json' in check.detail
    assert 'tok-planted-0001' not in check.detail and 'pw-planted-0002' not in check.detail
    assert report.failed


def test_a_clean_output_tree_passes_the_scan(
    live_check: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', 'tok-planted-0001')  # pragma: allowlist secret
    (tmp_path / 'report.json').write_text('{}')
    report = live_check.Report()  # type: ignore[attr-defined]
    live_check.scan_outputs(tmp_path, report)  # type: ignore[attr-defined]
    assert [c.status for c in report.checks] == ['pass'] and not report.failed


def test_unverified_checks_do_not_fail_the_run(live_check: object) -> None:
    report = live_check.Report()  # type: ignore[attr-defined]
    live_check.check_protect(report)  # type: ignore[attr-defined]
    assert report.checks[-1].status == 'unverified' and not report.failed
