# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The current release is 0.2.0; only the latest release is supported.

## [Unreleased]

### History rewrite (2026-10-12): clones made before this date must be re-cloned

The whole history from 2025-04-25 on was rewritten to remove three credentials, the
maintainer's own network identifiers (device names, MAC addresses, addresses of four subnets)
and three internal document paths that should never have been committed. Every commit hash
changed; the tree at the tip did not (the code is identical). `main` was force-pushed on
2026-10-12. If you cloned or forked before then:

- do not merge, rebase or pull the old history into the new one; delete the clone and clone
  again (or `git fetch origin && git reset --hard origin/main` in a clone with no local work);
- a fork keeps the old history until it is deleted and re-forked;
- commit hashes cited in older issues, notes or links no longer resolve; the hashes cited in
  this repository's own documents were remapped.

The removed credentials were rotated or belong to decommissioned services. The maintainer has
asked GitHub Support to purge the superseded commits from the server's object store and caches.

### Changed (behaviour)

- `unifi-network-toolkit discover` and `python -m unifi_mapper.cli` preview by default and write
  port names only with `--apply`, like `unifi-mapper discover`; `--dry-run` is still accepted and
  means the default; both flags together exit 2. A script that relied on the old write-by-default
  must add `--apply` (issue 015).
- `scripts/unifi-cron.sh` installs six read-only tasks; the port-naming job, which writes port
  names every 30 minutes, is scheduled or run only with `--with-port-naming`. Its launchd plists
  are now valid XML, so macOS schedules load (issue 025). A host that wants the scheduled write
  re-runs `install --with-port-naming`.
- Config files follow the dotenv comment grammar: a ` #` after an unquoted value starts a
  comment; a quoted value keeps everything inside the quotes and drops what follows them. A
  value that held a bare `#` without a preceding space is unchanged.
- `unifi-mapper inventory …` honours the root `--config` and `UNIFI_CONFIG` (issue 043).
- `unifi-mapper capabilities` and `python -m unifi_mapper.analyze_network_capabilities` read the
  config the CLI would (`--config`, `UNIFI_CONFIG`, then the search) and run behind the read-only
  guard; both used to read a fixed `~/.config/unifi_management_cli/prod.env` whatever was given.
- `diagnose all` names the MCP tool behind each check and exits 2 on a failed check as before;
  its fifteen checks are the shared `diagnostics/run_all.py` table.
- `unifi-network-toolkit` and `python -m unifi_mapper.cli` honour `UNIFI_CONFIG` and the same XDG
  search as `unifi-mapper`; the toolkit's `--config` default was a hard-coded `prod.env` path.
- `inventory update-firmware` previews by default and triggers the upgrades only with `--apply`,
  after the confirmation that `--force` skips, like every other writer. `--dry-run` is still
  accepted and means the default; both flags together exit 2; `--force` on its own previews and
  says so. A script that upgraded with `--force` must now pass `--apply --force` (issue 077).
- `radio optimize` no longer moves one hard-coded AP name off channel 36. Channel moves are a
  site setting: `UNIFI_RADIO_CHANNEL_MOVES=NAME=FROM>TO,…`; unset means no moves (issue 046).
- The Protect monitor follows every camera unless `PROTECT_CAMERA_HOSTS` (or `--camera-host`)
  names the host prefixes to keep; it used to follow one hard-coded subnet. Third-party cameras
  are followed either way (issue 046).
- The topology report and HTML diagram group devices by generic room words only; a site adds its
  own words with `UNIFI_LOCATION_KEYWORDS`. Example addresses and names in help text, descriptions
  and docstrings are documentation values (issue 046).
- The read-only guard refuses a raw request path that starts with `//` (issue 029).
- The coverage floor is 60 (measured 64%), so the pre-push hook can pass (issue 065).

### Added

- `--version` on every entry point; `unifi-mapper version` prints the installed version.
- A missing default config lists every path that was searched and the keys a minimal file needs.
- GitHub Actions CI running the pre-push gates; `CONTRIBUTING.md`; `SECURITY.md`.
- A parity gate between the CLI and the MCP server (`tests/test_surface_parity.py`): every
  manifest entry names its `unifi-mapper` command (`cli:`) or says why there is none
  (`cli_gap:`), and every command has a tool or a categorised reason in
  `src/unifi_mapper/mcp/parity.py`; the gate pins how many gaps are "not yet built" (issue 078).
- Nine MCP tools for read-only commands that had none: `get_device_inventory` (`inventory
  list`), `get_firmware_drift` (`inventory firmware-skew`, issue 017), `get_port_naming_capabilities`
  (`capabilities`), `run_all_diagnostics` (`diagnose all`), `detect_config_drift`,
  `compare_link_errors`, `analyze_client_roaming`, `scan_neighbour_aps` and
  `compare_neighbour_baseline` (the compare halves of `analyze config-drift`, `link-errors`,
  `roaming` and `neighbours`; the snapshot writers stay on the CLI, and a baseline path must be
  absolute and end in `.json`). 96 tools, 82 on the direct surface.
- `inventory firmware-skew --json` (the `get_firmware_drift` shape), `capabilities --json` and
  `diagnose all --json`.
- Eighteen `unifi-mapper` commands for the twenty MCP tools that had none, each with `--json`
  equal to the tool's result: `analyze ip-conflicts`, `storms`, `mac-table`, `qos`,
  `capacity`, `lags` and `foreign-bridges`; `diagnose security`, `vlans`, `freshness`
  (`--sample` for the two-read check), `performance`, `connectivity`, `firewall SRC DST`,
  `path SRC DST` (`--analyze` for the path analysis; from controller data, no packet sent) and
  `client-path CLIENT`; `stp path-costs`; `find ip` and `find mac`. Both sides of the parity
  gate now report no gap that is not a recorded decision. 98 commands in all.

### Fixed

- `security_audit` (and the new `diagnose security`) read the rogue-AP list from
  `rest/rogueap`, which UniFi Network answers with `400 api.err.InvalidObject`, so every call
  failed with `API_ERROR`. It reads the passive `stat/rogueap` list now, and tells a rogue
  from a neighbour: a rogue broadcasts one of this site's SSIDs from hardware that is not ours
  (critical), is flagged by the controller as seen on the wired network (high), or is UniFi
  hardware not adopted here heard at -60 dBm or louder (medium); every other neighbour is
  counted in `neighbour_aps`, the three loudest listed for context, none a risk or an action
  (issue 079). On a home site this took the report from 619 critical "rogues" and 195 MAC
  anomalies to none and 11.

### Removed

- Internal process documents (`.github/agents/`, `.github/prompts/`, `docs/solutions/`) from the
  public tree. The README's reference material moved to `docs/reference/cli.md`,
  `docs/guides/protect-and-axis.md` and `docs/architecture/README.md`.

## [0.2.0] - 2026-10-07

This release carries the diagnostics prototype of June and July 2026 onto the main line:
read-only MCP tools and CLI diagnostics (gateway probes, client connectivity,
AP health, the per-VLAN traffic collector, WAN history), the default-on MCP call log, and the
docs hygiene pass. See `docs/issues/059` and `060` for what was and was not ported.
