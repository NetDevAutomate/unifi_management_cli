#!/usr/bin/env python3
"""ONVIF camera stream testing script.

Usage:
    uv run python scripts/onvif_stream.py info          # Show camera info
    uv run python scripts/onvif_stream.py streams       # List all stream URIs
    uv run python scripts/onvif_stream.py snapshot      # Capture snapshots
    uv run python scripts/onvif_stream.py test-rtsp     # Test RTSP connectivity
"""

import asyncio
import os
import sys
from dataclasses import dataclass

import onvif
from onvif import ONVIFCamera

WSDL_DIR = os.path.join(os.path.dirname(onvif.__file__), "wsdl")


@dataclass
class CameraConfig:
    name: str
    ip: str
    port: int
    user: str
    password: str


# Camera configurations
CAMERAS = [
    CameraConfig("Intercom", "192.168.10.11", 80, "onvif", "ge0rge3rd"),
    CameraConfig("Front_Of_House", "192.168.10.12", 80, "onvif", "ge0rge3rd"),
]


async def get_camera(config: CameraConfig) -> ONVIFCamera:
    """Connect to camera and return ONVIFCamera instance."""
    camera = ONVIFCamera(
        config.ip, config.port, config.user, config.password, wsdl_dir=WSDL_DIR
    )
    await camera.update_xaddrs()

    # Fix XAddrs if camera returns 127.0.0.1 (common with AXIS cameras)
    for service_name, xaddr in camera.xaddrs.items():
        if "127.0.0.1" in xaddr or "localhost" in xaddr:
            fixed_xaddr = xaddr.replace("127.0.0.1", config.ip)
            fixed_xaddr = fixed_xaddr.replace("localhost", config.ip)
            camera.xaddrs[service_name] = fixed_xaddr

    return camera


async def show_info(config: CameraConfig):
    """Show camera information."""
    print(f"\n{'='*60}")
    print(f"📷 {config.name} ({config.ip})")
    print("=" * 60)

    try:
        camera = await get_camera(config)
        devicemgmt = await camera.create_devicemgmt_service()
        info = await devicemgmt.GetDeviceInformation()

        print(f"  Manufacturer: {info.Manufacturer}")
        print(f"  Model: {info.Model}")
        print(f"  Firmware: {info.FirmwareVersion}")
        print(f"  Serial: {info.SerialNumber}")
        print("  Status: ✅ Connected")

        await camera.close()
    except Exception as e:
        print(f"  Status: ❌ Failed - {e}")


async def list_streams(config: CameraConfig):
    """List all available stream URIs."""
    print(f"\n{'='*60}")
    print(f"🎬 {config.name} ({config.ip}) - Stream URIs")
    print("=" * 60)

    try:
        camera = await get_camera(config)
        media = await camera.create_media_service()
        profiles = await media.GetProfiles()

        for profile in profiles:
            res = profile.VideoEncoderConfiguration.Resolution
            enc = profile.VideoEncoderConfiguration.Encoding
            print(f"\n  Profile: {profile.Name}")
            print(f"  Resolution: {res.Width}x{res.Height}")
            print(f"  Encoding: {enc}")

            # Get stream URI - use keyword arguments for newer onvif-zeep-async
            stream_setup = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
            uri_response = await media.GetStreamUri(
                {"StreamSetup": stream_setup, "ProfileToken": profile.token}
            )

            # Fix 127.0.0.1 in RTSP URI and build authenticated version
            rtsp_uri = uri_response.Uri.replace("127.0.0.1", config.ip)
            auth_uri = rtsp_uri.replace(
                "rtsp://", f"rtsp://{config.user}:{config.password}@"
            )
            print(f"  URI: {rtsp_uri}")
            print(f"  Auth URI: {auth_uri}")

        await camera.close()
    except Exception as e:
        print(f"  ❌ Failed: {e}")


async def capture_snapshot(config: CameraConfig, output_dir: str = "/tmp"):
    """Capture a snapshot from the camera."""
    print(f"\n📸 Capturing snapshot from {config.name}...")

    try:
        camera = await get_camera(config)
        media = await camera.create_media_service()
        profiles = await media.GetProfiles()

        if not profiles:
            print("  ❌ No profiles available")
            return

        # Use first profile
        profile = profiles[0]
        snapshot_uri = await media.GetSnapshotUri(profile.token)

        # Fix 127.0.0.1 in snapshot URI
        fixed_snapshot_uri = snapshot_uri.Uri.replace("127.0.0.1", config.ip)
        print(f"  Snapshot URI: {fixed_snapshot_uri}")

        # Download snapshot using httpx
        import httpx
        from httpx import DigestAuth

        auth = DigestAuth(config.user, config.password)
        async with httpx.AsyncClient(auth=auth, timeout=10.0) as client:
            response = await client.get(fixed_snapshot_uri)
            if response.status_code == 200:
                filename = f"{output_dir}/{config.name.lower()}_snapshot.jpg"
                with open(filename, "wb") as f:
                    f.write(response.content)
                print(f"  ✅ Saved to: {filename}")
            else:
                print(f"  ❌ HTTP {response.status_code}")

        await camera.close()
    except Exception as e:
        print(f"  ❌ Failed: {e}")


async def test_rtsp(config: CameraConfig):
    """Test RTSP stream connectivity."""
    print(f"\n🔗 Testing RTSP for {config.name}...")

    try:
        camera = await get_camera(config)
        media = await camera.create_media_service()
        profiles = await media.GetProfiles()

        if not profiles:
            print("  ❌ No profiles")
            return

        profile = profiles[0]
        stream_setup = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
        uri_response = await media.GetStreamUri(
            {"StreamSetup": stream_setup, "ProfileToken": profile.token}
        )

        # Fix 127.0.0.1 and add auth credentials
        fixed_uri = uri_response.Uri.replace("127.0.0.1", config.ip)
        rtsp_uri = fixed_uri.replace(
            "rtsp://", f"rtsp://{config.user}:{config.password}@"
        )

        print(f"  Stream URI: {rtsp_uri}")

        # Test with ffprobe if available
        import subprocess

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_name",
                "-of",
                "csv=p=0",
                "-rtsp_transport",
                "tcp",
                "-i",
                rtsp_uri,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 3:
                print(f"  ✅ Stream OK: {parts[2]} {parts[0]}x{parts[1]}")
            else:
                print(f"  ✅ Stream OK: {result.stdout.strip()}")
        else:
            print(f"  ⚠️  ffprobe failed: {result.stderr[:100] if result.stderr else 'no output'}")

        await camera.close()
    except FileNotFoundError:
        print("  ⚠️  ffprobe not found - install ffmpeg for RTSP testing")
    except subprocess.TimeoutExpired:
        print("  ❌ RTSP connection timeout")
    except Exception as e:
        print(f"  ❌ Failed: {e}")


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "info":
        for cam in CAMERAS:
            await show_info(cam)

    elif command == "streams":
        for cam in CAMERAS:
            await list_streams(cam)

    elif command == "snapshot":
        for cam in CAMERAS:
            await capture_snapshot(cam)

    elif command == "test-rtsp":
        for cam in CAMERAS:
            await test_rtsp(cam)

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
