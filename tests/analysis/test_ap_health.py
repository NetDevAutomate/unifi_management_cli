"""AP health sampling (``analysis/ap_health.py``) and ``diagnose ap-health``.

Ported from the July work (a local archive, not in the repo) and adapted: documentation values
only; no PoE power-cycle phase (a controller write, W9 in issue 060), no job registry and no
MCP tool (D4), no SSID or ``reports/`` default; every sample read bounded and a timed-out
sample recorded as missing; retry rates only over real intervals; client pings opt-in through
``analysis/gateway_ssh.py``; Ctrl-C ends with a partial report and exit 130. The controller is
the fake behind the real read-only guard; SSH is the shared fake over the root ban.
"""

import asyncio
import asyncssh
import inspect
import json
import pytest
import shlex
from pathlib import Path
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from tests.fake_ssh import FakeSSH
from tests.fixtures_unifi import FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.analysis import ap_health
from unifi_mapper.analysis.ap_health import (
    ApHealthCapture,
    ApSample,
    build_report,
    clients_on_ap,
    expected_duration_seconds,
    interval_rows,
    render_markdown,
    run_ap_health_capture,
    sample_device,
    summarize_samples,
)
from unifi_mapper.core.utils.counters import VapCounters
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.typer_cli import app


runner = CliRunner()
FAKE_SSH_PW = 'FAKE-AP-HEALTH-SSH-PASSWORD'  # pragma: allowlist secret
FAKE_PSK = 'FAKE-WLAN-PASSPHRASE'  # pragma: allowlist secret
AP_MAC = '02:00:00:00:01:01'
REF_MAC = '02:00:00:00:01:02'


def _ap(name: str, mac: str, tx_packets: int, tx_retries: int) -> dict[str, Any]:
    return {
        'name': name,
        'mac': mac,
        'type': 'uap',
        'model': 'U6IW',
        'serial': 'FAKE-SERIAL',
        'version': '6.8.2',
        'state': 1,
        'ip': '192.0.2.21' if mac == AP_MAC else '192.0.2.22',
        'uptime': 3600,
        'x_authkey': 'FAKE-AP-AUTHKEY',  # pragma: allowlist secret
        'system-stats': {'cpu': '15.0', 'mem': '40.0'},
        'sys_stats': {'loadavg_1': '1.2'},
        'uplink': {'type': 'wire', 'speed': 1000, 'full_duplex': True},
        'radio_table': [{'radio': 'ng', 'channel': 11, 'ht': '20', 'tx_power': 12}],
        'radio_table_stats': [
            {'radio': 'ng', 'channel': 11, 'cu_total': 60, 'cu_self_tx': 5, 'num_sta': 10}
        ],
        'vap_table': [
            {
                'essid': 'SSID A',
                'radio': 'ng',
                'channel': 11,
                'num_sta': 8,
                'tx_packets': tx_packets,
                'tx_retries': tx_retries,
            },
            {'essid': 'SSID B', 'radio': 'ng', 'tx_packets': 10, 'tx_retries': 0},
            {'essid': 'SSID C', 'radio': 'na', 'tx_packets': 99999, 'tx_retries': 1},
        ],
    }


def _sample(ts: float, tx_packets: int, tx_retries: int, **kw: Any) -> ApSample:
    vaps = [VapCounters(essid='SSID A', tx_packets=tx_packets, tx_retries=tx_retries)]
    return ApSample(role=kw.pop('role', 'target'), ts=ts, vaps=vaps, **kw)


# --- the pure parts -----------------------------------------------------------------------


def test_a_sample_keeps_the_2_4_ghz_radio_and_vaps_only() -> None:
    s = sample_device(_ap('AP 1', AP_MAC, 5000, 500), 'target', 1.0)
    assert (s.role, s.ts, s.channel, s.cu_total, s.cpu, s.uptime) == (
        'target',
        1.0,
        11,
        60,
        15.0,
        3600,
    )
    assert [v.essid for v in s.vaps] == ['SSID A', 'SSID B']  # the 5 GHz VAP left out
    bare = sample_device({'name': 'Bare', 'uptime': 5}, 'target', 2.0)
    assert bare.channel is None and bare.vaps == [] and bare.missing is False


def test_clients_on_an_ap_are_its_wireless_ones_up_to_four() -> None:
    clients = [
        {'ip': '192.0.2.31', 'ap_mac': AP_MAC, 'is_wired': False},
        {'ip': '192.0.2.32', 'ap_mac': AP_MAC.upper(), 'is_wired': False},
        {'ip': '192.0.2.33', 'ap_mac': REF_MAC, 'is_wired': False},
        {'ip': '192.0.2.34', 'ap_mac': AP_MAC, 'is_wired': True},
        {'ip': None, 'ap_mac': AP_MAC, 'is_wired': False},
    ]
    assert clients_on_ap(clients, AP_MAC) == ['192.0.2.31', '192.0.2.32']
    many = [{'ip': f'198.51.100.{i}', 'ap_mac': AP_MAC} for i in range(1, 10)]
    assert len(clients_on_ap(many, AP_MAC)) == 4


def test_retry_rates_come_from_real_intervals_only() -> None:
    samples = [
        _sample(1, 1000, 100, pings={'192.0.2.31': {'loss_pct': 0}}),
        _sample(2, 2000, 300, pings={'192.0.2.31': {'loss_pct': 10}}),
        ApSample(role='target', ts=3, missing=True, reason='timed out'),
        _sample(4, 3000, 350),
    ]
    rows = interval_rows(samples, 'SSID A')
    assert [r['retry_pct'] for r in rows] == [None, 20.0, None, 5.0]  # no interval before 1
    assert rows[2]['missing'] is True and rows[2]['reason'] == 'timed out'
    (summary,) = summarize_samples(samples, 'SSID A')
    assert summary == {
        'role': 'target',
        'samples': 3,
        'missing': 1,
        'mean_retry_pct': 12.5,
        'retry_intervals': 2,
        'mean_ping_loss_pct': 5.0,
    }


def test_a_quiet_interval_gives_no_retry_rate() -> None:
    samples = [_sample(1, 10, 1), _sample(2, 40, 7)]  # 30 packets: below the floor
    (summary,) = summarize_samples(samples, 'SSID A')
    assert summary['mean_retry_pct'] is None and summary['retry_intervals'] == 0


def _capture(partial_samples: list[ApSample] | None = None) -> ApHealthCapture:
    capture = ApHealthCapture(samples_requested=3, interval_seconds=60)
    capture.samples = partial_samples or [_sample(1, 1000, 100), _sample(2, 2000, 300)]
    capture.target = ap_health.device_block(_ap('AP 1', AP_MAC, 1, 1))
    capture.essid, capture.essid_source = 'SSID A', 'given'
    capture.wlan_configs = [{'name': 'SSID A', 'wpa_mode': 'wpa2', 'iot_channel_lock': True}]
    return capture


def test_the_report_has_its_sections_and_no_power_cycle() -> None:
    report = build_report(_capture(), partial=False)
    assert report['partial'] is False and report['essid'] == 'SSID A'
    assert report['ssid_config']['iot_channel_lock'] is True
    assert report['samples_taken'] == {'target': 2}
    markdown = render_markdown(report)
    for heading in ('# AP Health Report — AP 1', '## Suspect device', '## Summary'):
        assert heading in markdown
    assert 'reset-aware' in markdown and 'iot_channel_lock' in markdown
    assert 'power-cycle' not in markdown.lower() and 'PoE' not in markdown


def test_a_partial_report_says_so() -> None:
    report = build_report(_capture(), partial=True)
    assert report['partial'] is True
    assert 'Partial' in render_markdown(report)


def test_the_expected_duration_is_up_to_ten_hours() -> None:
    assert expected_duration_seconds(60, 600) == 36_000
    assert expected_duration_seconds(1, 30) == 30


def test_there_is_no_ssid_default_and_no_power_cycle_path() -> None:
    signature = inspect.signature(run_ap_health_capture)
    assert signature.parameters['essid'].default is None
    assert 'output' not in signature.parameters  # no reports/ default: the CLI's --output
    source = Path(ap_health.__file__).read_text(encoding='utf-8')
    for marker in ('cmd/devmgr', '.post(', 'power_cycle'):  # the July cycle's call and name
        assert marker not in source


# --- the capture --------------------------------------------------------------------------


class _Counters:
    """Each device read returns the next counters, so the samples differ."""

    def __init__(self) -> None:
        self.reads = 0

    def __call__(self, _request: Any) -> dict[str, Any]:
        self.reads += 1
        n = self.reads
        return legacy(
            [
                _ap('AP 1', AP_MAC, 1000 * n, 100 * n),
                _ap('AP 2', REF_MAC, 1000 * n, 10 * n),
                {'name': 'Switch A', 'mac': '02:00:00:00:00:a1', 'type': 'usw'},
            ]
        )


CLIENTS = [
    {'ip': '192.0.2.31', 'ap_mac': AP_MAC, 'is_wired': False},
    {'ip': '192.0.2.33', 'ap_mac': REF_MAC, 'is_wired': False},
]
WLANS = [{'name': 'SSID A', 'wpa_mode': 'wpa2', 'x_passphrase': FAKE_PSK}]


def _controller() -> FakeController:
    return FakeController(
        {
            f'{API}/stat/device': _Counters(),
            f'{API}/stat/sta': legacy(CLIENTS),
            f'{API}/rest/wlanconf': legacy(WLANS),
        }
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', FAKE_SSH_PW)


@pytest.fixture
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waited: list[float] = []

    async def _no_wait(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr(ap_health, '_pause', _no_wait)
    return waited


@pytest.fixture
def ssh(monkeypatch: pytest.MonkeyPatch) -> FakeSSH:
    fake = FakeSSH()
    monkeypatch.setattr(asyncssh, 'connect', fake)
    return fake


async def _run(controller: FakeController, **kwargs: Any) -> tuple[dict[str, Any], Any]:
    capture = ApHealthCapture()
    async with serving(controller):
        report = await run_ap_health_capture(sink=capture, **kwargs)
    return report, capture


async def test_the_capture_samples_both_aps_through_reads_only(
    pauses: list[float], ssh: FakeSSH
) -> None:
    controller = _controller()
    report, capture = await _run(
        controller, target='AP 1', reference='AP 2', samples=3, interval=30
    )
    assert pauses == [30, 30]
    assert report['samples_taken'] == {'target': 3, 'reference': 3}
    assert report['essid'] == 'SSID A' and report['essid_source'] == 'busiest'
    assert [s.role for s in capture.samples] == ['target', 'reference'] * 3
    target = [r for r in report['rows'] if r['role'] == 'target']
    assert [r['retry_pct'] for r in target] == [None, 10.0, 10.0]
    assert report['ssid_config'] == dict.fromkeys(ap_health.SSID_CONFIG_KEYS) | {
        'wpa_mode': 'wpa2'
    }
    assert controller.methods == {'GET'} and ssh.connects == []
    text = json.dumps(report)
    assert FAKE_PSK not in text and 'FAKE-AP-AUTHKEY' not in text


async def test_a_sample_read_that_times_out_is_missing_not_fatal(
    pauses: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ap_health._read_sample
    calls = {'n': 0}

    async def _stall_second(ping_clients: bool) -> Any:
        calls['n'] += 1
        if calls['n'] == 2:
            await asyncio.sleep(5)
        return await real(ping_clients)

    monkeypatch.setattr(ap_health, 'SAMPLE_READ_TIMEOUT', 0.1)
    monkeypatch.setattr(ap_health, '_read_sample', _stall_second)
    report, capture = await _run(_controller(), target='AP 1', samples=3, interval=30)
    assert [s.missing for s in capture.samples] == [False, True, False]
    assert report['samples_taken'] == {'target': 2} and report['samples_missing'] == {'target': 1}


@pytest.mark.parametrize(
    'kwargs',
    [{'samples': 0}, {'samples': 61}, {'interval': 29}, {'interval': 601}],
    ids=['samples 0', 'samples 61', 'interval 29', 'interval 601'],
)
async def test_out_of_range_bounds_are_refused_before_any_read(kwargs: dict[str, int]) -> None:
    controller = _controller()
    with pytest.raises(ToolError) as caught:
        await _run(controller, target='AP 1', **kwargs)
    assert caught.value.error_code == ErrorCodes.CONFIG_INVALID
    assert controller.calls == []


@pytest.mark.parametrize('target', ['No such AP', 'Switch A'], ids=['unknown', 'not an AP'])
async def test_a_target_that_is_not_an_ap_is_not_found(target: str, pauses: list[float]) -> None:
    with pytest.raises(ToolError) as caught:
        await _run(_controller(), target=target, samples=1, interval=30)
    assert caught.value.error_code == ErrorCodes.DEVICE_NOT_FOUND


async def test_the_reference_must_be_another_ap(pauses: list[float]) -> None:
    with pytest.raises(ToolError) as caught:
        await _run(_controller(), target='AP 1', reference=AP_MAC, samples=1, interval=30)
    assert caught.value.error_code == ErrorCodes.CONFIG_INVALID


async def test_client_pings_run_in_one_gateway_session(pauses: list[float], ssh: FakeSSH) -> None:
    report, capture = await _run(
        _controller(), target='AP 1', samples=2, interval=30, ping_clients=True
    )
    assert len(ssh.connects) == 1
    argv = [shlex.split(command) for command in ssh.commands]
    assert argv == [['ping', '-c', '10', '-i', '0.3', '-W', '2', '192.0.2.31']] * 2
    assert capture.samples[0].pings['192.0.2.31']['loss_pct'] == 0.0
    assert report['ping_clients'] is True


# --- the CLI ------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH) -> FakeController:
    controller = _controller()
    route_cli(monkeypatch, controller)
    return controller


def test_the_command_prints_json_and_the_expected_duration(
    cli: FakeController, pauses: list[float], ssh: FakeSSH
) -> None:
    args = ['diagnose', 'ap-health', 'AP 1', '--samples', '2', '--interval', '30', '--json']
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data['partial'] is False and data['samples_taken'] == {'target': 2}
    assert 'Expected duration: about 1 min' in result.stderr
    assert 'host key' not in result.stderr and ssh.connects == []  # no SSH without pings


def test_ping_clients_routes_through_ssh_and_prints_the_notice_once(
    cli: FakeController, pauses: list[float], ssh: FakeSSH
) -> None:
    args = ['diagnose', 'ap-health', 'AP 1', '--samples', '1', '--interval', '30']
    result = runner.invoke(app, [*args, '--ping-clients'])
    assert result.exit_code == 0, result.output
    assert result.stderr.count('host key') == 1 and len(ssh.connects) == 1
    assert '# AP Health Report — AP 1' in result.stdout


@pytest.mark.parametrize(
    'interrupt', [asyncio.CancelledError, KeyboardInterrupt], ids=['cancelled', 'ctrl-c']
)
def test_an_interrupt_prints_and_writes_a_partial_report_and_exits_130(
    cli: FakeController,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interrupt: type[BaseException],
) -> None:
    calls: list[float] = []

    async def _interrupt_after_two(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) == 2:  # the pause before the third sample
            raise interrupt

    monkeypatch.setattr(ap_health, '_pause', _interrupt_after_two)
    output = tmp_path / 'out' / 'ap-health.md'
    args = ['diagnose', 'ap-health', 'AP 1', '--samples', '5', '--interval', '30']
    result = runner.invoke(app, [*args, '--output', str(output), '--json'])
    assert result.exit_code == 130, result.output
    data = json.loads(result.stdout)
    assert data['partial'] is True and data['samples_taken'] == {'target': 2}
    assert 'Partial' in output.read_text(encoding='utf-8')


@pytest.mark.parametrize(
    'args',
    [['--samples', '0'], ['--samples', '61'], ['--interval', '29'], ['--interval', '601']],
)
def test_out_of_range_options_are_usage_errors(cli: FakeController, args: list[str]) -> None:
    result = runner.invoke(app, ['diagnose', 'ap-health', 'AP 1', *args])
    assert result.exit_code == 2, result.output
    assert cli.calls == []


def test_the_command_has_help() -> None:
    result = runner.invoke(app, ['diagnose', 'ap-health', '--help'])
    assert result.exit_code == 0
    flat = ' '.join(result.output.split())
    assert 'Read-only' in flat and 'no power-cycle' in flat and 'exits 130' in flat
