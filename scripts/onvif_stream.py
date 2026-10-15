#!/usr/bin/env python3
"""ONVIF camera stream testing script.

Usage:
    uv run python scripts/onvif_stream.py info          # Show camera info
    uv run python scripts/onvif_stream.py streams       # List all stream URIs
    uv run python scripts/onvif_stream.py snapshot      # Capture snapshots
    uv run python scripts/onvif_stream.py test-rtsp     # RTSP DESCRIBE: auth + SDP metadata

Each command runs against every camera in ONVIF_CAMERAS (NAME=HOST[:PORT],...) with the
ONVIF_USERNAME and ONVIF_PASSWORD account. Keep them in a file outside the repository and
pass it with "uv run --env-file FILE python scripts/onvif_stream.py ...". The script stops
before connecting to any camera if one of them is unset.

test-rtsp sends one RTSP DESCRIBE to each camera's first stream, in this process, with Digest
authentication (Basic only when the camera offers nothing else). It proves that the camera
accepts the account and returns the stream's SDP metadata (codecs, dimensions). It does not
pull video, so it does not prove the stream plays. No external program is started and the
password is never on a command line.

The output never shows ONVIF_PASSWORD: stream URIs are printed as rtsp://USER:***@HOST/...,
and error text is masked the same way.
"""

import asyncio
import base64
import contextlib
import hashlib
import onvif
import os
import re
import secrets
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from onvif import ONVIFCamera
from onvif_config import CameraConfig, ConfigError, load_cameras
from urllib.parse import urlsplit


WSDL_DIR = os.path.join(os.path.dirname(onvif.__file__), 'wsdl')
MASK = '***'

RTSP_PORT = 554
RTSP_TIMEOUT = 10.0
Opener = Callable[[str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]
# How the probe opens its TCP connection; a test points this at a fake camera.
OPEN_CONNECTION: Opener = asyncio.open_connection


class RtspError(Exception):
    """The DESCRIBE probe failed; the message never holds the password."""


@dataclass
class DescribeResult:
    """What one RTSP DESCRIBE proved: the status, the scheme that was accepted, the SDP."""

    status: int
    auth: str  # 'none', 'digest' or 'basic': the scheme the camera accepted
    sdp: str

    def media(self) -> list[str]:
        """The SDP's media lines as ``'<kind> <codec>[ <w>x<h>]'``, in order."""
        out: list[str] = []
        kind = ''
        codec = ''
        size = ''
        for line in self.sdp.splitlines():
            if line.startswith('m='):
                if kind:
                    out.append(' '.join(filter(None, (kind, codec, size))))
                kind, codec, size = line[2:].split(' ', 1)[0], '', ''
            elif line.startswith('a=rtpmap:'):
                codec = codec or line.split(' ', 1)[1].split('/', 1)[0]
            elif line.startswith('a=x-dimensions:') or line.startswith('a=framesize:'):
                found = re.findall(r'\d+', line.split(':', 1)[1])
                if len(found) >= 2:
                    size = f'{found[-2]}x{found[-1]}'
        if kind:
            out.append(' '.join(filter(None, (kind, codec, size))))
        return out


def _redact(text: object, config: CameraConfig) -> str:
    """Return ``text`` as a string with the camera's password replaced by ``MASK``.

    Every string this script prints that could hold the password (a stream URI, an RTSP
    error, an exception message) goes through here first.

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
        The authenticated URI, for the ``streams`` listing. Print it only through ``_redact``;
        nothing in this script passes it to another program.
    """
    return uri.replace('rtsp://', f'rtsp://{config.user}:{config.password}@')


def _parse_auth_params(params: str) -> dict[str, str]:
    """Parse the ``k=v, k="v"`` parameters of a WWW-Authenticate challenge."""
    return {
        key: quoted or bare
        for key, quoted, bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', params)
    }


def _digest_authorization(
    challenge: str, user: str, password: str, *, method: str, uri: str
) -> str | None:
    """Build the ``Authorization: Digest`` value for ``challenge`` (RFC 2617/7616).

    MD5 and SHA-256 (the camera chooses, in ``algorithm``), with ``qop="auth"`` when offered.
    Only hashes of the password leave this function.

    Returns:
        The header value, or None when the challenge uses an algorithm this probe lacks.
    """
    fields = _parse_auth_params(challenge)
    realm, nonce = fields.get('realm', ''), fields.get('nonce', '')
    if not nonce:
        return None
    algorithm = fields.get('algorithm', 'MD5').upper()
    if algorithm.startswith('SHA-256'):
        digest = hashlib.sha256
    elif algorithm.startswith('MD5'):
        digest = hashlib.md5  # the camera's choice (RFC 2617 Digest), not ours
    else:
        return None

    def h(text: str) -> str:
        return digest(text.encode(), usedforsecurity=False).hexdigest()

    cnonce = secrets.token_hex(8)
    ha1 = h(f'{user}:{realm}:{password}')
    if algorithm.endswith('-SESS'):
        ha1 = h(f'{ha1}:{nonce}:{cnonce}')
    ha2 = h(f'{method}:{uri}')
    qop = 'auth' if 'auth' in {q.strip() for q in fields.get('qop', '').split(',')} else ''
    parts = [
        f'username="{user}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f'algorithm={fields.get("algorithm", "MD5")}',
    ]
    if qop:
        response = h(f'{ha1}:{nonce}:00000001:{cnonce}:{qop}:{ha2}')
        parts += [f'qop={qop}', 'nc=00000001', f'cnonce="{cnonce}"']
    else:
        response = h(f'{ha1}:{nonce}:{ha2}')
        if algorithm.endswith('-SESS'):
            parts.append(f'cnonce="{cnonce}"')  # it entered HA1, so the camera needs it
    parts.append(f'response="{response}"')
    if fields.get('opaque'):
        parts.append(f'opaque="{fields["opaque"]}"')
    return 'Digest ' + ', '.join(parts)


def _authorization(
    challenges: list[str], user: str, password: str, *, method: str, uri: str
) -> tuple[str, str] | None:
    """Pick the strongest scheme the camera offered and build its Authorization value.

    Returns:
        ``(scheme, header value)`` with scheme ``'digest'`` or ``'basic'``, or None when the
        camera offered neither.
    """
    digest_offered: list[str] = []
    for challenge in challenges:
        scheme, _, params = challenge.strip().partition(' ')
        if scheme.lower() == 'digest':
            value = _digest_authorization(params, user, password, method=method, uri=uri)
            if value:
                return 'digest', value
            digest_offered.append(_parse_auth_params(params).get('algorithm', 'MD5'))
    if digest_offered:
        # Basic would send the password base64-encoded; it is used only when the camera offers
        # nothing else, never as a downgrade from a Digest challenge this probe cannot answer.
        raise RtspError(
            'the camera offered Digest with an algorithm this probe does not speak ('
            + ', '.join(digest_offered)
            + '); Basic is not tried in its place'
        )
    for challenge in challenges:
        if challenge.strip().lower().startswith('basic'):
            token = base64.b64encode(f'{user}:{password}'.encode()).decode()
            return 'basic', f'Basic {token}'
    return None


async def _rtsp_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    method: str,
    uri: str,
    cseq: int,
    authorization: str | None = None,
) -> tuple[int, list[tuple[str, str]], str]:
    """Send one RTSP request and read its response.

    Returns:
        ``(status, headers, body)``; headers as ``(lower-case name, value)`` pairs.
    """
    lines = [f'{method} {uri} RTSP/1.0', f'CSeq: {cseq}', 'User-Agent: onvif_stream.py']
    lines.append('Accept: application/sdp')
    if authorization:
        lines.append(f'Authorization: {authorization}')
    writer.write(('\r\n'.join(lines) + '\r\n\r\n').encode())
    await writer.drain()
    try:
        head = await reader.readuntil(b'\r\n\r\n')
    except asyncio.IncompleteReadError as e:
        raise RtspError('the camera closed the connection without an RTSP response') from e
    status_line, *header_lines = head.decode('latin-1').split('\r\n')
    try:
        status = int(status_line.split(' ', 2)[1])
    except (IndexError, ValueError) as e:
        raise RtspError(f'not an RTSP response: {status_line[:60]!r}') from e
    headers = [
        (name.strip().lower(), value.strip())
        for name, _, value in (line.partition(':') for line in header_lines if line)
    ]
    length = next((int(v) for n, v in headers if n == 'content-length' and v.isdigit()), 0)
    body = (await reader.readexactly(length)).decode('utf-8', 'replace') if length else ''
    return status, headers, body


async def rtsp_describe(
    uri: str,
    user: str,
    password: str,
    *,
    timeout: float = RTSP_TIMEOUT,
    open_connection: Opener | None = None,
) -> DescribeResult:
    """Send an authenticated RTSP DESCRIBE for ``uri`` and return the camera's SDP.

    The request goes out bare; on a 401 the camera's challenge is answered once, with Digest
    when offered (only hashes of the password leave this process) or Basic when that is all
    the camera speaks. A second 401 is an authentication failure, not a retry. The whole
    exchange is bounded by ``timeout`` seconds.

    Args:
        uri: The stream URI the camera reported (no credentials in it).
        user: The ONVIF account.
        password: Its password; it appears in no exception message and on no command line.
        timeout: Seconds for the whole exchange, connection included.
        open_connection: How to open the TCP connection; defaults to ``OPEN_CONNECTION``.

    Returns:
        The status (200), the accepted scheme and the SDP body.

    Raises:
        RtspError: a malformed URI, no connection, a timeout, an unanswerable challenge, a
            401 after authentication, or any other non-200 status.
    """
    parts = urlsplit(uri)
    host, port = parts.hostname, parts.port or RTSP_PORT
    if parts.scheme != 'rtsp' or not host:
        raise RtspError(f'not an rtsp:// URI: {_strip_userinfo(uri)}')
    target = f'rtsp://{host}:{port}{parts.path or "/"}' + (
        f'?{parts.query}' if parts.query else ''
    )
    opener = open_connection or OPEN_CONNECTION

    async def exchange() -> DescribeResult:
        try:
            reader, writer = await opener(host, port)
        except OSError as e:
            raise RtspError(f'cannot connect to {host}:{port}: {e.strerror or e}') from e
        try:
            status, headers, body = await _rtsp_request(
                reader, writer, method='DESCRIBE', uri=target, cseq=1
            )
            scheme = 'none'
            if status == 401:
                challenges = [v for n, v in headers if n == 'www-authenticate']
                picked = _authorization(challenges, user, password, method='DESCRIBE', uri=target)
                if picked is None:
                    raise RtspError(
                        'the camera offered no authentication scheme this probe speaks: '
                        + (', '.join(c.split(' ', 1)[0] for c in challenges) or 'none')
                    )
                scheme, header = picked
                status, headers, body = await _rtsp_request(
                    reader, writer, method='DESCRIBE', uri=target, cseq=2, authorization=header
                )
            if status == 401:
                raise RtspError(
                    f'authentication rejected (401 after {scheme.title()}): check '
                    "ONVIF_USERNAME and ONVIF_PASSWORD against the camera's RTSP account"
                )
            if status != 200:
                raise RtspError(f'DESCRIBE {_strip_userinfo(target)} returned RTSP {status}')
            return DescribeResult(status=status, auth=scheme, sdp=body)
        finally:
            # Cleanup must never block: when ``wait_for`` cancels this coroutine mid-read, an
            # unbounded ``await writer.wait_closed()`` here could itself hang on a silent peer
            # and swallow the cancellation, so the deadline would never fire.
            writer.close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 0.5)

    try:
        return await asyncio.wait_for(exchange(), timeout)
    except asyncio.TimeoutError as e:
        raise RtspError(f'timed out after {timeout:g}s waiting for {host}:{port}') from e


_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')


def _describe_outcome(result: DescribeResult, config: CameraConfig) -> str:
    """One line saying exactly what the DESCRIBE proved (council pass B, findings M2 and M4).

    Authentication is "accepted" only when the camera challenged and then answered 200; a camera
    that answers without asking proves nothing about the account. Metadata is claimed only for a
    body that is SDP (``v=0`` and at least one ``m=`` line). Camera-supplied text is masked and
    stripped of control characters before it is printed.
    """
    if result.auth == 'none':
        auth = 'authentication not assessed: the camera answered without asking for credentials'
        mark = '⚠️'
    else:
        auth = f'authentication accepted ({result.auth.title()})'
        mark = '✅'
    media = result.media() if result.sdp.lstrip().startswith('v=0') else []
    if media:
        shown = _CONTROL_CHARS.sub('', _redact(', '.join(media), config))
        what = f'SDP returned: {shown}. Metadata only: this does not pull video.'
    else:
        what = 'no SDP metadata in the answer.'
        mark = '⚠️'
    return f'{mark} DESCRIBE answered: {auth}; {what}'


def _strip_userinfo(uri: str) -> str:
    """Return ``uri`` without any ``user:password@`` part, for messages."""
    return re.sub(r'://[^/@]*@', '://', uri)


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
    """RTSP DESCRIBE probe of each camera's first stream (the ``test-rtsp`` command).

    Sends one authenticated DESCRIBE in this process (``rtsp_describe``) and prints what it
    proved: the camera accepted the ONVIF account (Digest, or Basic when that is all it
    offers) and returned the stream's SDP metadata, listed as codec and dimensions. It does
    not pull video, so a line marked OK means "authentication accepted and metadata
    returned", not that the stream plays. No other program is started and the password is on
    no command line; the printed URI is the bare one the camera reported, and error text has
    the password masked. A camera that fails is reported, and the caller moves on to the next.
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

        # Fix 127.0.0.1; the probe gets the bare URI and the account separately.
        rtsp_uri = uri_response.Uri.replace('127.0.0.1', config.ip)
        print(f'  Stream URI: {_redact(rtsp_uri, config)}')

        try:
            result = await rtsp_describe(rtsp_uri, config.user, config.password)
        except RtspError as e:
            print(f'  ❌ DESCRIBE failed: {_redact(e, config)}')
        else:
            print(f'  {_describe_outcome(result, config)}')

        await camera.close()
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
