#!/usr/bin/env python3
"""Dump the controller's config and state objects to JSON files, secrets removed. Read-only.

One GET per endpoint of a fixed table (``ENDPOINTS``), through a logged-in
``UnifiApiClient`` behind the read-only guard (``install_read_only_guard``), so a write
can't leave the host. Every payload goes through ``strip_secrets`` before it is written as
``<name>.json``; ``manifest.json`` lists, per endpoint, the HTTP status and a record count
(or the redacted error), every removed secret path, and the guard's request audit (method
and path only). Files are ``0o600``, each created new (``O_EXCL | O_NOFOLLOW``, so nothing
already there is followed or overwritten), and a new output directory ``0o700``.

``--output`` is required and refused inside this repository (exit 2), so a dump can't be
committed by accident: raw controller objects describe the whole site even with their
secrets removed. It must be a new directory, or an empty one you own that no other user can
write to and that is not a symbolic link (exit 2 otherwise); every file is created in the
directory as it was opened, so a file or symlink planted there can't redirect a write.
Events and alarms are not in the table: ``unifi-mapper controller events --json`` reads
them through the allowlisted readers.

Rebuilt from the July work's IoT diagnostic fetch (a local archive, not in the repo): no
``reports/`` default, no hard-coded config path, the guard installed, secrets stripped,
and the endpoints that returned 404 in July's own capture (legacy ``stat/event``,
``stat/alarm``, ``stat/dhcp``; v2 ``events``, ``mdns``) and ``stat/rogueap`` (detection
data, read by ``unifi-mapper analyze neighbours``) dropped.

Usage:
    uv run python scripts/controller_dump.py --output ~/tmp/controller-dump
    uv run python scripts/controller_dump.py --output DIR --endpoint wlanconf --endpoint sta
    uv run python scripts/controller_dump.py --config PATH --output DIR

The config is ``--config``, else ``UNIFI_CONFIG``, else ``unifi-mapper``'s default search.
Exit codes: 0 every endpoint read, 1 a failed login or endpoint, 2 a bad argument or
``--output``. A failed logout afterwards is one redacted warning line; the exit code stands.
"""

import argparse
import json
import os
import stat
import sys
from datetime import UTC, datetime
from loguru import logger
from pathlib import Path
from typing import Any
from unifi_mapper.cli import get_default_config_path, load_env_from_config
from unifi_mapper.core.utils.readonly import install_read_only_guard
from unifi_mapper.core.utils.redact import redact_text
from unifi_mapper.diagnostic_reads import Collection, api_path, rows, v2_path


REPO_ROOT = Path(__file__).resolve().parents[1]
# name -> (API family, path below the site prefix)
ENDPOINTS: dict[str, tuple[str, str]] = {
    'wlanconf': ('legacy', 'rest/wlanconf'),
    'networkconf': ('legacy', 'rest/networkconf'),
    'setting': ('legacy', 'rest/setting'),
    'firewallrule': ('legacy', 'rest/firewallrule'),
    'firewallgroup': ('legacy', 'rest/firewallgroup'),
    'sta': ('legacy', 'stat/sta'),
    'device': ('legacy', 'stat/device'),
    'health': ('legacy', 'stat/health'),
    'firewall-policies': ('v2', 'firewall-policies'),
    'firewall-zone': ('v2', 'firewall/zone'),
    'trafficrules': ('v2', 'trafficrules'),
    'apgroups': ('v2', 'apgroups'),
}


def inside_repo(path: Path, root: Path = REPO_ROOT) -> bool:
    """Whether ``path`` (resolved) is the repository root or anywhere under it."""
    resolved = path.resolve()
    return resolved == root or root in resolved.parents


def config_path(given: str | None) -> Path:
    """``--config``, else ``UNIFI_CONFIG``, else ``unifi-mapper``'s default search."""
    if given:
        return Path(given).expanduser()
    from_env = os.environ.get('UNIFI_CONFIG')
    if from_env:
        return Path(from_env).expanduser()
    return get_default_config_path()


def _write_private(dir_fd: int, name: str, data: Any) -> None:
    """Write ``data`` as indented JSON to a new file ``name`` in the open directory, ``0o600``.

    The file is opened ``O_CREAT | O_EXCL | O_NOFOLLOW`` relative to ``dir_fd``: a file or
    symlink already there raises ``FileExistsError`` and is never followed, truncated or
    re-moded, and a path swapped after the checks can't move the write elsewhere.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(name, flags, 0o600, dir_fd=dir_fd)
    os.fchmod(fd, 0o600)  # a umask keeps no wider mode
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=1, default=str, sort_keys=True)
        file.write('\n')


def _unsafe(info: os.stat_result, output: Path) -> str | None:
    """Why a directory's owner or mode can't take a dump, or None."""
    if info.st_uid != os.getuid():
        return f'--output is not your directory: {output}'
    if stat.S_IMODE(info.st_mode) & 0o022:
        return f'--output is writable by other users: {output}'
    return None


def output_refusal(output: Path) -> str | None:
    """Why an existing ``--output`` can't take a dump, or None when it can.

    The dump writes predictable names (``<endpoint>.json``), so an existing directory must be
    the user's own, writable by no one else and empty, and not a symbolic link: nothing
    planted there can redirect a write. A path that does not exist yet is fine; it is
    created ``0o700``.

    Args:
        output: The ``--output`` path, ``~`` expanded.

    Returns:
        The reason to refuse it (exit 2), or None.
    """
    try:
        info = os.lstat(output)
    except FileNotFoundError:
        return None
    except OSError as e:
        return f'cannot check --output {output}: {e.strerror or type(e).__name__}'
    if stat.S_ISLNK(info.st_mode):
        return f'--output is a symbolic link: {output}'
    if not stat.S_ISDIR(info.st_mode):
        return f'--output is not a directory: {output}'
    unsafe = _unsafe(info, output)
    if unsafe is not None:
        return unsafe
    try:
        empty = not any(output.iterdir())
    except OSError as e:
        return f'cannot check --output {output}: {e.strerror or type(e).__name__}'
    if not empty:
        return f'--output must be a new or empty directory: {output}'
    return None


def dump(client: Any, site: str, output: Path, names: list[str]) -> dict[str, Any]:
    """Read each named endpoint through the read-only guard and write it, secrets removed.

    Args:
        client: A logged-in ``UnifiApiClient``; the guard is installed here.
        site: The controller site.
        output: An empty directory to write into (``main`` checks it first); it is opened
            once without following a link, checked again, and every file is created in it.
        names: Keys of :data:`ENDPOINTS`, in order.

    Returns:
        The manifest written to ``manifest.json``.

    Raises:
        OSError: ``output`` is a link or not a directory now, or a file is already there.
        RuntimeError: ``output``'s owner or mode changed since ``main`` checked it.
    """
    dir_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        unsafe = _unsafe(os.fstat(dir_fd), output)
        if unsafe is not None:
            raise RuntimeError(unsafe)
        return _dump_into(client, site, dir_fd, names)
    finally:
        os.close(dir_fd)


def _dump_into(client: Any, site: str, dir_fd: int, names: list[str]) -> dict[str, Any]:
    """:func:`dump`'s reads and writes, into the directory open as ``dir_fd``."""
    audit = install_read_only_guard(client, site)
    collection = Collection()
    endpoints: dict[str, dict[str, Any]] = {}
    for name in names:
        family, suffix = ENDPOINTS[name]
        path = (api_path if family == 'legacy' else v2_path)(client, site, suffix)
        result = collection.fetch(client, path, section=name)
        if not result.ok:
            endpoints[name] = {'status': result.status, 'error': collection.errors[-1].error}
            continue
        cleaned = collection.clean(result.data, name)
        _write_private(dir_fd, f'{name}.json', cleaned)
        endpoints[name] = {'status': result.status, 'records': len(rows(cleaned))}
    manifest = {
        'generated_utc': datetime.now(UTC).isoformat(timespec='seconds'),
        'endpoints': endpoints,
        'sanitised_paths': sorted(collection.sanitised_paths),
        'request_audit': list(audit),
    }
    _write_private(dir_fd, 'manifest.json', manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Dump controller config and state objects (read-only, secrets removed).'
    )
    parser.add_argument('--config', help='env file (default: UNIFI_CONFIG, then the default)')
    parser.add_argument(
        '--output',
        required=True,
        help='a new or empty directory for the dump; refused inside the repository',
    )
    parser.add_argument(
        '--endpoint',
        action='append',
        choices=sorted(ENDPOINTS),
        help='an endpoint to dump (repeatable; default: all)',
    )
    return parser


def _logout(client: Any) -> None:
    """Log out; a failure is one redacted warning line, and the dump's exit code stands."""
    try:
        client.logout()
    except Exception as e:  # noqa: BLE001 - never a traceback, which could print a secret
        print(
            f'controller_dump: logout failed (the dump is complete): {redact_text(e)}',
            file=sys.stderr,
        )


def _login(path: Path) -> tuple[Any, str]:
    """A logged-in ``UnifiApiClient`` from the env file at ``path``, and its site."""
    from unifi_mapper.api_client import UnifiApiClient
    from unifi_mapper.config import UnifiConfig

    load_env_from_config(str(path))
    config = UnifiConfig.from_env(str(path))
    client = UnifiApiClient(
        base_url=config.base_url,
        site=config.site,
        verify_ssl=config.verify_ssl,
        username=config.username,
        password=config.password,
        api_token=config.api_token,
        timeout=config.timeout,
    )
    if not client.login():
        raise RuntimeError('could not authenticate to the controller')
    return client, config.site


def main(argv: list[str] | None = None) -> int:
    """Run the dump; return the exit code."""
    args = _parser().parse_args(argv)
    # A logged traceback must never show frame values (the config's credentials).
    logger.remove()
    logger.add(sys.stderr, level='WARNING', diagnose=False)
    output = Path(args.output).expanduser()
    if inside_repo(output):
        print('controller_dump: --output must be outside the repository', file=sys.stderr)
        return 2
    refusal = output_refusal(output)
    if refusal is not None:
        print(f'controller_dump: {refusal}', file=sys.stderr)
        return 2
    try:
        if not output.exists():
            output.mkdir(mode=0o700, parents=True)
            output.chmod(0o700)
        client, site = _login(config_path(args.config))
    except Exception as e:  # noqa: BLE001 - one redacted line, never a traceback
        print(f'controller_dump: {redact_text(e)}', file=sys.stderr)
        return 1
    try:
        manifest = dump(client, site, output, args.endpoint or list(ENDPOINTS))
    except Exception as e:  # noqa: BLE001 - one redacted line, never a traceback
        print(f'controller_dump: {redact_text(e)}', file=sys.stderr)
        return 1
    finally:
        _logout(client)
    failed = 0
    for name, entry in manifest['endpoints'].items():
        if 'error' in entry:
            failed += 1
            print(f'{name}: {entry["error"]}', file=sys.stderr)
        else:
            print(f'{name}: {entry["records"]} record(s)')
    print(f'Wrote {output} ({len(manifest["sanitised_paths"])} secret field(s) removed)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
