#!/usr/bin/env python3
"""Read-only live check of the CLI and the MCP server against the maintainer's controller.

Issue 039. Maintainer tooling, run by hand before a release; it is not part of the package.
Everything it does is a read: the CLI runs in this process behind the read-only guard with
the request audit on, and the MCP server runs as a fresh ``uvx --from <checkout>`` stdio
child with its call log and request audit on and the active probes forced off. One
``mutates: true`` tool is called only to confirm ``MUTATION_REFUSED`` with no controller
request sent. Results go under ``$XDG_STATE_HOME/unifi_mapper/live-check/<UTC stamp>/``
(never the repository) and every file written is scanned for the secret values in the
environment before the report is printed.

Usage::

    uv run python scripts/live_check.py [--config PATH] [--skip-mcp] [--skip-cli]

The config file (TOML; default ``$XDG_CONFIG_HOME/unifi_mapper/live-check.toml``) names the
switch and port the port-level checks target and the switches and ports to leave alone;
nothing network-specific is hard-coded here::

    switch = 'core-switch'  # the switch the port checks read
    port = 5  # a port on it (not excluded below)
    exclude_switches = ['edge-2']  # never read these switches' ports
    exclude_ports = ['core-switch/1', 'core-switch/2']
    required_vlans = [10, 20]  # for vlan-coverage
    checkout = '/path/to/checkout'  # optional; default: this script's repository
    # cli_commands = [["diagnose", "vlans", "--json"]]            # optional override
    # [[mcp_tools]]                                               # optional additions
    # name = "diagnose_vlans"
    # args = {}

Exit status: 0 when every check passed (``unverified`` checks do not fail the run), 1 when a
check failed, 2 for a configuration problem.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MUTATION_REFUSED = 'MUTATION_REFUSED'
ACTIVE_PROBES_ENV = 'UNIFI_MCP_ALLOW_ACTIVE_PROBES'
PROBE_TOOLS = ('gateway_ping', 'gateway_traceroute', 'gateway_dns_check', 'run_latency_matrix')
SECRET_ENV_RE = re.compile(r'(TOKEN|PASSWORD|SECRET|AES_KEY|API_KEY)$')
MIN_SECRET_LEN = 6
DEFAULT_CLI_COMMANDS: tuple[tuple[str, ...], ...] = (
    ('inventory',),
    ('diagnose', 'vlans', '--json'),
    ('diagnose', 'firewall', '1', '1', '--json'),
    ('analyze', 'vlan-coverage'),
)
DEFAULT_MCP_TOOLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ('network_health_check', {}),
    ('diagnose_vlans', {}),
    ('detect_foreign_bridges', {}),
    ('diagnose_switch_port', {}),  # switch and port are filled from the config
)
MUTATING_TOOL = ('apply_stp_changes', {'changes': []})


@dataclass
class Config:
    """What the run targets, from the config file only."""

    switch: str
    port: int
    exclude_switches: list[str]
    exclude_ports: list[str]
    required_vlans: list[int]
    checkout: Path
    cli_commands: list[list[str]]
    mcp_tools: list[tuple[str, dict[str, Any]]]


@dataclass
class Check:
    """One line of the report."""

    name: str
    status: str  # pass | fail | unverified
    detail: str


@dataclass
class Report:
    """The run's checks, in order."""

    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        """Record a pass or a fail."""
        self.checks.append(Check(name, 'pass' if ok else 'fail', detail))

    def unverified(self, name: str, detail: str) -> None:
        """Record a check the run could not make (it does not fail the run)."""
        self.checks.append(Check(name, 'unverified', detail))

    @property
    def failed(self) -> bool:
        """True when any check failed."""
        return any(c.status == 'fail' for c in self.checks)


def default_config_path() -> Path:
    """``$XDG_CONFIG_HOME/unifi_mapper/live-check.toml`` (``~/.config`` when unset)."""
    base = os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base) / 'unifi_mapper' / 'live-check.toml'


def load_config(path: Path, repo_root: Path) -> Config:
    """Read the TOML config; refuse a target that the exclusions cover."""
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f'config not found: {path} (see the module docstring for the keys)')
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'config is not valid TOML: {path}: {e}')
    try:
        switch = str(raw['switch'])
        port = int(raw['port'])
    except KeyError as e:
        raise SystemExit(f'config {path} lacks the required key {e}')
    exclude_switches = [str(s) for s in raw.get('exclude_switches', [])]
    exclude_ports = [str(p) for p in raw.get('exclude_ports', [])]
    if switch in exclude_switches or f'{switch}/{port}' in exclude_ports:
        raise SystemExit(f'config {path}: the target {switch}/{port} is in its own exclusions')
    cli = [[str(a) for a in cmd] for cmd in raw.get('cli_commands', [])] or [
        list(c) for c in DEFAULT_CLI_COMMANDS
    ]
    tools = [(t[0], dict(t[1])) for t in DEFAULT_MCP_TOOLS]
    for entry in raw.get('mcp_tools', []):
        tools.append((str(entry['name']), dict(entry.get('args', {}))))
    return Config(
        switch=switch,
        port=port,
        exclude_switches=exclude_switches,
        exclude_ports=exclude_ports,
        required_vlans=[int(v) for v in raw.get('required_vlans', [])],
        checkout=Path(raw['checkout']).expanduser() if raw.get('checkout') else repo_root,
        cli_commands=cli,
        mcp_tools=tools,
    )


def load_env_file() -> str:
    """Load the CLI's env file into the environment (the CLI's own search order); return the site.

    Done once up front so the secret scan knows every secret value the run could leak, and so
    the fresh server child inherits the same settings the CLI used.
    """
    from unifi_mapper.cli import get_default_config_path, load_env_from_config
    from unifi_mapper.config import UnifiConfig

    config_path = str(get_default_config_path())
    load_env_from_config(config_path)
    return UnifiConfig.from_env(config_path).site


def run_dir() -> Path:
    """A fresh directory under the XDG state root, never under the repository."""
    from unifi_mapper.analysis.port_counter_baseline import state_dir

    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    out = state_dir() / 'live-check' / stamp
    out.mkdir(parents=True, exist_ok=False)
    out.chmod(0o700)
    return out


# --- the CLI, in process, behind the guard with the request audit on ---------------------------


def _cli_args(cmd: list[str], cfg: Config) -> list[str]:
    """Fill the config's VLAN list into vlan-coverage; everything else is as configured."""
    if (
        cmd[:2] == ['analyze', 'vlan-coverage']
        and cfg.required_vlans
        and '--required-vlans' not in cmd
    ):
        return [*cmd, '--required-vlans', ','.join(str(v) for v in cfg.required_vlans)]
    return cmd


def run_cli(cfg: Config, out: Path, report: Report) -> str:
    """Run each CLI command through the Typer app in this process; return the site name.

    Every controller request goes through the CLI's own read-only guard and is appended to
    ``cli-request-audit.jsonl``; afterwards each audited request is re-checked against the
    guard's allowlist, and a ``ReadOnlyViolation`` surfacing from any command fails the run.
    """
    from typer.testing import CliRunner
    from unifi_mapper import typer_cli
    from unifi_mapper.core.utils.readonly import (
        ReadOnlyViolation,
        configure_request_audit,
        request_allowed,
    )

    site = load_env_file()
    audit_path = out / 'cli-request-audit.jsonl'
    configure_request_audit(audit_path)
    outputs = out / 'cli-outputs'
    outputs.mkdir()
    runner = CliRunner()
    for n, cmd in enumerate(cfg.cli_commands, 1):
        args = _cli_args(cmd, cfg)
        result = runner.invoke(typer_cli.app, args, catch_exceptions=True)
        slug = '-'.join(a.strip('-') for a in cmd)[:60]
        (outputs / f'{n:02d}-{slug}.txt').write_text(result.output)
        violation = isinstance(result.exception, ReadOnlyViolation)
        crashed = result.exception is not None and not isinstance(result.exception, SystemExit)
        ok = result.exit_code in (0, 2) and not violation and not crashed
        what = (
            'READ_ONLY_VIOLATION'
            if violation
            else type(result.exception).__name__
            if crashed
            else f'exit {result.exit_code}'
        )
        report.add(f'cli: {" ".join(cmd)}', ok, f'{what}, {len(result.output)} bytes of output')
    configure_request_audit(None)
    lines = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
    outside = [
        f'{line["method"]} {line["path"]}'
        for line in lines
        if not request_allowed(line['method'], line['path'], site)[0]
    ]
    report.add(
        'cli: every audited request is inside the read-only allowlist',
        bool(lines) and not outside,
        f'{len(lines)} requests audited, {len(outside)} outside: {outside[:3]}',
    )
    return site


# --- the MCP server, as a fresh uvx stdio child --------------------------------------------------


def _text(result: Any) -> str:
    return ''.join(getattr(c, 'text', '') for c in result.content)


async def run_mcp(cfg: Config, out: Path, report: Report) -> None:
    """Drive a fresh ``uvx --from <checkout> unifi-mcp`` over stdio.

    Listings, the configured reads, and one mutating call that must be refused with no request.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    uvx = shutil.which('uvx')
    if uvx is None:
        report.unverified('mcp', 'uvx is not on PATH')
        return
    call_log = out / 'mcp-call-audit.jsonl'
    env = {k: v for k, v in os.environ.items() if k != ACTIVE_PROBES_ENV}
    env['UNIFI_MCP_CALL_AUDIT'] = str(call_log)
    env['UNIFI_MCP_REQUEST_AUDIT'] = 'on'
    env['UNIFI_MCP_TOOL_SURFACE'] = 'direct'  # list and call every tool by name
    params = StdioServerParameters(
        command=uvx,
        args=['--no-cache', '--from', str(cfg.checkout), 'unifi-mcp'],
        env=env,
        cwd=str(cfg.checkout),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        version = str(getattr(getattr(init, 'serverInfo', None), 'version', '?'))
        expected = checkout_version(cfg.checkout)
        report.add(
            'mcp: the fresh uvx server is the checkout',
            version == expected,
            f'server version {version}, checkout pyproject version {expected}',
        )
        listed = await session.list_tools()
        names = {t.name for t in listed.tools}
        report.add(
            'mcp: the direct surface lists the tools',
            len(names) > 50,
            f'{len(names)} tools listed',
        )
        probes = sorted(names & set(PROBE_TOOLS))
        report.add(
            'mcp: active probes are held back (gate unset)', not probes, f'listed: {probes}'
        )
        for name, args in cfg.mcp_tools:
            if name == 'diagnose_switch_port' and not args:
                args = {'switch': cfg.switch, 'port': cfg.port}
            result = await session.call_tool(name, args)
            text = _text(result)
            ok = not result.isError and MUTATION_REFUSED not in text
            report.add(
                f'mcp: {name}', ok, f'{"error" if result.isError else "ok"}, {len(text)} bytes'
            )
        name, args = MUTATING_TOOL
        before = len(_call_lines(call_log))
        # Through execute_tool, the meta surface every client sees, as an agent would reach it.
        result = await session.call_tool('execute_tool', {'tool_name': name, 'params': args})
        text = _text(result)
        report.add(
            f'mcp: {name} is refused',
            result.isError and MUTATION_REFUSED in text,
            f'isError={result.isError}, {MUTATION_REFUSED} named={MUTATION_REFUSED in text}',
        )
    lines = _call_lines(call_log)
    new = lines[before:]
    requests_during_refusal = [line for line in new if line.get('kind') == 'request']
    refusal = [line for line in new if line.get('kind') == 'call' and line.get('tool') == name]
    report.add(
        f'mcp: {name} sent no controller request',
        bool(refusal) and not requests_during_refusal,
        f'{len(refusal)} call line(s), {len(requests_during_refusal)} request line(s) '
        'in its window',
    )
    requests_total = sum(1 for line in lines if line.get('kind') == 'request')
    report.add(
        'mcp: request audit recorded the reads',
        requests_total > 0,
        f'{requests_total} request lines',
    )


def checkout_version(checkout: Path) -> str:
    """The version ``pyproject.toml`` in the checkout declares (what a fresh build must report)."""
    try:
        return str(tomllib.loads((checkout / 'pyproject.toml').read_text())['project']['version'])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return '?'


def _call_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- Protect, secrets, report -------------------------------------------------------------------


def check_protect(report: Report) -> None:
    """Report the Protect surface as unverified, naming why."""
    if not os.environ.get('PROTECT_HOST'):
        report.unverified(
            'protect', 'no Protect credentials in the environment (PROTECT_HOST unset)'
        )
        return
    report.unverified(
        'protect', 'credentials present; the Protect surface is not exercised by this harness yet'
    )


def secret_values() -> dict[str, str]:
    """The secret values in the environment, by variable name (names only ever leave here)."""
    return {
        k: v for k, v in os.environ.items() if SECRET_ENV_RE.search(k) and len(v) >= MIN_SECRET_LEN
    }


def scan_outputs(out: Path, report: Report) -> None:
    """Fail the run if any secret value from the environment appears in any file written."""
    secrets = secret_values()
    hits: list[str] = []
    for path in sorted(p for p in out.rglob('*') if p.is_file()):
        try:
            text = path.read_text(errors='replace')
        except OSError:
            continue
        for name, value in secrets.items():
            if value in text:
                hits.append(f'{name} in {path.relative_to(out)}')
    report.add(
        'outputs: no secret value appears in any file written',
        not hits,
        f'{len(secrets)} secret variable(s) checked against {sum(1 for _ in out.rglob("*"))} '
        f'paths; hits: {hits}',
    )


def write_report(out: Path, report: Report) -> None:
    """Write ``report.json`` beside the audits."""
    (out / 'report.json').write_text(
        json.dumps(
            {
                'run': out.name,
                'result': 'fail' if report.failed else 'pass',
                'checks': [c.__dict__ for c in report.checks],
            },
            indent=2,
        )
        + '\n'
    )


def print_report(out: Path, report: Report) -> None:
    """Print one line per check and the overall result with the run directory."""
    width = max(len(c.name) for c in report.checks)
    for c in report.checks:
        mark = {'pass': 'PASS', 'fail': 'FAIL', 'unverified': '----'}[c.status]
        print(f'{mark}  {c.name.ljust(width)}  {c.detail}')
    print(f'\n{"FAIL" if report.failed else "PASS"}: {out}')


def main(argv: list[str] | None = None) -> int:
    """Run the checks; return the exit status."""
    parser = argparse.ArgumentParser(description=(__doc__ or '').split('\n\n')[0])
    parser.add_argument('--config', type=Path, default=default_config_path())
    parser.add_argument('--skip-mcp', action='store_true')
    parser.add_argument('--skip-cli', action='store_true')
    ns = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(ns.config, repo_root)
    load_env_file()
    out = run_dir()
    report = Report()
    if not ns.skip_cli:
        run_cli(cfg, out, report)
    if not ns.skip_mcp:
        asyncio.run(run_mcp(cfg, out, report))
    check_protect(report)
    scan_outputs(out, report)
    write_report(out, report)
    print_report(out, report)
    return 1 if report.failed else 0


if __name__ == '__main__':
    sys.exit(main())
