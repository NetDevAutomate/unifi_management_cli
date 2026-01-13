#!/usr/bin/env python3
"""Simple ONVIF camera test script using onvif-zeep-async."""

import asyncio
import os
import onvif
from onvif import ONVIFCamera

# WSDL files are bundled with the onvif package
WSDL_DIR = os.path.join(os.path.dirname(onvif.__file__), "wsdl")


async def test_camera(ip: str, port: int, user: str, password: str):
    """Test ONVIF connection and get camera info."""
    print(f"\n{'='*60}")
    print(f"Testing ONVIF: {ip}:{port} as {user}")
    print('='*60)

    try:
        # Connect to camera with WSDL directory
        camera = ONVIFCamera(ip, port, user, password, wsdl_dir=WSDL_DIR)
        await camera.update_xaddrs()

        # Get device info
        devicemgmt = camera.create_devicemgmt_service()
        info = await devicemgmt.GetDeviceInformation()

        print(f"\n✅ Connection successful!")
        print(f"   Manufacturer: {info.Manufacturer}")
        print(f"   Model: {info.Model}")
        print(f"   Firmware: {info.FirmwareVersion}")
        print(f"   Serial: {info.SerialNumber}")

        # Get capabilities
        caps = await devicemgmt.GetCapabilities()
        print(f"\n📋 Capabilities:")
        print(f"   Media: {bool(caps.Media)}")
        print(f"   PTZ: {bool(caps.PTZ) if hasattr(caps, 'PTZ') else False}")
        print(f"   Events: {bool(caps.Events) if hasattr(caps, 'Events') else False}")

        # Get media profiles
        media = camera.create_media_service()
        profiles = await media.GetProfiles()

        print(f"\n🎬 Media Profiles ({len(profiles)}):")
        for p in profiles:
            print(f"   - {p.Name}: {p.VideoEncoderConfiguration.Resolution.Width}x{p.VideoEncoderConfiguration.Resolution.Height}")

            # Get stream URI
            stream_setup = {
                'Stream': 'RTP-Unicast',
                'Transport': {'Protocol': 'RTSP'}
            }
            uri = await media.GetStreamUri(stream_setup, p.token)
            print(f"     Stream: {uri.Uri}")

        await camera.close()
        return True

    except Exception as e:
        print(f"\n❌ Failed: {e}")
        return False


async def main():
    """Test both cameras."""
    cameras = [
        ("192.168.10.11", 80, "onvifuser", "onvifpassword", "Intercom"),
        ("192.168.10.12", 80, "onvifuser", "onvifpassword", "Front_Of_House"),
    ]

    results = {}
    for ip, port, user, password, name in cameras:
        print(f"\n{'#'*60}")
        print(f"# {name}")
        print('#'*60)
        results[name] = await test_camera(ip, port, user, password)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    for name, success in results.items():
        status = "✅ OK" if success else "❌ FAILED"
        print(f"  {name}: {status}")


if __name__ == "__main__":
    asyncio.run(main())
