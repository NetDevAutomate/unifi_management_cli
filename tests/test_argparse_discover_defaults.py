"""Issue 015: the two argparse twins of `discover` preview by default, as `unifi-mapper` does.

`unifi-network-toolkit discover` and `python -m unifi_mapper.cli` wrote port names unless
`--dry-run` was passed, while `unifi-mapper discover` (issue 007) previews unless `--apply`
is given. Both reach the same `run_port_mapper` / `batch_update_port_names` path, which PUTs
`port_overrides` and force-provisions the switch, so the same word must mean the same thing in
every entry point. The mapper and the runner are faked at the same seams as
``tests/test_discover_defaults.py`` uses; no test here reaches a controller.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unifi_mapper import cli as legacy_cli
from unifi_mapper import network_cli, port_mapper, run_methods, smart_port_mapper


pytestmark = pytest.mark.usefixtures('block_network')


@dataclass
class Recorder:
    run_dry_run: list[bool] = field(default_factory=list)
    smart_dry_run: list[bool] = field(default_factory=list)
    writes: list[object] = field(default_factory=list)


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Recorder:
    recorder = Recorder()
    env = tmp_path / 'site.env'
    env.write_text('UNIFI_URL=https://203.0.113.10\nUNIFI_CONSOLE_API_TOKEN=test-token-value\n')
    monkeypatch.setenv('UNIFI_CONFIG', str(env))
    monkeypatch.chdir(tmp_path)

    class FakeMapper:
        def __init__(self, **_kwargs: Any) -> None:
            self.api_client = object()

        def batch_update_port_names(self, *args: object, **_kwargs: object) -> bool:
            recorder.writes.append(args)
            return True

    def fake_run_port_mapper(*, port_mapper: FakeMapper, dry_run: bool, **_: object):
        recorder.run_dry_run.append(dry_run)
        if not dry_run:
            port_mapper.batch_update_port_names({})
        return [], []

    class FakeSmartMapper:
        def __init__(self, _api_client: object) -> None:
            pass

        def smart_update_ports(self, *_args: object, dry_run: bool, **_kwargs: object):
            recorder.smart_dry_run.append(dry_run)
            if not dry_run:
                recorder.writes.append('smart')
            return {}

        def generate_smart_mapping_report(self, _results: object) -> str:
            return 'smart report'

    monkeypatch.setattr(port_mapper, 'UnifiPortMapper', FakeMapper)
    monkeypatch.setattr(run_methods, 'run_port_mapper', fake_run_port_mapper)
    monkeypatch.setattr(run_methods, 'get_devices_and_lldp_data', lambda *_: ([], {}))
    monkeypatch.setattr(smart_port_mapper, 'SmartPortMapper', FakeSmartMapper)
    return recorder


def _toolkit(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr('sys.argv', ['unifi-network-toolkit', *argv])
    try:
        network_cli.main()
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _legacy(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr('sys.argv', ['unifi-mapper', *argv])
    try:
        legacy_cli.main()
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def test_toolkit_discover_previews_by_default(rec: Recorder, monkeypatch) -> None:
    assert _toolkit(monkeypatch, 'discover') == 0
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_toolkit_discover_dry_run_is_still_accepted(rec: Recorder, monkeypatch) -> None:
    assert _toolkit(monkeypatch, 'discover', '--dry-run') == 0
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_toolkit_discover_apply_writes(rec: Recorder, monkeypatch) -> None:
    assert _toolkit(monkeypatch, 'discover', '--apply') == 0
    assert rec.run_dry_run == [False]
    assert rec.writes == [({},)]


def test_toolkit_discover_apply_with_dry_run_is_rejected(rec: Recorder, monkeypatch) -> None:
    assert _toolkit(monkeypatch, 'discover', '--apply', '--dry-run') == 2
    assert rec.writes == []


def test_legacy_cli_previews_by_default(rec: Recorder, monkeypatch) -> None:
    assert _legacy(monkeypatch) == 0
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_legacy_cli_apply_writes(rec: Recorder, monkeypatch) -> None:
    assert _legacy(monkeypatch, '--apply') == 0
    assert rec.run_dry_run == [False]
    assert rec.writes == [({},)]


def test_legacy_cli_verify_updates_previews_through_the_smart_mapper(
    rec: Recorder, monkeypatch
) -> None:
    assert _legacy(monkeypatch, '--verify-updates') == 0
    assert rec.smart_dry_run == [True]
    assert rec.run_dry_run == [True]  # the compatibility report run is always a preview
    assert rec.writes == []


def test_legacy_cli_apply_with_dry_run_is_rejected(rec: Recorder, monkeypatch) -> None:
    assert _legacy(monkeypatch, '--apply', '--dry-run') == 2
    assert rec.writes == []
