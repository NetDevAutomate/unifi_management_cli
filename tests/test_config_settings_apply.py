"""The five documented settings reach `unifi-mapper` (issue 042).

`UNIFI_DEFAULT_FORMAT`, `UNIFI_OUTPUT_DIR` and `UNIFI_DIAGRAM_DIR` are `discover`'s defaults
when the matching option is not given; `UNIFI_MAX_RETRIES` and `UNIFI_RETRY_DELAY` reach the
API client wherever a `UnifiConfig` builds one. The collaborators are faked at the seams
``tests/test_discover_defaults.py`` uses, so nothing here reaches a controller.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typer.testing import CliRunner, Result
from types import SimpleNamespace
from typing import Any
from unifi_mapper import config as config_module
from unifi_mapper import port_mapper, run_methods, typer_cli
from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.config import UnifiConfig
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()


class Recorder:
    def __init__(self) -> None:
        self.mappers: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Recorder:
    """A config whose five settings are all non-default, and fakes that record what reached them."""
    recorder = Recorder()
    monkeypatch.chdir(tmp_path)
    fake_config = SimpleNamespace(
        base_url='https://192.0.2.1',
        site='default',
        api_token='fake-token',  # pragma: allowlist secret
        username=None,
        password=None,
        verify_ssl=False,
        timeout=10,
        max_retries=7,
        retry_delay=2.5,
        default_format='svg',
        default_output_dir=str(tmp_path / 'from-config' / 'reports'),
        default_diagram_dir=str(tmp_path / 'from-config' / 'diagrams'),
    )
    monkeypatch.setattr(
        config_module.UnifiConfig, 'from_env', classmethod(lambda cls, *a, **k: fake_config)
    )
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)

    class FakeMapper:
        def __init__(self, **kwargs: Any) -> None:
            recorder.mappers.append(kwargs)
            self.api_client = object()

    def fake_run_port_mapper(**kwargs: Any):
        recorder.runs.append(kwargs)
        return [], []

    monkeypatch.setattr(port_mapper, 'UnifiPortMapper', FakeMapper)
    monkeypatch.setattr(run_methods, 'run_port_mapper', fake_run_port_mapper)
    return recorder


def _run(*args: str) -> Result:
    result = runner.invoke(app, ['discover', *args])
    assert result.exit_code == 0, result.output
    return result


# --- the three output settings -----------------------------------------------------------------


def test_default_format_applies_when_format_is_not_given(rec: Recorder, tmp_path: Path) -> None:
    _run()
    [run] = rec.runs
    assert run['diagram_format'] == 'svg'
    assert Path(run['diagram_path']).name == 'network_diagram.svg'


def test_format_option_beats_default_format(rec: Recorder) -> None:
    _run('--format', 'html')
    [run] = rec.runs
    assert run['diagram_format'] == 'html'
    assert Path(run['diagram_path']).name == 'network_diagram.html'


def test_output_dir_applies_when_output_is_not_given(rec: Recorder, tmp_path: Path) -> None:
    _run()
    [run] = rec.runs
    assert (
        Path(run['output_path']) == tmp_path / 'from-config' / 'reports' / 'port_mapping_report.md'
    )
    assert (tmp_path / 'from-config' / 'reports').is_dir()


def test_output_option_beats_output_dir(rec: Recorder, tmp_path: Path) -> None:
    _run('--output', str(tmp_path / 'mine.md'))
    [run] = rec.runs
    assert Path(run['output_path']) == tmp_path / 'mine.md'


def test_diagram_dir_applies_when_diagram_is_not_given(rec: Recorder, tmp_path: Path) -> None:
    _run()
    [run] = rec.runs
    assert (
        Path(run['diagram_path']) == tmp_path / 'from-config' / 'diagrams' / 'network_diagram.svg'
    )
    assert (tmp_path / 'from-config' / 'diagrams').is_dir()


def test_diagram_option_beats_diagram_dir(rec: Recorder, tmp_path: Path) -> None:
    _run('--diagram', str(tmp_path / 'mine.png'))
    [run] = rec.runs
    assert Path(run['diagram_path']) == tmp_path / 'mine.png'


def test_a_tilde_in_the_configured_dirs_is_the_home_directory(
    rec: Recorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`.env.example` documents `~/Documents/...`; a literal `~` directory would be a surprise."""
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    config = config_module.UnifiConfig.from_env('x')
    config.default_output_dir = '~/network-reports'
    config.default_diagram_dir = '~/network-diagrams'
    _run()
    [run] = rec.runs
    assert (
        Path(run['output_path'])
        == tmp_path / 'home' / 'network-reports' / 'port_mapping_report.md'
    )
    assert (
        Path(run['diagram_path']) == tmp_path / 'home' / 'network-diagrams' / 'network_diagram.svg'
    )


# --- the two retry settings --------------------------------------------------------------------


def test_discover_hands_max_retries_to_the_client(rec: Recorder) -> None:
    _run()
    [mapper] = rec.mappers
    assert mapper['max_retries'] == 7


def test_discover_hands_retry_delay_to_the_client(rec: Recorder) -> None:
    _run()
    [mapper] = rec.mappers
    assert mapper['retry_delay'] == 2.5


def test_the_port_mapper_passes_both_retry_settings_to_its_api_client() -> None:
    mapper = port_mapper.UnifiPortMapper(
        base_url='https://192.0.2.1', api_token='fake-token', max_retries=7, retry_delay=2.5
    )  # pragma: allowlist secret
    assert isinstance(mapper.api_client, UnifiApiClient)
    assert mapper.api_client.max_retries == 7
    assert mapper.api_client.retry_delay == 2.5


def test_the_readonly_client_gets_both_retry_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`_readonly_client` builds the sync client the read-only diagnostics use."""
    seen: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            seen.append(kwargs)

        def login(self) -> bool:
            return True

        def logout(self) -> bool:
            return True

    config = UnifiConfig(
        base_url='https://192.0.2.1',
        api_token='fake-token',  # pragma: allowlist secret
        max_retries=7,
        retry_delay=2.5,
    )
    monkeypatch.setattr(config_module.UnifiConfig, 'from_env', classmethod(lambda cls, *a: config))
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setattr('unifi_mapper.api_client.UnifiApiClient', FakeClient)
    monkeypatch.setattr(
        'unifi_mapper.core.utils.readonly.install_read_only_guard', lambda *a: None
    )
    with typer_cli._readonly_client() as (client, site):
        assert isinstance(client, FakeClient) and site == 'default'
    [kwargs] = seen
    assert kwargs['max_retries'] == 7 and kwargs['retry_delay'] == 2.5
