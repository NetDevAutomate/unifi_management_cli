"""The ONVIF scripts read their cameras and account from the environment (issue 041).

``scripts/onvif_probe.py`` and ``scripts/onvif_stream.py`` used to hard-code the site's
cameras and a camera password. Both now read ``ONVIF_USERNAME``, ``ONVIF_PASSWORD`` and
``ONVIF_CAMERAS`` through ``scripts/onvif_config.py``, and must stop before connecting to a
camera when one is unset.

Nothing here touches a camera: ``onvif`` is replaced by a stub whose ``ONVIFCamera`` fails
the test if anything constructs it, ``block_network`` fails any socket connect, and the
user's environment is never read (every variable is unset or set with ``monkeypatch``).
``scripts/`` is not an importable package, so the modules are loaded by path.
"""

from __future__ import annotations

import asyncio
import pytest
import sys
import types
from tests.script_modules import SCRIPTS, load_script
from typing import Any


VARIABLES = ('ONVIF_USERNAME', 'ONVIF_PASSWORD', 'ONVIF_CAMERAS')
FAKE_PASSWORD = 'not-a-camera-password'  # pragma: allowlist secret

pytestmark = pytest.mark.usefixtures('block_network')


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``scripts/onvif_config.py``, with every ONVIF variable unset."""
    for var in VARIABLES:
        monkeypatch.delenv(var, raising=False)
    return load_script('onvif_config', monkeypatch)


@pytest.fixture
def cameras_built(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Replace the ``onvif`` package with a stub that fails on any connection attempt."""
    built: list[tuple[object, ...]] = []

    class _NoCamera:
        """Stands in for ``ONVIFCamera``: records each construction, then fails."""

        def __init__(self, *args: object, **_kwargs: object) -> None:
            """Record the camera's arguments and fail the test."""
            built.append(args)
            raise AssertionError('an ONVIF connection in a unit test')

    stub: Any = types.ModuleType('onvif')  # Any: ModuleType declares no ONVIFCamera attribute
    stub.__file__ = str(SCRIPTS / 'onvif' / '__init__.py')  # the scripts derive WSDL_DIR from it
    stub.ONVIFCamera = _NoCamera
    monkeypatch.setitem(sys.modules, 'onvif', stub)
    return built


def _env(**overrides: str) -> dict[str, str]:
    """Return a complete set of ONVIF variables with dummy values, updated by ``overrides``."""
    env = {
        'ONVIF_USERNAME': 'onvifuser',
        'ONVIF_PASSWORD': FAKE_PASSWORD,
        'ONVIF_CAMERAS': 'Camera A=192.0.2.10, Camera B=192.0.2.11:8080',
    }
    env.update(overrides)
    return env


def test_load_cameras_reads_each_camera_and_the_shared_account(config: Any) -> None:
    """Each NAME=HOST[:PORT] entry becomes a camera (port 80 by default) with the account."""
    cameras = config.load_cameras(_env())

    assert [(c.name, c.ip, c.port, c.user) for c in cameras] == [
        ('Camera A', '192.0.2.10', 80, 'onvifuser'),
        ('Camera B', '192.0.2.11', 8080, 'onvifuser'),
    ]
    assert {c.password for c in cameras} == {FAKE_PASSWORD}


def test_load_cameras_reads_os_environ_by_default(
    config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no mapping given, the loader reads ``os.environ``."""
    for var, value in _env(ONVIF_CAMERAS='Camera A=camera-a.example').items():
        monkeypatch.setenv(var, value)

    [camera] = config.load_cameras()

    assert (camera.name, camera.ip, camera.port) == ('Camera A', 'camera-a.example', 80)


@pytest.mark.parametrize(
    ('unset', 'named'),
    [
        (VARIABLES, 'ONVIF_USERNAME, ONVIF_PASSWORD, ONVIF_CAMERAS'),
        (('ONVIF_PASSWORD',), 'ONVIF_PASSWORD'),
        (('ONVIF_USERNAME', 'ONVIF_CAMERAS'), 'ONVIF_USERNAME, ONVIF_CAMERAS'),
    ],
)
def test_load_cameras_names_every_missing_variable(
    config: Any, unset: tuple[str, ...], named: str
) -> None:
    """The error names every unset variable, in a fixed order, and says how to set them."""
    env = {var: value for var, value in _env().items() if var not in unset}

    with pytest.raises(config.ConfigError, match=f'^not set: {named}\\. Set ONVIF_USERNAME'):
        config.load_cameras(env)


@pytest.mark.parametrize('value', ['', '   '])
def test_an_empty_variable_counts_as_unset(config: Any, value: str) -> None:
    """An empty or blank value is reported as unset."""
    with pytest.raises(config.ConfigError, match='^not set: ONVIF_USERNAME\\.'):
        config.load_cameras(_env(ONVIF_USERNAME=value))


@pytest.mark.parametrize(
    'cameras',
    [
        ',',
        'Camera A',
        '=192.0.2.10',
        'Camera A=',
        'Camera A=:8080',
        'Camera A=192.0.2.10:http',
        'Camera A=192.0.2.10:',
        'Camera A=192.0.2.10:8\N{SUPERSCRIPT TWO}',
        'Camera A=192.0.2.10:0',
        'Camera A=192.0.2.10:65536',
        'Camera A=192.0.2.10, Camera B',
    ],
)
def test_load_cameras_rejects_a_malformed_camera_list(config: Any, cameras: str) -> None:
    """A malformed camera list is a ConfigError that names the variable, never the password."""
    with pytest.raises(config.ConfigError, match='ONVIF_CAMERAS') as excinfo:
        config.load_cameras(_env(ONVIF_CAMERAS=cameras))

    assert FAKE_PASSWORD not in str(excinfo.value)


@pytest.mark.parametrize(
    'camera',
    ['Camera B=192.0.2.11:80:90', 'Camera B=2001:db8::11', 'Camera B=[2001:db8::11]:8080'],
)
def test_an_address_with_more_than_one_colon_is_rejected(config: Any, camera: str) -> None:
    """A second ``:`` (a typo, or an IPv6 literal, which isn't supported) fails at load time.

    Such an entry used to become a bare host on port 80 and fail only when the script tried
    to connect. The message gives the entry's position, not its address.
    """
    with pytest.raises(config.ConfigError, match='entry 2 has more than one ":"') as excinfo:
        config.load_cameras(_env(ONVIF_CAMERAS=f'Camera A=192.0.2.10, {camera}'))

    assert camera.partition('=')[2] not in str(excinfo.value)
    assert FAKE_PASSWORD not in str(excinfo.value)


def test_the_password_stays_out_of_the_repr(config: Any) -> None:
    """A camera's repr never shows its password."""
    [camera, _] = config.load_cameras(_env())

    assert FAKE_PASSWORD not in repr(camera)


@pytest.mark.parametrize('command', ['info', 'streams', 'snapshot', 'test-rtsp'])
def test_stream_script_stops_before_connecting_when_unset(
    config: Any,
    cameras_built: list[tuple[object, ...]],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Every stream command stops with the missing variables before building a camera."""
    stream = load_script('onvif_stream', monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['onvif_stream.py', command])

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(stream.main())

    message = str(excinfo.value.code)
    assert message.startswith('onvif_stream.py: not set: ONVIF_USERNAME, ONVIF_PASSWORD')
    assert cameras_built == []


def test_stream_script_reports_usage_without_reading_the_environment(
    config: Any,
    cameras_built: list[tuple[object, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown command prints the usage and exits 1 without reading the environment."""
    stream = load_script('onvif_stream', monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['onvif_stream.py', 'no-such-command'])

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(stream.main())

    assert excinfo.value.code == 1
    assert 'Unknown command: no-such-command' in capsys.readouterr().out
    assert cameras_built == []


def test_probe_script_stops_before_connecting_when_unset(
    config: Any, cameras_built: list[tuple[object, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe stops with the missing variables before building a camera."""
    probe = load_script('onvif_probe', monkeypatch)
    monkeypatch.setenv('ONVIF_USERNAME', 'onvifuser')

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(probe.main())

    message = str(excinfo.value.code)
    assert message.startswith('onvif_probe.py: not set: ONVIF_PASSWORD, ONVIF_CAMERAS')
    assert cameras_built == []


def test_rtsp_check_reports_each_failing_camera_and_moves_on(
    config: Any,
    cameras_built: list[tuple[object, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``test-rtsp`` prints a failure for a camera it can't reach, then tries the next one.

    The camera stub fails on construction, before ffprobe runs, which is the path that used to
    stop the whole run with an UnboundLocalError.
    """
    stream = load_script('onvif_stream', monkeypatch)
    for var, value in _env().items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(sys, 'argv', ['onvif_stream.py', 'test-rtsp'])

    asyncio.run(stream.main())

    out = capsys.readouterr().out
    assert out.count('❌ Failed') == 2
    assert len(cameras_built) == 2
    assert FAKE_PASSWORD not in out
