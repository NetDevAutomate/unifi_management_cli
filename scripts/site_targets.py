"""Read the one-off site scripts' targets from a JSON file outside the repository.

``apply_ap_channel_plan.py``, ``apply_stp_priorities_custom.py`` and
``remediate_stp_post_apply.py`` change one site's devices by name, so the names, channels,
priorities and ports they act on are that site's data (issue 046). The repository keeps
placeholders only, in ``site-targets.example.json`` next to this file. Each script reads its
own section of the real file, found in this order:

1. the path given with the script's ``--targets`` option;
2. ``$XDG_CONFIG_HOME/unifi_management_cli/site-targets.json``, or
   ``~/.config/unifi_management_cli/site-targets.json`` when ``XDG_CONFIG_HOME`` is unset.

A missing or unreadable file, a missing section, a key repeated in one object, an AP listed
twice in the channel plan or a malformed entry raises :class:`TargetsError`. Each script
reports it and exits 2 before it reads the controller config or contacts the controller. A
message names the file, and the section and the entry's position where they apply; it never
repeats an entry's value.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


EXAMPLE = Path(__file__).resolve().parent / 'site-targets.example.json'
FILE_NAME = 'site-targets.json'
CHANNEL_PLAN = 'apply_ap_channel_plan'
STP_PRIORITIES = 'apply_stp_priorities_custom'
POST_APPLY = 'remediate_stp_post_apply'
# The controller stores a radio width as a string; an int is accepted and then ignored.
WIDTHS = ('20', '40', '80', '160')
MAX_PRIORITY = 61440
PRIORITY_STEP = 4096


class TargetsError(Exception):
    """The site targets file is missing, unreadable or malformed."""


class _DuplicateKey(Exception):
    """An object in the targets file repeats a key; ``json`` would keep only the last one."""


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object, refusing a key it already holds (a ``json`` parser hook)."""
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise _DuplicateKey
        obj[key] = value
    return obj


def default_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the default targets file under the XDG config directory.

    Args:
        environ: The environment to read ``XDG_CONFIG_HOME`` from; ``os.environ`` when None.

    Returns:
        ``<config home>/unifi_management_cli/site-targets.json``.
    """
    env = os.environ if environ is None else environ
    base = env.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base).expanduser() / 'unifi_management_cli' / FILE_NAME


def load_section(
    section: str, path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> Any:
    """Return one script's section of the targets file.

    Args:
        section: The top-level key, named after the script.
        path: The file from ``--targets``; the default path when None.
        environ: The environment for the default path; ``os.environ`` when None.

    Returns:
        The section's parsed JSON value.

    Raises:
        TargetsError: The file is missing, unreadable, not UTF-8 or not JSON, repeats a key
            in one object, or has no such section.
    """
    target = Path(path).expanduser() if path else default_path(environ)
    try:
        text = target.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise TargetsError(
            f'{target}: not found. Copy {EXAMPLE.name} from scripts/ there and fill in '
            "this site's targets, or pass --targets PATH"
        ) from None
    except OSError as exc:
        raise TargetsError(f'{target}: cannot be read ({exc.strerror})') from None
    except UnicodeDecodeError:
        raise TargetsError(f'{target}: cannot be read (not UTF-8 text)') from None
    try:
        data = json.loads(text, object_pairs_hook=_unique_keys)
    except _DuplicateKey:
        raise TargetsError(
            f'{target}: an object lists the same key twice, so one entry would be lost'
        ) from None
    except ValueError as exc:
        line = getattr(exc, 'lineno', '?')
        raise TargetsError(f'{target}: not valid JSON (line {line})') from None
    if not isinstance(data, dict) or section not in data:
        raise TargetsError(f'{target}: no "{section}" section')
    return data[section]


def _is_int(value: object) -> bool:
    """True for an int that isn't a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_name(value: object) -> bool:
    """True for a non-empty, non-blank string."""
    return isinstance(value, str) and bool(value.strip())


def channel_plan(
    path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> list[tuple[str, int, str]]:
    """Return the 5 GHz channel plan: ``(AP name, primary channel, width)`` in apply order.

    Args:
        path: The file from ``--targets``; the default path when None.
        environ: The environment for the default path; ``os.environ`` when None.

    Returns:
        The plan entries, in the file's order (the AP the operator is connected through
        belongs last).

    Raises:
        TargetsError: The file or section is missing, an entry is malformed, or an AP is
            listed twice (it would be written and provisioned twice, the later entry
            winning).
    """
    where = f'{CHANNEL_PLAN}.channel_plan'
    raw = load_section(CHANNEL_PLAN, path, environ)
    entries = raw.get('channel_plan') if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise TargetsError(f'{where}: expected a non-empty list of [AP name, channel, width]')
    plan: list[tuple[str, int, str]] = []
    first_entry: dict[str, int] = {}
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, list) or len(entry) != 3:
            raise TargetsError(f'{where} entry {i}: expected [AP name, channel, width]')
        name, channel, width = entry
        if not _is_name(name):
            raise TargetsError(f'{where} entry {i}: the AP name must be a non-empty string')
        if name in first_entry:
            raise TargetsError(
                f'{where} entry {i}: the same AP as entry {first_entry[name]}; list each AP once'
            )
        first_entry[name] = i
        if not _is_int(channel) or channel <= 0:
            raise TargetsError(f'{where} entry {i}: the channel must be a positive integer')
        if not isinstance(width, str) or width not in WIDTHS:
            raise TargetsError(
                f'{where} entry {i}: the width must be one of "20", "40", "80" or "160", '
                'written as a string (the controller ignores an int)'
            )
        plan.append((name, channel, width))
    return plan


def stp_priorities(
    path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> dict[str, int]:
    """Return the explicit STP bridge priority for each switch, by switch name.

    Args:
        path: The file from ``--targets``; the default path when None.
        environ: The environment for the default path; ``os.environ`` when None.

    Returns:
        ``{switch name: priority}``, in the file's order. The order doesn't matter:
        ``apply_stp_priorities_custom.py`` applies the lowest priority, the intended root,
        first.

    Raises:
        TargetsError: The file or section is missing, or an entry is malformed.
    """
    where = f'{STP_PRIORITIES}.priorities'
    raw = load_section(STP_PRIORITIES, path, environ)
    entries = raw.get('priorities') if isinstance(raw, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise TargetsError(f'{where}: expected a non-empty object of switch name: priority')
    priorities: dict[str, int] = {}
    for i, (name, priority) in enumerate(entries.items(), 1):
        if not _is_name(name):
            raise TargetsError(f'{where} entry {i}: the switch name must be non-empty')
        if not _is_int(priority) or not 0 <= priority <= MAX_PRIORITY or priority % PRIORITY_STEP:
            raise TargetsError(
                f'{where} entry {i}: the priority must be a multiple of {PRIORITY_STEP} '
                f'from 0 to {MAX_PRIORITY}'
            )
        priorities[name] = priority
    return priorities


def post_apply_ports(
    path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> tuple[str, dict[str, dict[int, str]]]:
    """Return the port profile to apply and the ports to apply it to.

    Args:
        path: The file from ``--targets``; the default path when None.
        environ: The environment for the default path; ``os.environ`` when None.

    Returns:
        ``(profile name, {switch name: {port number: port name}})``.

    Raises:
        TargetsError: The file or section is missing, or an entry is malformed.
    """
    raw = load_section(POST_APPLY, path, environ)
    if not isinstance(raw, dict):
        raise TargetsError(f'{POST_APPLY}: expected an object with port_profile and ports')
    profile = raw.get('port_profile')
    if not _is_name(profile):
        raise TargetsError(f'{POST_APPLY}.port_profile: expected the port profile name')
    where = f'{POST_APPLY}.ports'
    switches = raw.get('ports')
    if not isinstance(switches, dict) or not switches:
        raise TargetsError(
            f'{where}: expected an object of switch name: {{port number: port name}}'
        )
    ports: dict[str, dict[int, str]] = {}
    for i, (switch, table) in enumerate(switches.items(), 1):
        if not _is_name(switch) or not isinstance(table, dict) or not table:
            raise TargetsError(
                f'{where} entry {i}: expected a switch name and an object of port number: '
                'port name'
            )
        parsed: dict[int, str] = {}
        for key, port_name in table.items():
            if not key.isdecimal() or int(key) <= 0:
                raise TargetsError(f'{where} entry {i}: port numbers must be positive integers')
            if not _is_name(port_name):
                raise TargetsError(f'{where} entry {i}: port names must be non-empty strings')
            if int(key) in parsed:
                raise TargetsError(
                    f'{where} entry {i}: a port number is listed twice (as "2" and "02", say)'
                )
            parsed[int(key)] = port_name
        ports[switch] = parsed
    return str(profile), ports
