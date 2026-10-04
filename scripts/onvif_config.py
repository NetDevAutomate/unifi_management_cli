"""Camera list and credentials for the ONVIF scripts, read from the environment.

``onvif_probe.py`` and ``onvif_stream.py`` keep no camera address, name or password in the
repository (issue 041). Both read three environment variables:

- ``ONVIF_USERNAME`` and ``ONVIF_PASSWORD``: the ONVIF account on the cameras;
- ``ONVIF_CAMERAS``: comma-separated ``NAME=HOST[:PORT]`` entries (port 80 when omitted).

Keep them in a file outside the repository and pass it to each run, for example::

    uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_stream.py info

This module doesn't import the ONVIF library, so it loads without it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field


USERNAME_VAR = 'ONVIF_USERNAME'
PASSWORD_VAR = 'ONVIF_PASSWORD'  # pragma: allowlist secret (a variable name)
CAMERAS_VAR = 'ONVIF_CAMERAS'
DEFAULT_PORT = 80
HELP = (
    f"Set {USERNAME_VAR} and {PASSWORD_VAR} to the cameras' ONVIF account and {CAMERAS_VAR}"
    ' to comma-separated NAME=HOST[:PORT] entries (docs/guides/axis-provisioning.md,'
    ' section 8).'
)


class ConfigError(Exception):
    """The ONVIF settings are missing or malformed. The message never holds the password."""


@dataclass(frozen=True)
class CameraConfig:
    """ONVIF camera connection settings."""

    name: str
    ip: str
    port: int
    user: str
    password: str = field(repr=False)


def _parse_camera(entry: str) -> tuple[str, str, int]:
    """Split one ``NAME=HOST[:PORT]`` entry.

    Args:
        entry: One comma-separated item of ``ONVIF_CAMERAS``, already stripped.

    Returns:
        The camera's name, host and port (``DEFAULT_PORT`` when the entry has none).

    Raises:
        ConfigError: If the entry has no name or host, or its port isn't 1-65535.
    """
    name, sep, address = (part.strip() for part in entry.partition('='))
    host, port_text = address, ''
    if address.count(':') == 1:
        host, _, port_text = address.partition(':')
    if not sep or not name or not host:
        raise ConfigError(f'{CAMERAS_VAR} entry {entry!r} is not NAME=HOST[:PORT]. {HELP}')
    if not port_text:
        return name, host, DEFAULT_PORT
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise ConfigError(f'{CAMERAS_VAR} entry {entry!r} has a port outside 1-65535')
    return name, host, int(port_text)


def load_cameras(environ: Mapping[str, str] | None = None) -> list[CameraConfig]:
    """Read the camera list and the shared ONVIF account.

    Args:
        environ: The variables to read; ``os.environ`` when omitted.

    Returns:
        One ``CameraConfig`` per ``ONVIF_CAMERAS`` entry, in the order given.

    Raises:
        ConfigError: If a variable is unset or empty, or an entry is malformed. The message
            names every missing variable and never includes the password.
    """
    env = os.environ if environ is None else environ
    values = {var: env.get(var, '') for var in (USERNAME_VAR, PASSWORD_VAR, CAMERAS_VAR)}
    missing = [var for var, value in values.items() if not value.strip()]
    if missing:
        raise ConfigError(f'not set: {", ".join(missing)}. {HELP}')
    entries = [item.strip() for item in values[CAMERAS_VAR].split(',') if item.strip()]
    if not entries:
        raise ConfigError(f'{CAMERAS_VAR} lists no camera. {HELP}')
    user, password = values[USERNAME_VAR], values[PASSWORD_VAR]
    return [
        CameraConfig(name, host, port, user, password)
        for name, host, port in map(_parse_camera, entries)
    ]
