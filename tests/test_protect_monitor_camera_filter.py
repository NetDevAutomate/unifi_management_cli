"""Issue 046 item 4: the Protect monitor's camera filter comes from configuration, not source.

The monitor tracked only the cameras whose host carried one hard-coded subnet prefix (the
maintainer's camera VLAN), or that were third-party. Now it tracks every camera unless
``PROTECT_CAMERA_HOSTS`` (or ``--camera-host``) names the host prefixes to keep; third-party
cameras are kept either way, as before. Nothing here opens a connection.
"""

from __future__ import annotations

import pytest
from unifi_mapper.monitors import protect_monitor
from unifi_mapper.monitors.protect_monitor import ProtectMonitor, camera_hosts_from_env


pytestmark = pytest.mark.usefixtures('block_network')


_PLACEHOLDER = 'unused'  # not a credential: nothing here connects


def _monitor(**kwargs) -> ProtectMonitor:
    return ProtectMonitor(
        base_url='https://203.0.113.1', username='viewer', password=_PLACEHOLDER, **kwargs
    )


def test_every_camera_is_tracked_when_no_hosts_are_configured() -> None:
    monitor = _monitor()
    assert monitor.tracks_camera({'host': '198.51.100.21'})
    assert monitor.tracks_camera({'host': '192.0.2.9'})
    assert monitor.tracks_camera({})  # a camera with no host yet


def test_configured_host_prefixes_narrow_the_set() -> None:
    monitor = _monitor(camera_hosts=('198.51.100.',))
    assert monitor.tracks_camera({'host': '198.51.100.21'})
    assert not monitor.tracks_camera({'host': '192.0.2.9'})
    assert not monitor.tracks_camera({})


def test_third_party_cameras_are_kept_whatever_the_prefixes() -> None:
    monitor = _monitor(camera_hosts=('198.51.100.',))
    assert monitor.tracks_camera({'host': '192.0.2.9', 'isThirdPartyCamera': True})


def test_camera_hosts_from_env_splits_and_trims(monkeypatch) -> None:
    monkeypatch.setenv('PROTECT_CAMERA_HOSTS', ' 198.51.100., 203.0.113.4 ,,')
    assert camera_hosts_from_env() == ('198.51.100.', '203.0.113.4')
    monkeypatch.delenv('PROTECT_CAMERA_HOSTS')
    assert camera_hosts_from_env() == ()


def test_cli_passes_camera_hosts_to_the_monitor(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeMonitor:
        def __init__(self, **kwargs) -> None:
            seen.update(kwargs)

        def run(self, show_full: bool = True) -> None:
            seen['ran'] = show_full

    monkeypatch.setattr(protect_monitor, 'ProtectMonitor', FakeMonitor)
    monkeypatch.setenv('PROTECT_HOST', '203.0.113.1')
    monkeypatch.setenv('PROTECT_USERNAME', 'viewer')
    monkeypatch.setenv('PROTECT_PASSWORD', 'unused')
    monkeypatch.setenv('PROTECT_CAMERA_HOSTS', '198.51.100.')
    monkeypatch.setattr(
        'sys.argv',
        ['protect_monitor', '--camera-host', '203.0.113.', '--camera-host', '192.0.2.5', '-q'],
    )
    protect_monitor.main()
    # The command line wins over the environment, as the credentials do.
    assert seen['camera_hosts'] == ('203.0.113.', '192.0.2.5')
    assert seen['ran'] is False


def test_cli_falls_back_to_the_environment_for_camera_hosts(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeMonitor:
        def __init__(self, **kwargs) -> None:
            seen.update(kwargs)

        def run(self, show_full: bool = True) -> None:
            pass

    monkeypatch.setattr(protect_monitor, 'ProtectMonitor', FakeMonitor)
    monkeypatch.setenv('PROTECT_HOST', '203.0.113.1')
    monkeypatch.setenv('PROTECT_USERNAME', 'viewer')
    monkeypatch.setenv('PROTECT_PASSWORD', 'unused')
    monkeypatch.setenv('PROTECT_CAMERA_HOSTS', '198.51.100.')
    monkeypatch.setattr('sys.argv', ['protect_monitor'])
    protect_monitor.main()
    assert seen['camera_hosts'] == ('198.51.100.',)
