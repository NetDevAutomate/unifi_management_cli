"""``onvif_stream.py test-rtsp`` probes RTSP in-process; the password never reaches argv (057).

``check_rtsp`` used to hand ffprobe the authenticated URI on its command line, readable by
every local user in ``ps`` for the probe's lifetime. It now sends an RTSP ``DESCRIBE`` itself
with Digest (or Basic, when that is all the camera offers) authentication, standard library
only. What it proves is exactly what it prints: the camera accepted the account and returned
SDP metadata. It does not pull video.

The fake camera here is an asyncio RTSP server on a Unix socket (the test suite refuses TCP
connects, loopback included); the probe takes the connection opener as a parameter, so the
protocol bytes are real and the server records every byte it received.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import pytest
import re
import shutil
import subprocess
import sys
import tempfile
import types
from collections.abc import Iterator
from pathlib import Path
from tests.script_modules import load_script
from typing import Any


USER = 'onvifuser'
FAKE_PASSWORD = 'zq9x-not-a-camera-password-k4'  # pragma: allowlist secret
WRONG_PASSWORD = 'something-else'  # pragma: allowlist secret
REALM = 'AXIS_FAKE0001'
NONCE = '0000d7d5Yfake'
STREAM_PATH = '/axis-media/media.amp'
SDP = (
    'v=0\r\n'
    'o=- 1 1 IN IP4 192.0.2.10\r\n'
    's=Session streamed with GStreamer\r\n'
    'm=video 0 RTP/AVP 96\r\n'
    'a=rtpmap:96 H264/90000\r\n'
    'a=x-dimensions:1920,1080\r\n'
    'm=audio 0 RTP/AVP 97\r\n'
    'a=rtpmap:97 MPEG4-GENERIC/16000/1\r\n'
)


def _h(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


class FakeRtspCamera:
    """An RTSP server that answers DESCRIBE after Digest (or Basic) authentication."""

    def __init__(
        self, path: Path, *, password: str, schemes: tuple[str, ...] = ('Digest',), qop: bool
    ) -> None:
        self.path = path
        self.password = password
        self.schemes = schemes
        self.qop = qop
        self.received: list[bytes] = []
        self.requests: list[dict[str, str]] = []
        self._server: asyncio.AbstractServer | None = None

    async def __aenter__(self) -> FakeRtspCamera:
        self._server = await asyncio.start_unix_server(self._serve, path=str(self.path))
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def open(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """The opener the probe is given: ignores host/port, connects to the Unix socket."""
        self.requests.append({'host': host, 'port': str(port)})
        return await asyncio.open_unix_connection(str(self.path))

    def _challenge(self) -> str:
        lines = []
        for scheme in self.schemes:
            if scheme == 'Digest':
                qop = ', qop="auth"' if self.qop else ''
                lines.append(
                    f'WWW-Authenticate: Digest realm="{REALM}", nonce="{NONCE}", '
                    f'algorithm=MD5, stale=FALSE{qop}\r\n'
                )
            else:
                lines.append(f'WWW-Authenticate: Basic realm="{REALM}"\r\n')
        return ''.join(lines)

    def _authorised(self, method: str, header: str) -> bool:
        scheme, _, params = header.partition(' ')
        if scheme == 'Basic' and 'Basic' in self.schemes:
            import base64

            return base64.b64decode(params).decode() == f'{USER}:{self.password}'
        if scheme != 'Digest' or 'Digest' not in self.schemes:
            return False
        fields = {
            k: (v1 or v2) for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', params)
        }
        if fields.get('username') != USER or fields.get('realm') != REALM:
            return False
        if fields.get('nonce') != NONCE or not fields.get('uri'):
            return False
        ha1 = _h(f'{USER}:{REALM}:{self.password}')
        ha2 = _h(f'{method}:{fields["uri"]}')
        if self.qop:
            if fields.get('qop') != 'auth' or not fields.get('cnonce') or not fields.get('nc'):
                return False
            expected = _h(f'{ha1}:{NONCE}:{fields["nc"]}:{fields["cnonce"]}:auth:{ha2}')
        else:
            expected = _h(f'{ha1}:{NONCE}:{ha2}')
        return fields.get('response') == expected

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                try:
                    raw = await reader.readuntil(b'\r\n\r\n')
                except (asyncio.IncompleteReadError, ConnectionError):
                    return
                self.received.append(raw)
                head, *header_lines = raw.decode('latin-1').split('\r\n')
                method, uri, _version = head.split(' ', 2)
                headers = {
                    k.strip().lower(): v.strip()
                    for k, _, v in (line.partition(':') for line in header_lines if line)
                }
                cseq = headers.get('cseq', '0')
                auth = headers.get('authorization', '')
                if not auth or not self._authorised(method, auth):
                    writer.write(
                        f'RTSP/1.0 401 Unauthorized\r\nCSeq: {cseq}\r\n'
                        f'{self._challenge()}\r\n'.encode()
                    )
                elif method != 'DESCRIBE' or not uri.endswith(STREAM_PATH):
                    writer.write(f'RTSP/1.0 404 Not Found\r\nCSeq: {cseq}\r\n\r\n'.encode())
                else:
                    body = SDP.encode()
                    writer.write(
                        f'RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\nContent-Type: application/sdp\r\n'
                        f'Content-Base: {uri}/\r\nContent-Length: {len(body)}\r\n\r\n'.encode()
                        + body
                    )
                await writer.drain()
        finally:
            writer.close()


@pytest.fixture
def sock() -> Iterator[Path]:
    """A short path for the fake camera's Unix socket (AF_UNIX paths are capped at 104 bytes).

    ``tmp_path`` is too long for one; this lives in a fresh ``mkdtemp`` under ``TMPDIR``.
    """
    directory = Path(tempfile.mkdtemp(prefix='rtsp-'))
    try:
        yield directory / 'cam.sock'
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def stream(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``scripts/onvif_stream.py`` with the ``onvif`` package stubbed and no subprocess."""
    stub: Any = types.ModuleType('onvif')
    stub.__file__ = str(Path(__file__).resolve().parents[1] / 'scripts' / 'onvif' / '__init__.py')
    stub.ONVIFCamera = object
    monkeypatch.setitem(sys.modules, 'onvif', stub)
    for var in ('ONVIF_USERNAME', 'ONVIF_PASSWORD', 'ONVIF_CAMERAS'):
        monkeypatch.delenv(var, raising=False)

    def _no_process(*_a: object, **_k: object) -> None:
        raise AssertionError('test-rtsp started a subprocess')

    monkeypatch.setattr(subprocess, 'run', _no_process)
    monkeypatch.setattr(subprocess, 'Popen', _no_process)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', _no_process)
    load_script('onvif_config', monkeypatch)  # the stream script imports it by bare name
    return load_script('onvif_stream', monkeypatch)


def _camera_config(stream: Any) -> Any:
    """One camera's config with the fake credentials."""
    return stream.CameraConfig(
        name='Front', ip='192.0.2.10', port=80, user=USER, password=FAKE_PASSWORD
    )


def _bare_uri() -> str:
    return 'rtsp' + '://192.0.2.10' + STREAM_PATH


def _fake_camera(uri: str) -> Any:
    """A connected ``ONVIFCamera`` stand-in reporting one profile with ``uri``."""

    class _Media:
        async def GetProfiles(self) -> list[types.SimpleNamespace]:  # noqa: N802
            encoder = types.SimpleNamespace(
                Resolution=types.SimpleNamespace(Width=1920, Height=1080), Encoding='H264'
            )
            return [
                types.SimpleNamespace(Name='P1', token='p1', VideoEncoderConfiguration=encoder)
            ]

        async def GetStreamUri(self, _request: object) -> types.SimpleNamespace:  # noqa: N802
            return types.SimpleNamespace(Uri=uri)

    class _Camera:
        async def create_media_service(self) -> _Media:
            return _Media()

        async def close(self) -> None:
            return None

    return _Camera()


# --- the probe against the fake camera ------------------------------------------------------


@pytest.mark.parametrize('qop', [False, True], ids=['digest', 'digest-qop-auth'])
async def test_describe_with_the_right_password_returns_the_sdp(
    stream: Any, sock: Path, qop: bool
) -> None:
    async with FakeRtspCamera(sock, password=FAKE_PASSWORD, qop=qop) as cam:
        result = await stream.rtsp_describe(
            _bare_uri(), USER, FAKE_PASSWORD, timeout=5, open_connection=cam.open
        )
    assert result.status == 200 and result.auth == 'digest'
    assert 'a=rtpmap:96 H264/90000' in result.sdp
    assert result.media() == ['video H264 1920x1080', 'audio MPEG4-GENERIC']
    assert cam.requests[0] == {'host': '192.0.2.10', 'port': '554'}
    # Digest never puts the password on the wire, let alone on a command line.
    assert all(FAKE_PASSWORD.encode() not in raw for raw in cam.received)
    assert any(b'Authorization: Digest' in raw for raw in cam.received)


async def test_describe_with_the_wrong_password_is_an_auth_failure(
    stream: Any, sock: Path
) -> None:
    async with FakeRtspCamera(sock, password=WRONG_PASSWORD, qop=False) as cam:
        with pytest.raises(stream.RtspError) as excinfo:
            await stream.rtsp_describe(
                _bare_uri(), USER, FAKE_PASSWORD, timeout=5, open_connection=cam.open
            )
    text = str(excinfo.value)
    assert '401' in text and 'authentication' in text.lower()
    assert FAKE_PASSWORD not in text
    assert len(cam.received) == 2  # the challenge, then one authenticated attempt; no retry loop


async def test_basic_is_used_only_when_the_camera_offers_nothing_else(
    stream: Any, sock: Path
) -> None:
    async with FakeRtspCamera(sock, password=FAKE_PASSWORD, schemes=('Basic',), qop=False) as cam:
        result = await stream.rtsp_describe(
            _bare_uri(), USER, FAKE_PASSWORD, timeout=5, open_connection=cam.open
        )
    assert result.status == 200 and result.auth == 'basic'


async def test_a_camera_that_never_answers_times_out(stream: Any, sock: Path) -> None:
    async def _silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Say nothing, but end when the probe hangs up: on 3.12 ``Server.wait_closed`` waits for
        # every active handler, so a fixed sleep here would stall the test for its full length.
        with contextlib.suppress(OSError, asyncio.IncompleteReadError):
            await reader.read()
        writer.close()

    server = await asyncio.start_unix_server(_silent, path=str(sock))
    try:

        async def _open(host: str, port: int) -> Any:
            return await asyncio.open_unix_connection(str(sock))

        started = asyncio.get_running_loop().time()
        with pytest.raises(stream.RtspError) as excinfo:
            await stream.rtsp_describe(
                _bare_uri(), USER, FAKE_PASSWORD, timeout=0.2, open_connection=_open
            )
        assert 'timed out' in str(excinfo.value)
        assert asyncio.get_running_loop().time() - started < 5, (
            'the deadline did not bound the probe'
        )
    finally:
        server.close()
        await asyncio.wait_for(server.wait_closed(), 5)


# --- the command ----------------------------------------------------------------------------


async def test_check_rtsp_reports_auth_accepted_and_the_sdp_without_a_subprocess(
    stream: Any,
    sock: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert not hasattr(stream, 'subprocess')
    assert 'subprocess' not in inspect.getsource(stream.check_rtsp)

    async def _get_camera(_config: Any) -> Any:
        return _fake_camera(_bare_uri())

    monkeypatch.setattr(stream, 'get_camera', _get_camera)
    async with FakeRtspCamera(sock, password=FAKE_PASSWORD, qop=False) as cam:
        monkeypatch.setattr(stream, 'OPEN_CONNECTION', cam.open)
        await stream.check_rtsp(_camera_config(stream))

    out = capsys.readouterr().out
    assert '✅' in out and 'accepted' in out and 'H264 1920x1080' in out
    assert 'Stream URI: ' + _bare_uri() in out
    assert FAKE_PASSWORD not in out and 'zq9x' not in out
    assert all(FAKE_PASSWORD.encode() not in raw for raw in cam.received)


async def test_check_rtsp_reports_a_rejected_account_without_the_password(
    stream: Any,
    sock: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def _get_camera(_config: Any) -> Any:
        return _fake_camera(_bare_uri())

    monkeypatch.setattr(stream, 'get_camera', _get_camera)
    async with FakeRtspCamera(sock, password=WRONG_PASSWORD, qop=False) as cam:
        monkeypatch.setattr(stream, 'OPEN_CONNECTION', cam.open)
        await stream.check_rtsp(_camera_config(stream))

    out = capsys.readouterr().out
    assert '❌' in out and '401' in out
    assert FAKE_PASSWORD not in out and 'zq9x' not in out


def test_the_command_promises_only_what_it_checks(stream: Any) -> None:
    """The docstring and the usage text say DESCRIBE/authentication/metadata, not viability."""
    doc = (stream.check_rtsp.__doc__ or '') + (stream.__doc__ or '')
    assert 'DESCRIBE' in doc and 'does not' in doc
    assert 'ffprobe' not in doc.lower()
