#!/usr/bin/env python3
"""Probe ONVIF cameras with onvif-zeep-async: device info, capabilities and stream URIs.

A live-camera probe, not a pytest test: it connects to every camera in ``ONVIF_CAMERAS``
with the ``ONVIF_USERNAME`` and ``ONVIF_PASSWORD`` account (see ``onvif_config.py``), and
stops before connecting to any camera if one of them is unset::

    uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_probe.py
"""

import asyncio
import onvif
import os
import sys
from onvif import ONVIFCamera
from onvif_config import ConfigError, load_cameras


# WSDL files are bundled with the onvif package
WSDL_DIR = os.path.join(os.path.dirname(onvif.__file__), 'wsdl')


async def probe_camera(ip: str, port: int, user: str, password: str) -> bool:
    """Probe an ONVIF connection and print the camera's info.

    Args:
        ip: The camera's address.
        port: The camera's ONVIF port.
        user: The ONVIF user name.
        password: The ONVIF user's password.

    Returns:
        True if the camera answered every probe, False if any step failed.
    """
    print(f'\n{"=" * 60}')
    print(f'Testing ONVIF: {ip}:{port} as {user}')
    print('=' * 60)

    try:
        # Connect to camera with WSDL directory
        camera = ONVIFCamera(ip, port, user, password, wsdl_dir=WSDL_DIR)
        await camera.update_xaddrs()

        # Get device info
        devicemgmt = camera.create_devicemgmt_service()
        info = await devicemgmt.GetDeviceInformation()

        print('\n✅ Connection successful!')
        print(f'   Manufacturer: {info.Manufacturer}')
        print(f'   Model: {info.Model}')
        print(f'   Firmware: {info.FirmwareVersion}')
        print(f'   Serial: {info.SerialNumber}')

        # Get capabilities
        caps = await devicemgmt.GetCapabilities()
        print('\n📋 Capabilities:')
        print(f'   Media: {bool(caps.Media)}')
        print(f'   PTZ: {bool(caps.PTZ) if hasattr(caps, "PTZ") else False}')
        print(f'   Events: {bool(caps.Events) if hasattr(caps, "Events") else False}')

        # Get media profiles
        media = camera.create_media_service()
        profiles = await media.GetProfiles()

        print(f'\n🎬 Media Profiles ({len(profiles)}):')
        for p in profiles:
            print(
                f'   - {p.Name}: {p.VideoEncoderConfiguration.Resolution.Width}x{p.VideoEncoderConfiguration.Resolution.Height}'
            )

            # Get stream URI
            stream_setup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
            uri = await media.GetStreamUri(stream_setup, p.token)
            print(f'     Stream: {uri.Uri}')

        await camera.close()
        return True

    except Exception as e:
        print(f'\n❌ Failed: {e}')
        return False


async def main() -> None:
    """Probe every camera in ``ONVIF_CAMERAS``."""
    try:
        cameras = load_cameras()
    except ConfigError as e:
        sys.exit(f'onvif_probe.py: {e}')

    results = {}
    for cam in cameras:
        print(f'\n{"#" * 60}')
        print(f'# {cam.name}')
        print('#' * 60)
        results[cam.name] = await probe_camera(cam.ip, cam.port, cam.user, cam.password)

    print(f'\n{"=" * 60}')
    print('SUMMARY')
    print('=' * 60)
    for name, success in results.items():
        status = '✅ OK' if success else '❌ FAILED'
        print(f'  {name}: {status}')


if __name__ == '__main__':
    asyncio.run(main())
