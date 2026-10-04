#!/usr/bin/env python3
"""ONVIF camera stream testing script.

Usage:
    uv run python scripts/onvif_stream.py info          # Show camera info
    uv run python scripts/onvif_stream.py streams       # List all stream URIs
    uv run python scripts/onvif_stream.py snapshot      # Capture snapshots
    uv run python scripts/onvif_stream.py test-rtsp     # Test RTSP connectivity

Each command runs against every camera in ONVIF_CAMERAS (NAME=HOST[:PORT],...) with the
ONVIF_USERNAME and ONVIF_PASSWORD account. Keep them in a file outside the repository and
pass it with "uv run --env-file FILE python scripts/onvif_stream.py ...". The script stops
before connecting to any camera if one of them is unset.

The output never shows ONVIF_PASSWORD: stream URIs are printed as rtsp://USER:***@HOST/...,
and error text is masked the same way.
"""

import asyncio
import onvif
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from onvif import ONVIFCamera
from onvif_config import CameraConfig, ConfigError, load_cameras


WSDL_DIR = os.path.join(os.path.dirname(onvif.__file__), 'wsdl')
MASK = '***'


def _redact(text: object, config: CameraConfig) -> str:
    """Return ``text`` as a string with the camera's password replaced by ``MASK``.

    Every string this script prints that could hold the password (a stream URI, ffprobe's
    error output, an exception message) goes through here first.

    Args:
        text: The value to print; it is converted with ``str``.
        config: The camera whose password must not appear.

    Returns:
        The text, with every occurrence of the password masked.
    """
    value = str(text)
    if config.password:
        value = value.replace(config.password, MASK)
    return value


def _with_credentials(uri: str, config: CameraConfig) -> str:
    """Return ``uri`` with the camera's ONVIF account added after ``rtsp://``.

    Args:
        uri: The stream URI the camera reported.
        config: The camera whose user and password to add.

    Returns:
        The authenticated URI. Pass it to ffprobe; print it only through ``_redact``.
    """
    return uri.replace('rtsp://', f'rtsp://{config.user}:{config.password}@')


async def get_camera(config: CameraConfig) -> ONVIFCamera:
    """Connect to camera and return ONVIFCamera instance."""
    camera = ONVIFCamera(config.ip, config.port, config.user, config.password, wsdl_dir=WSDL_DIR)
    await camera.update_xaddrs()

    # Fix XAddrs if camera returns 127.0.0.1 (common with AXIS cameras)
    for service_name, xaddr in camera.xaddrs.items():
        if '127.0.0.1' in xaddr or 'localhost' in xaddr:
            fixed_xaddr = xaddr.replace('127.0.0.1', config.ip)
            fixed_xaddr = fixed_xaddr.replace('localhost', config.ip)
            camera.xaddrs[service_name] = fixed_xaddr

    return camera


async def show_info(config: CameraConfig) -> None:
    """Show camera information."""
    print(f'\n{"=" * 60}')
    print(f'📷 {config.name} ({config.ip})')
    print('=' * 60)

    try:
        camera = await get_camera(config)
        devicemgmt = await camera.create_devicemgmt_service()
        info = await devicemgmt.GetDeviceInformation()

        print(f'  Manufacturer: {info.Manufacturer}')
        print(f'  Model: {info.Model}')
        print(f'  Firmware: {info.FirmwareVersion}')
        print(f'  Serial: {info.SerialNumber}')
        print('  Status: ✅ Connected')

        await camera.close()
    except Exception as e:
        print(f'  Status: ❌ Failed - {_redact(e, config)}')


async def list_streams(config: CameraConfig) -> None:
    """List all available stream URIs (the ``streams`` command).

    Each profile's URI is printed bare and with the ONVIF account added, the password masked.
    """
    print(f'\n{"=" * 60}')
    print(f'🎬 {config.name} ({config.ip}) - Stream URIs')
    print('=' * 60)

    try:
        camera = await get_camera(config)
        media = await camera.create_media_service()
        profiles = await media.GetProfiles()

        for profile in profiles:
            res = profile.VideoEncoderConfiguration.Resolution
            enc = profile.VideoEncoderConfiguration.Encoding
            print(f'\n  Profile: {profile.Name}')
            print(f'  Resolution: {res.Width}x{res.Height}')
            print(f'  Encoding: {enc}')

            # Get stream URI - use keyword arguments for newer onvif-zeep-async
            stream_setup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
            uri_response = await media.GetStreamUri(
                {'StreamSetup': stream_setup, 'ProfileToken': profile.token}
            )

            # Fix 127.0.0.1 in RTSP URI; show the authenticated form with the password masked
            rtsp_uri = uri_response.Uri.replace('127.0.0.1', config.ip)
            print(f'  URI: {_redact(rtsp_uri, config)}')
            print(f'  Auth URI: {_redact(_with_credentials(rtsp_uri, config), config)}')

        await camera.close()
    except Exception as e:
        print(f'  ❌ Failed: {_redact(e, config)}')


async def capture_snapshot(config: CameraConfig, output_dir: str = '/tmp') -> None:
    """Capture a snapshot from the camera."""
    print(f'\n📸 Capturing snapshot from {config.name}...')

    try:
        camera = await get_camera(config)
        media = await camera.create_media_service()
        profiles = await media.GetProfiles()

        if not profiles:
            print('  ❌ No profiles available')
            return

        # Use first profile
        profile = profiles[0]
        snapshot_uri = await media.GetSnapshotUri(profile.token)

        # Fix 127.0.0.1 in snapshot URI
        fixed_snapshot_uri = snapshot_uri.Uri.replace('127.0.0.1', config.ip)
        print(f'  Snapshot URI: {_redact(fixed_snapshot_uri, config)}')

        # Download snapshot using httpx
        import httpx
        from httpx import DigestAuth

        auth = DigestAuth(config.user, config.password)
        async with httpx.AsyncClient(auth=auth, timeout=10.0) as client:
            response = await client.get(fixed_snapshot_uri)
            if response.status_code == 200:
                filename = f'{output_dir}/{config.name.lower()}_snapshot.jpg'
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f'  ✅ Saved to: {filename}')
            else:
                print(f'  ❌ HTTP {response.status_code}')

        await camera.close()
    except Exception as e:
        print(f'  ❌ Failed: {_redact(e, config)}')


async def check_rtsp(config: CameraConfig) -> None:
    """Test RTSP stream connectivity (the ``test-rtsp`` command).

    A camera that fails, before or during the ffprobe run, is reported, and the caller moves
    on to the next one. ffprobe gets the full authenticated URI; the printed URI and any error
    text have the password masked.
    """
    print(f'\n🔗 Testing RTSP for {config.name}...')

    try:
        camera = await get_camera(config)
        media = await camera.create_media_service()
        profiles = await media.GetProfiles()

        if not profiles:
            print('  ❌ No profiles')
            return

        profile = profiles[0]
        stream_setup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
        uri_response = await media.GetStreamUri(
            {'StreamSetup': stream_setup, 'ProfileToken': profile.token}
        )

        # Fix 127.0.0.1 and add auth credentials (ffprobe gets them; the output masks them)
        fixed_uri = uri_response.Uri.replace('127.0.0.1', config.ip)
        rtsp_uri = _with_credentials(fixed_uri, config)

        print(f'  Stream URI: {_redact(rtsp_uri, config)}')

        # Test with ffprobe if available
        result = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=width,height,codec_name',
                '-of',
                'csv=p=0',
                '-rtsp_transport',
                'tcp',
                '-i',
                rtsp_uri,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(',')
            if len(parts) >= 3:
                print(f'  ✅ Stream OK: {parts[2]} {parts[0]}x{parts[1]}')
            else:
                print(f'  ✅ Stream OK: {_redact(result.stdout.strip(), config)}')
        else:
            # Mask before truncating, so a cut can't leave part of the password showing.
            detail = _redact(result.stderr, config)[:100] if result.stderr else 'no output'
            print(f'  ⚠️  ffprobe failed: {detail}')

        await camera.close()
    except FileNotFoundError:
        print('  ⚠️  ffprobe not found - install ffmpeg for RTSP testing')
    except subprocess.TimeoutExpired:
        print('  ❌ RTSP connection timeout')
    except Exception as e:
        print(f'  ❌ Failed: {_redact(e, config)}')


COMMANDS: dict[str, Callable[[CameraConfig], Awaitable[None]]] = {
    'info': show_info,
    'streams': list_streams,
    'snapshot': capture_snapshot,
    'test-rtsp': check_rtsp,
}


async def main() -> None:
    """Run the ONVIF stream test CLI."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    action = COMMANDS.get(command)
    if action is None:
        print(f'Unknown command: {command}')
        print(__doc__)
        sys.exit(1)

    try:
        cameras = load_cameras()
    except ConfigError as e:
        sys.exit(f'onvif_stream.py: {e}')

    for cam in cameras:
        await action(cam)


if __name__ == '__main__':
    asyncio.run(main())
