# UniFi Management CLI

Discover, diagnose and document a UniFi network from the command line, and let an AI
assistant read it through a read-only MCP server. It talks to a UniFi Network controller
(a UniFi OS console or a classic controller) over its HTTPS API; a few diagnostics also use
the gateway over SSH. Community tool, not affiliated with Ubiquiti.

What it is good at:

- **Port evidence**: every port's speed, duplex, profile, LLDP peer, clients and error
  counters, as a report or a JSON bundle you can attach to a vendor ticket.
- **Health checks**: 15 read-only diagnostics in one run (`diagnose all`), a WAN and
  speedtest history, AP retry rates, client connectivity from the client's VLAN.
- **Fleet audits**: link speeds below capability, MTU on uplinks, PoE budgets, STP root and
  priority placement, single-uplink switches, DHCP pool use.
- **Port names from LLDP**: preview the names a switch's ports should carry, then write them
  only when you say so.
- **An MCP server** with 82 read-only tools, so Claude, Codex or any MCP client can answer
  "why is my phone slow?" against your own controller.

## Safety model

Read this before pointing it at a production network.

- **Reads by default.** Every command only reads the controller unless it is one of the few
  that can write (`discover --apply`, `ports refresh --apply`, `stp apply --no-dry-run`,
  `stp rollback --no-dry-run`, `stp optimize --apply`, `radio optimize --apply`,
  `radio restore --apply`, `inventory update-firmware --apply`). Each of those previews first
  and needs the explicit flag; the firmware command also asks for confirmation, which only
  `--force` skips.
- **The MCP server never writes** to the controller and never opens SSH. It exposes read-only
  tools only, keeps a call log of tool names and argument *keys* (never values), and strips
  secrets from every result.
- **Secrets are stripped, not masked**, from anything the tool prints, logs or saves. The
  stripping is by key name (`x_*`, and keys containing password, secret, token, authkey, psk,
  preshared or pre-shared, passphrase, api_key, private_key, plus the SNMP community and
  syslog key); only
  the paths of what was removed are reported. A credential typed into a free-text field under
  some other key would not be caught. **Reports are still sensitive**: device names, MAC and IP
  addresses and your topology remain in them. Review before you post one anywhere.
- **TLS verification is off by default** (`UNIFI_VERIFY_SSL=false`), because most consoles
  present a self-signed certificate. Turn it on if yours has a trusted one.
- **Gateway SSH host keys are not verified yet** ([issue 038](docs/issues/038-ssh-host-key-verification-disabled.md)),
  so a device on the path between you and the gateway could impersonate it and receive the SSH
  password. Use the SSH-based commands (`gateway *`, `diagnose latency-matrix|bandwidth|client-connectivity|ap-health`,
  `vlan-traffic sample`) only from a trusted LAN segment; they are CLI-only and run only when
  `UNIFI_SSH_PASSWORD` is set.
- Tracebacks never print local variables; the config file is never written back.

See [SECURITY.md](SECURITY.md) for the full data-handling contract and how to report a problem.

## Requirements

- Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/).
- A UniFi Network controller you can reach over HTTPS, and either an API token (recommended:
  UniFi OS > Control Plane > Integrations, or a local admin's API key) or a local admin's
  username and password. A read-only admin is enough for everything except the writes above.
- Optional: Graphviz (`brew install graphviz` / `apt install graphviz`) for PNG and SVG
  diagrams; `--format html` needs nothing extra.

Tested against UniFi Network 10.x on a UniFi OS console with USW switches, U6/U7 access
points and a UDM/UXG gateway. Classic (non-UniFi OS) controllers use port 8443 and are
exercised less. UniFi Protect support is a library and five MCP tools that have **not** been
verified against a live console ([issue 034](docs/issues/034-protect-has-no-live-account.md)).

## Five-minute start

```bash
git clone https://github.com/NetDevAutomate/unifi_management_cli.git
cd unifi_management_cli
uv sync
```

Create the config file. Keys and values only; a comment is a line starting with `#`, or a
` #` after a value.

```bash
mkdir -p ~/.config/unifi_management_cli
cat > ~/.config/unifi_management_cli/prod.env <<'EOF'
UNIFI_URL=https://192.0.2.1
UNIFI_SITE=default
UNIFI_CONSOLE_API_TOKEN=paste-your-token-here
UNIFI_VERIFY_SSL=false
EOF
chmod 600 ~/.config/unifi_management_cli/prod.env
```

Inside the checkout every command is `uv run unifi-mapper …`; `uv tool install .` installs it
once so that `unifi-mapper …` works from any directory. Run the health check (reads only;
exit 0 when nothing is wrong, 2 when a check fails):

```bash
uv run unifi-mapper diagnose all
```

`diagnose all` runs 15 checks: link quality, capacity planning, port profiles, MTU consistency, SFP diagnostics, radio optimisation, firmware skew, DHCP pools, PoE budget, client density, uplink redundancy, uplink VLAN transparency, device power budget, foreign bridges and telemetry freshness.

Then look at one switch, and preview the port names LLDP suggests (nothing is written):

```bash
uv run unifi-mapper ports list "Office Switch"
uv run unifi-mapper ports inspect "Office Switch" 7
uv run unifi-mapper discover --format html          # HTML needs no Graphviz
uv run unifi-mapper discover --format html --apply  # only when the preview looks right
```

`diagnose all` prints one line per check (`✅`, `⚠️` or `❌` with the finding), then a
pass/warn/fail count; it exits 2 when any check fails, so it works in a script or a cron job.

`unifi-mapper` and `unifi-mcp` share one config search: `--config PATH` or `UNIFI_CONFIG`,
else `$XDG_CONFIG_HOME/unifi_management_cli/{prod,default}.env` (an absolute
`XDG_CONFIG_HOME` only), then `~/.config/unifi_management_cli/{prod,default}.env`, then the
legacy `~/.config/unifi_network_mapper/prod.env` with a warning. The CLI alone still reads
`./.env` last, with a deprecation warning; that fallback is removed in 0.4.0. When none
exists it lists every path it tried. [`.env.example`](.env.example)
documents every key, including the optional gateway SSH, Network Integration API and Protect
settings.

## What you can do

98 commands in 17 groups; `unifi-mapper --help` lists them and
[docs/reference/cli.md](docs/reference/cli.md) has an example for each. The ones people
reach for first:

| Task | Command | Writes? |
| --- | --- | --- |
| Health summary of the whole site | `diagnose all` | no |
| Why one port is slow or flapping | `ports inspect "Switch" 7`, `ports diagnose "Switch" 7 --json` | no |
| Where a client is, and its history | `ports client aa:bb:cc:dd:ee:ff` | no |
| Ports negotiated below capability | `analyze link-speeds` | no |
| STP: who is root, what should change | `stp audit-priorities`, `stp optimize`, `stp apply --plan FILE` | only with `--apply` / `--no-dry-run` |
| Wi-Fi channel plan | `radio report`, `radio optimize` | only with `--apply` |
| Firmware status across the fleet | `inventory list`, `inventory check-updates` | no |
| Port names from LLDP | `discover`, `discover --apply` | only with `--apply` |
| Per-VLAN traffic over time (SSH) | `vlan-traffic sample` then `vlan-traffic report` | no (local store) |
| Config objects and recent changes | `controller config wlanconf`, `controller config-changes` | no |
| Check a downloaded backup offline | `backup verify site.unf` | no |

```bash
unifi-mapper analyze link-speeds
unifi-mapper stp audit-priorities
unifi-mapper stp analyze
unifi-mapper radio snapshot
unifi-mapper radio report
unifi-mapper inventory check-updates
unifi-mapper ports refresh "Office Switch"          # previews the LLDP-derived labels
unifi-mapper ports refresh "Office Switch" --apply
unifi-mapper controller config-changes --since-hours 168
unifi-mapper backup verify site.unf
unifi-mapper vlan-traffic report
unifi-mapper ports client aa:bb:cc:dd:ee:ff
unifi-mapper gateway ping 192.0.2.1
```

Exit codes: 0 done, 1 an error (one line on stderr; `--debug` for a traceback), 2 a usage
error or a check that failed, 130 interrupted. The full table, with every command that exits
2 on a failed check, is in the [command reference](docs/reference/cli.md#command-reference).

`unifi-network-toolkit` and `unifi-inventory` are older entry points over the same code and
will be removed in a later release; use `unifi-mapper`, which has every command and the same
preview-by-default rule.

Scheduled audits (launchd or cron) are installed by
[`scripts/unifi-cron.sh`](docs/reference/cli.md#scheduled-audits); the default schedule only
reads, and the port-naming write is opt-in.

## MCP server

`unifi-mcp` serves the tool catalog over stdio. The catalog holds 96 entries in 7 categories:
82 are read-only tools a client can call, 11 are pipeline steps that pass in-process objects
between those tools, and 3 are the CLI's write operations, which the server refuses to run. By
default a client sees 4 discovery meta-tools (`search_tools`, `get_tool_info`,
`list_categories`, `execute_tool`); with `UNIFI_MCP_TOOL_SURFACE=direct` it sees those 4 plus
the 82 tools, 86 in all. It reads the same config file. Results flow to the AI host you connect
it to, so the same "reports are sensitive" rule applies. Every read-only CLI command has an MCP
tool or a recorded reason (the SSH probes and the long-running AP sampler are CLI-only by
decision); a test enforces it, so the two surfaces cannot drift apart silently.

> [!WARNING]
> `unifi-mcp` on PyPI is an unrelated third-party package. Always run this one from the
> checkout: `uvx --from /ABS/PATH/TO/unifi_management_cli unifi-mcp`.

```json
{
  "mcpServers": {
    "unifi": {
      "command": "uvx",
      "args": ["--python", "3.12", "--from", "/ABS/PATH/TO/unifi_management_cli", "unifi-mcp"],
      "env": { "UNIFI_CONFIG": "/Users/you/.config/unifi_management_cli/prod.env" }
    }
  }
}
```

`unifi-mcp --check` prints where the config comes from and which credential families are
ready (key names only). The [MCP server guide](docs/mcp-server/MCP_SERVER_GUIDE.md) covers
every setting, the error codes, the call log and the client configs.

## Known limitations

The open items live in [docs/issues](docs/issues/README.md), one file each, with the
reasoning. The ones that affect use today:

- Gateway SSH host keys are not verified (038); Protect tools are unverified live (034).
- `monitor_lags` misses LAGs on current switch firmware (061).
- PNG and SVG diagrams need Graphviz's `dot`; without it `discover` writes a placeholder and
  its report (075). MQTT needs the `mqtt` extra: `uv sync --extra mqtt` (074).

## Documentation

- [Use cases and how-to](docs/guides/use-cases-and-howto.md): task-by-task walkthroughs.
- [Command reference](docs/reference/cli.md): every command with an example; exit codes;
  scheduled audits; the read-only scripts.
- [Troubleshooting and runbook](docs/operations/troubleshooting-and-runbook.md).
- [MCP server guide](docs/mcp-server/MCP_SERVER_GUIDE.md) and the
  [MCP standards review](docs/mcp-server/MCP_STANDARDS_REVIEW.md).
- [Protect and AXIS integration](docs/guides/protect-and-axis.md),
  [AXIS provisioning](docs/guides/axis-provisioning.md).
- [Architecture](docs/architecture/README.md): overview, C4 diagrams, codebase map.

## Contributing

`uv sync && uv run pre-commit install && uv run pytest -m "not live"` gets you to green
(about 80 s, no controller needed). [CONTRIBUTING.md](CONTRIBUTING.md) has the gates and the
rules that are not negotiable: reads become CLI commands and read-only MCP tools, writes are
CLI-only and preview by default, fixtures use documentation addresses.

## Licence and attribution

MIT, see [LICENSE.md](LICENSE.md). Protect support builds on
[uiprotect](https://github.com/uilibs/uiprotect) (MIT). Not affiliated with or endorsed by
Ubiquiti Inc.; UniFi is their trademark.
