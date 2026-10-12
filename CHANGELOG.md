# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The current release is 0.2.0; only the latest release is supported.

## [Unreleased]

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

### Removed

- Internal process documents (`.github/agents/`, `.github/prompts/`, `docs/solutions/`) from the
  public tree. The README's reference material moved to `docs/reference/cli.md`,
  `docs/guides/protect-and-axis.md` and `docs/architecture/README.md`.

## [0.2.0] - 2026-10-07

This release carries the diagnostics prototype of June and July 2026 onto the main line:
read-only MCP tools and CLI diagnostics (gateway probes, client connectivity,
AP health, the per-VLAN traffic collector, WAN history), the default-on MCP call log, and the
docs hygiene pass. See `docs/issues/059` and `060` for what was and was not ported.
