#!/usr/bin/env python3
"""
Enhanced UniFi Protect Monitor - Full Debug & AI Analytics

Monitors AI Ports, cameras, smart detection, and stream health in real-time.
Provides comprehensive visibility into:
- AI Port pairing status and camera connections
- Smart detection events (person, vehicle, animal, face, license plate)
- Audio detection (smoke, CO, siren, baby cry, glass break, etc.)
- Stream health and RTSP routing (direct vs AI Port)
- Recording status and video quality
- Real-time change detection with alerts

Usage:
    # As a module
    from unifi_mapper.monitors import ProtectMonitor
    monitor = ProtectMonitor(base_url, username, password)
    monitor.run()

    # As CLI (from project root)
    python -m unifi_mapper.monitors.protect_monitor --help
"""
import argparse
import logging
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

warnings.filterwarnings("ignore")

log = logging.getLogger(__name__)


class ProtectMonitor:
    """
    Real-time monitor for UniFi Protect devices with AI analytics.

    Provides comprehensive monitoring of:
    - AI Ports: pairing status, smart detection capabilities, camera capacity
    - Cameras: connection state, recording status, stream routing
    - Events: smart detection, motion, audio events
    - Changes: real-time alerts when device state changes

    Example:
        monitor = ProtectMonitor(
            base_url="https://192.168.1.1",
            username="admin",
            password="secret"
        )
        monitor.run(poll_interval=3)
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        poll_interval: int = 3,
        log_file: Optional[str] = None,
    ):
        """
        Initialize the Protect Monitor.

        Args:
            base_url: UniFi controller URL (e.g., https://192.168.1.1)
            username: Protect admin username
            password: Protect admin password
            poll_interval: Seconds between API polls (default: 3)
            log_file: Optional path to write logs
        """
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.poll_interval = poll_interval
        self.log_file = log_file
        self.session: Optional[requests.Session] = None
        self.previous_state: Optional[Dict[str, Any]] = None
        self.is_authenticated = False

    def log(self, message: str) -> None:
        """Log to console and optionally to file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line)
        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(line + "\n")

    def login(self) -> bool:
        """
        Login to Protect API.

        Note: Protect API requires `remember: True` and `strict: True` flags
        for successful authentication, unlike the Network API.

        Returns:
            True if login successful, False otherwise
        """
        self.session = requests.Session()
        self.session.verify = False

        try:
            resp = self.session.post(
                f"{self.base_url}/api/auth/login",
                json={
                    "username": self.username,
                    "password": self.password,
                    "remember": True,  # Required for Protect API
                    "strict": True,  # Required for Protect API
                },
                timeout=10,
            )

            if resp.status_code == 200:
                self.is_authenticated = True
                self.log("✅ Connected to Protect API")
                return True
            else:
                self.log(f"❌ Login failed: {resp.status_code}")
                return False
        except Exception as e:
            self.log(f"❌ Login error: {e}")
            return False

    def get_bootstrap(self) -> Optional[Dict[str, Any]]:
        """Get full bootstrap data from Protect API."""
        if not self.session:
            return None

        try:
            resp = self.session.get(
                f"{self.base_url}/proxy/protect/api/bootstrap", timeout=15
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            log.error(f"Failed to get bootstrap: {e}")
        return None

    def get_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent events (smart detections, motion, etc.).

        Args:
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries
        """
        if not self.session:
            return []

        try:
            end = int(time.time() * 1000)
            start = end - (60 * 60 * 1000)  # 1 hour ago
            resp = self.session.get(
                f"{self.base_url}/proxy/protect/api/events",
                params={"start": start, "end": end, "limit": limit},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            self.log(f"⚠️ Failed to get events: {e}")
        return []

    @staticmethod
    def format_timestamp(ts: Optional[int]) -> str:
        """Format millisecond timestamp to HH:MM:SS."""
        if ts:
            return datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
        return "Never"

    @staticmethod
    def format_uptime(seconds: Optional[int]) -> str:
        """Format seconds as human readable duration."""
        if not seconds:
            return "N/A"
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        mins = (seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h {mins}m"
        elif hours > 0:
            return f"{hours}h {mins}m"
        else:
            return f"{mins}m"

    def extract_ai_port_state(self, ap: Dict[str, Any]) -> Dict[str, Any]:
        """Extract comprehensive AI Port state for monitoring."""
        ff = ap.get("featureFlags", {})
        stats = ap.get("stats", {})
        sd_settings = ap.get("smartDetectSettings", {})

        return {
            # Identity
            "name": ap.get("name"),
            "ip": ap.get("host"),
            "mac": ap.get("mac"),
            "firmware": ap.get("firmwareVersion"),
            # Connection
            "state": ap.get("state"),
            "connectedSince": ap.get("connectedSince"),
            "lastSeen": ap.get("lastSeen"),
            "uptime": ap.get("uptime"),
            "connectionHost": ap.get("connectionHost"),
            # Recording
            "isRecording": ap.get("isRecording"),
            "hasRecordings": ap.get("hasRecordings"),
            # Camera Pairing
            "pairedCameras": ap.get("pairedCameras", []),
            "cameraId": ap.get("cameraId"),
            "rtspClient": ap.get("rtspClient"),
            "cameraCapacity": ap.get("cameraCapacity", {}),
            "cameraUtilization": ap.get("cameraUtilization"),
            "maxCameraCapacity": ap.get("maxCameraCapacity"),
            # AI/Smart Detection
            "smartDetectTypes": sd_settings.get("objectTypes", []),
            "smartDetectAudioTypes": sd_settings.get("audioTypes", []),
            "isSmartDetected": ap.get("isSmartDetected"),
            "isMotionDetected": ap.get("isMotionDetected"),
            "smartDetectZones": len(ap.get("smartDetectZones", [])),
            "motionZones": len(ap.get("motionZones", [])),
            # Capabilities
            "supportedSmartTypes": ff.get("smartDetectTypes", []),
            "supportedAudioTypes": ff.get("smartDetectAudioTypes", []),
            "hasSmartDetect": ff.get("hasSmartDetect"),
            "hasLineCrossing": ff.get("hasLineCrossing"),
            "hasLiveviewTracking": ff.get("hasLiveviewTracking"),
            # Channels/Quality
            "channels": [
                {
                    "name": c.get("name"),
                    "width": c.get("width"),
                    "height": c.get("height"),
                    "fps": c.get("fps"),
                    "bitrate": c.get("bitrate"),
                }
                for c in ap.get("channels", [])
            ],
            "currentResolution": ap.get("currentResolution"),
            "videoCodec": ap.get("videoCodec"),
            # Storage
            "sdCardState": stats.get("sdCard", {}).get("state"),
            "sdCardHealth": stats.get("sdCard", {}).get("healthStatus"),
        }

    def extract_camera_state(self, cam: Dict[str, Any]) -> Dict[str, Any]:
        """Extract comprehensive camera state for monitoring."""
        tpc = cam.get("thirdPartyCameraInfo", {})
        stats = cam.get("stats", {})
        sd_settings = cam.get("smartDetectSettings", {})
        lenses = cam.get("lenses", [])

        # Get recording times from lenses
        rec_start = None
        rec_end = None
        if lenses:
            lens_video = lenses[0].get("video", {})
            rec_start = lens_video.get("recordingStart")
            rec_end = lens_video.get("recordingEnd")

        return {
            # Identity
            "name": cam.get("name"),
            "ip": cam.get("host"),
            "mac": cam.get("mac"),
            "type": cam.get("type"),
            "isThirdParty": cam.get("isThirdPartyCamera"),
            # Connection
            "state": cam.get("state"),
            "lastSeen": cam.get("lastSeen"),
            "connectedSince": cam.get("connectedSince"),
            # Recording
            "isRecording": cam.get("isRecording"),
            "hasRecordings": cam.get("hasRecordings"),
            "recordingStart": rec_start,
            "recordingEnd": rec_end,
            # AI Port Pairing
            "isPairedWithAiPort": cam.get("isPairedWithAiPort"),
            "aiportId": cam.get("aiportId"),
            # Stream Info
            "rtspUrl": tpc.get("rtspUrl"),
            "rtspUrlLQ": tpc.get("rtspUrlLQ"),
            "rtspClient": cam.get("rtspClient"),
            "snapshotUrl": tpc.get("snapshotUrl"),
            "hasAudio": tpc.get("hasAudio"),
            "errors": tpc.get("errors", []),
            "connectionState": tpc.get("connectionState"),
            # AI/Smart Detection
            "smartDetectTypes": sd_settings.get("objectTypes", []),
            "isSmartDetected": cam.get("isSmartDetected"),
            "isMotionDetected": cam.get("isMotionDetected"),
            "smartDetectZones": len(cam.get("smartDetectZones", [])),
            "motionZones": len(cam.get("motionZones", [])),
            # Video Quality
            "currentResolution": cam.get("currentResolution"),
            "videoCodec": cam.get("videoCodec"),
            "channels": [
                {
                    "name": c.get("name"),
                    "width": c.get("width"),
                    "height": c.get("height"),
                    "fps": c.get("fps"),
                    "enabled": c.get("enabled"),
                }
                for c in cam.get("channels", [])[:3]
            ],
            # Capacity
            "aiPortCapacityPoints": cam.get("aiPortCapacityPoints"),
        }

    def print_ai_port_details(self, ap_state: Dict[str, Any]) -> None:
        """Print detailed AI Port status to console."""
        print(f"\n{'─' * 60}")
        print(f"🔌 AI PORT: {ap_state['name']} ({ap_state['ip']})")
        print(f"{'─' * 60}")

        # Connection Status
        state_icon = "🟢" if ap_state["state"] == "CONNECTED" else "🔴"
        rec_icon = "🔴 REC" if ap_state["isRecording"] else "⚪ IDLE"
        print(f"  Status: {state_icon} {ap_state['state']} | {rec_icon}")
        print(
            f"  Uptime: {self.format_uptime(ap_state['uptime'])} | "
            f"Last Seen: {self.format_timestamp(ap_state['lastSeen'])}"
        )
        print(
            f"  Firmware: {ap_state['firmware']} | "
            f"Connection Host: {ap_state['connectionHost']}"
        )

        # Camera Pairing
        print(f"\n  📷 Camera Pairing:")
        print(
            f"     Paired Cameras: {len(ap_state['pairedCameras'])} / "
            f"{ap_state['maxCameraCapacity']}"
        )
        print(f"     Camera IDs: {ap_state['pairedCameras'] or 'None'}")
        print(f"     Active Camera ID: {ap_state['cameraId'] or 'None'}")
        print(f"     RTSP Client: {ap_state['rtspClient'] or 'None'}")
        print(
            f"     Utilization: {ap_state['cameraUtilization']} | "
            f"Capacity: {ap_state['cameraCapacity']}"
        )

        # AI Detection
        motion_icon = "🏃" if ap_state["isMotionDetected"] else "  "
        smart_icon = "🤖" if ap_state["isSmartDetected"] else "  "
        print(f"\n  🤖 AI Detection: {motion_icon}{smart_icon}")
        print(f"     Active Types: {ap_state['smartDetectTypes'] or 'None configured'}")
        print(f"     Audio Types: {ap_state['smartDetectAudioTypes'] or 'None'}")
        print(
            f"     Smart Zones: {ap_state['smartDetectZones']} | "
            f"Motion Zones: {ap_state['motionZones']}"
        )

        # Capabilities
        print(f"\n  ⚙️ Capabilities:")
        print(f"     Supported: {', '.join(ap_state['supportedSmartTypes'])}")
        if ap_state["supportedAudioTypes"]:
            print(f"     Audio: {', '.join(ap_state['supportedAudioTypes'][:5])}...")
        print(
            f"     Features: SmartDetect={ap_state['hasSmartDetect']} "
            f"LineCross={ap_state['hasLineCrossing']} "
            f"Tracking={ap_state['hasLiveviewTracking']}"
        )

        # Video Channels
        print(
            f"\n  📺 Video: {ap_state['currentResolution']} / {ap_state['videoCodec']}"
        )
        for ch in ap_state["channels"]:
            bitrate_mbps = ch["bitrate"] / 1_000_000 if ch["bitrate"] else 0
            print(
                f"     {ch['name']}: {ch['width']}x{ch['height']} @ "
                f"{ch['fps']}fps ({bitrate_mbps:.1f} Mbps)"
            )

        # Storage
        print(
            f"\n  💾 SD Card: {ap_state['sdCardState']} ({ap_state['sdCardHealth']})"
        )

    def print_camera_details(self, cam_state: Dict[str, Any]) -> None:
        """Print detailed camera status to console."""
        print(f"\n{'─' * 60}")
        print(f"📷 CAMERA: {cam_state['name']} ({cam_state['ip']})")
        print(f"{'─' * 60}")

        # Connection Status
        state_icon = "🟢" if cam_state["state"] == "CONNECTED" else "🔴"
        rec_icon = "🔴 REC" if cam_state["isRecording"] else "⚪ IDLE"
        print(f"  Status: {state_icon} {cam_state['state']} | {rec_icon}")
        print(f"  Type: {cam_state['type']} | Third-Party: {cam_state['isThirdParty']}")
        print(f"  Last Seen: {self.format_timestamp(cam_state['lastSeen'])}")

        # Recording
        if cam_state["recordingStart"] or cam_state["recordingEnd"]:
            print(f"\n  🎬 Recording:")
            print(f"     Start: {self.format_timestamp(cam_state['recordingStart'])}")
            print(f"     End: {self.format_timestamp(cam_state['recordingEnd'])}")

        # AI Port Pairing
        paired_icon = "✅" if cam_state["aiportId"] else "❌"
        print(f"\n  🔗 AI Port Pairing:")
        print(f"     isPairedWithAiPort: {cam_state['isPairedWithAiPort']}")
        print(f"     aiportId: {cam_state['aiportId'] or 'NOT SET'} {paired_icon}")
        print(f"     AI Capacity Points: {cam_state['aiPortCapacityPoints']}")

        # Stream Info
        print(f"\n  📡 Stream:")
        print(f"     RTSP Client: {cam_state['rtspClient'] or 'None'}")
        if cam_state["rtspUrl"]:
            url = cam_state["rtspUrl"]
            if "127.0.0.1" in url:
                print(f"     RTSP URL: 🏠 DIRECT (127.0.0.1) - Stream to UDMPM")
            else:
                print(f"     RTSP URL: 🔌 VIA AI PORT - {url[:60]}...")
        print(f"     Has Audio: {cam_state['hasAudio']}")
        if cam_state["errors"]:
            print(f"     ⚠️ ERRORS: {cam_state['errors']}")

        # AI Detection
        motion_icon = "🏃" if cam_state["isMotionDetected"] else "  "
        smart_icon = "🤖" if cam_state["isSmartDetected"] else "  "
        print(f"\n  🤖 AI Detection: {motion_icon}{smart_icon}")
        print(f"     Active Types: {cam_state['smartDetectTypes'] or 'None'}")
        print(
            f"     Smart Zones: {cam_state['smartDetectZones']} | "
            f"Motion Zones: {cam_state['motionZones']}"
        )

        # Video Quality
        print(
            f"\n  📺 Video: {cam_state['currentResolution']} / {cam_state['videoCodec']}"
        )
        for ch in cam_state["channels"]:
            if ch.get("enabled"):
                print(
                    f"     {ch['name']}: {ch['width']}x{ch['height']} @ {ch['fps']}fps"
                )

    def print_events(self, events: List[Dict[str, Any]]) -> None:
        """Print recent events to console."""
        if not events:
            return

        print(f"\n{'═' * 60}")
        print(f"📋 RECENT EVENTS (last hour)")
        print(f"{'═' * 60}")

        for event in events[:10]:
            event_type = event.get("type", "unknown")
            start = self.format_timestamp(event.get("start"))
            smart_types = event.get("smartDetectTypes", [])

            if event_type == "smartDetectZone":
                types_str = ", ".join(smart_types) if smart_types else "motion"
                print(f"  {start} | 🤖 Smart Detect: {types_str}")
            elif event_type == "motion":
                print(f"  {start} | 🏃 Motion detected")
            else:
                print(f"  {start} | {event_type}")

    def detect_changes(
        self, old_state: Optional[Dict[str, Any]], new_state: Dict[str, Any]
    ) -> List[str]:
        """Detect and report changes between states."""
        changes = []

        if not old_state:
            return changes

        # Compare AI Ports
        for ap_id in new_state.get("aiports", {}):
            old_ap = old_state.get("aiports", {}).get(ap_id, {})
            new_ap = new_state["aiports"][ap_id]

            for key in [
                "state",
                "isRecording",
                "isSmartDetected",
                "isMotionDetected",
                "pairedCameras",
                "cameraId",
                "rtspClient",
            ]:
                if old_ap.get(key) != new_ap.get(key):
                    changes.append(
                        f"🔌 AI Port [{new_ap['name']}] {key}: "
                        f"{old_ap.get(key)} → {new_ap.get(key)}"
                    )

        # Compare Cameras
        for cam_id in new_state.get("cameras", {}):
            old_cam = old_state.get("cameras", {}).get(cam_id, {})
            new_cam = new_state["cameras"][cam_id]

            for key in [
                "state",
                "isRecording",
                "isSmartDetected",
                "isMotionDetected",
                "isPairedWithAiPort",
                "aiportId",
                "errors",
            ]:
                if old_cam.get(key) != new_cam.get(key):
                    changes.append(
                        f"📷 Camera [{new_cam['name']}] {key}: "
                        f"{old_cam.get(key)} → {new_cam.get(key)}"
                    )

        return changes

    def run(self, show_full: bool = True) -> None:
        """
        Main monitoring loop.

        Args:
            show_full: Show full status on changes (default: True)
                      Set to False for quiet mode (only changes)
        """
        if not self.login():
            return

        print(f"\n{'═' * 60}")
        print("🔍 UNIFI PROTECT ENHANCED MONITOR")
        print(f"{'═' * 60}")
        print(f"Poll interval: {self.poll_interval}s")
        if self.log_file:
            print(f"Logging to: {self.log_file}")
        print("Press Ctrl+C to stop\n")

        poll_count = 0

        try:
            while True:
                bootstrap = self.get_bootstrap()
                if not bootstrap:
                    self.log("⚠️ Failed to get bootstrap data")
                    time.sleep(self.poll_interval)
                    continue

                # Extract current state
                current_state: Dict[str, Any] = {"aiports": {}, "cameras": {}}

                for ap in bootstrap.get("aiports", []):
                    ap_state = self.extract_ai_port_state(ap)
                    current_state["aiports"][ap.get("id")] = ap_state

                for cam in bootstrap.get("cameras", []):
                    # Only track VLAN 10 / third-party cameras
                    if "192.168.10" in str(cam.get("host", "")) or cam.get(
                        "isThirdPartyCamera"
                    ):
                        cam_state = self.extract_camera_state(cam)
                        current_state["cameras"][cam.get("id")] = cam_state

                # Detect changes
                changes = self.detect_changes(self.previous_state, current_state)

                # Show full status on first run or if changes detected
                if poll_count == 0 or (changes and show_full):
                    for ap_state in current_state["aiports"].values():
                        self.print_ai_port_details(ap_state)

                    for cam_state in current_state["cameras"].values():
                        self.print_camera_details(cam_state)

                    # Get events on first run
                    if poll_count == 0:
                        events = self.get_events()
                        self.print_events(events)

                # Report changes
                if changes:
                    print(f"\n{'!' * 60}")
                    print(f"🔔 CHANGES DETECTED at {datetime.now().strftime('%H:%M:%S')}")
                    print(f"{'!' * 60}")
                    for change in changes:
                        print(f"  {change}")
                        self.log(change)

                self.previous_state = current_state
                poll_count += 1

                # Periodic status
                if poll_count % 20 == 0:
                    self.log(f"... monitoring (poll #{poll_count})")

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            print("\n\n✋ Monitoring stopped")
            self.log("Monitoring stopped by user")


def main():
    """CLI entry point for the Protect Monitor."""
    parser = argparse.ArgumentParser(
        description="Enhanced UniFi Protect Monitor with AI Analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic monitoring (3 second interval)
  python -m unifi_mapper.monitors.protect_monitor

  # Fast polling (1 second)
  python -m unifi_mapper.monitors.protect_monitor -i 1

  # Log to file
  python -m unifi_mapper.monitors.protect_monitor -l /tmp/protect.log

  # Quiet mode (only show changes)
  python -m unifi_mapper.monitors.protect_monitor -q

  # Custom credentials
  python -m unifi_mapper.monitors.protect_monitor \\
    --url https://192.168.1.1 \\
    --user admin \\
    --password secret
        """,
    )
    parser.add_argument(
        "-u",
        "--url",
        type=str,
        default="https://192.168.125.254",
        help="UniFi controller URL (default: https://192.168.125.254)",
    )
    parser.add_argument(
        "--user",
        type=str,
        default="Protect_Admin",
        help="Protect username (default: Protect_Admin)",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="rjn3tpt4DFE9tje-fcg",
        help="Protect password",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=3,
        help="Poll interval in seconds (default: 3)",
    )
    parser.add_argument("-l", "--log", type=str, help="Log file path")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only show changes, not full status",
    )
    args = parser.parse_args()

    monitor = ProtectMonitor(
        base_url=args.url,
        username=args.user,
        password=args.password,
        poll_interval=args.interval,
        log_file=args.log,
    )
    monitor.run(show_full=not args.quiet)


if __name__ == "__main__":
    main()
