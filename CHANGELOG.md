# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The current release is 0.2.0; only the latest release is supported.

## [Unreleased]

Nothing yet.

## [0.3.0] - 2026-10-13

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

### Breaking

- `discover --format` defaults to `UNIFI_DEFAULT_FORMAT` (then `png`) instead of always `png`,
  and `discover` output paths honour `UNIFI_OUTPUT_DIR` and `UNIFI_DIAGRAM_DIR`;
  `UNIFI_MAX_RETRIES` and `UNIFI_RETRY_DELAY` reach every API client the CLIs build. A config
  file that already set these values will see them applied for the first time (issue 042).
- `configure_logging` was removed from `unifi_mapper.core` and `unifi_mapper.core.utils`, and
  `UNIFI_MAPPER_DEBUG` is no longer read; nothing in the project called it (issue 045).
- `diagnose vlans` / `diagnose_vlans` audits every switch port (not only the overridden ones),
  reports profile names instead of raw `portconf_id`s, judges a trunk from the resolved profile's
  `forward` and `tagged_vlan_mgmt`, and lists a trunk's tagged VLANs; `analyze mac-table` tells a
  trunk from an access port the same way. Expect more port rows, names in the consistency check
  and real trunk-coverage verdicts; both read `rest/portconf` now (issue 030).
- `vlan-traffic report`: two samples further apart than the gap threshold plus the sampling grace
  are a gap, not a rate, in every pairing, so one fresh sample after a sampler outage no longer
  reports days of traffic as the current rate; `valid_sample_pct` drops for such a sample and the
  raw-tier caveat says so (issue 072).
- Network and Protect MCP tools raise on failure (`CONTROLLER_UNREACHABLE`,
  `AUTHENTICATION_FAILED`, `API_ERROR`, `NO_DATA`, or `TOOL_FAILED`) instead of returning
  `{"error": ...}` inside an `ok: true` result; a client that read the error dict must read
  `isError` and the error code instead (issue 011).
- Every MCP tool call has a 270 s deadline by default (`UNIFI_MCP_TOOL_TIMEOUT`, 5-3600 s,
  `[TIMEOUT]`), chosen so the server's code reaches a client whose own limit is 300 s, as the
  guide's snippets are; set the variable higher for a slower controller (issue 012).
- `diagnose ap-health --essid <name>` exits 2 after the discovery read when the target's 2.4 GHz
  radio does not carry that SSID (it used to measure the busiest VAP under that name); an AP
  without the tracked SSID shows `no rate (SSID not present)`, the JSON rows gain `retry_note`,
  and the ping note appears only with `--ping-clients` (issue 076).
- `diagnose latency-matrix`: a `ping` the gateway could not run is reported as that target's
  error instead of 100% loss; `LatencyResult.packet_loss` may be `null`, and `LatencyResult.error`
  and `LatencyMatrixReport.targets_failed` are new fields (issue 076).
- `diagnose wan --record` and `analyze link-errors --record` wait at most 5 s for the history
  lock, then exit 1 (`diagnose wan --record` exited 0 with a warning before) naming the lock file
  and who may hold it; histories and locks are `0o600` and the default state directory `0o700` on
  every run, a file owned by another user is refused, and a `--history` path's existing directory
  is left alone. A schedule that relied on exit 0 after a failed record should read the exit
  status (issue 076).
- MCP call log: after a lock timeout the log skips the lock for 30 s and the next successful
  write starts with a `{"kind": "lock_timeout", "dropped": N}` line; writes use a dedicated
  4-thread pool so a failing log can never slow every call (issue 076).
- `unifi-mapper` (and every CLI sharing its search) resolves the config file in the MCP server's
  order: `UNIFI_CONFIG`; `$XDG_CONFIG_HOME/unifi_management_cli/{prod,default}.env` (absolute
  values only); `~/.config/unifi_management_cli/{prod,default}.env`; the legacy
  `~/.config/unifi_network_mapper/prod.env`. `./.env` is consulted last and only when nothing
  else exists, with a deprecation warning on stderr; it is removed in 0.4.0, so name it with
  `--config ./.env` or `UNIFI_CONFIG=./.env` (issue 048).
- Radio snapshots, the config-drift baseline, the roaming history and the neighbour baseline
  default to `$XDG_STATE_HOME/unifi_mapper/` (`~/.local/state/unifi_mapper/`) instead of
  `./reports/`. Files already under `./reports/` are not moved or read: pass the old path once
  with `--snapshot`, `--baseline` or `--history`, or move the file (issue 010).
- The gateway SSH commands verify the gateway's host key against `~/.ssh/known_hosts` and
  refuse, before the password is sent, a key that is missing or has changed; the error names
  `user@host` and the one `ssh` command that records the key. Anyone who never ran `ssh` to the
  gateway from the same account must do so once. `UNIFI_SSH_KNOWN_HOSTS=off` disables the check
  with a warning on every run; any other value is rejected (issue 038).
- `security_audit` / `diagnose security` reports only what the controller can show: pending
  adoption, guest-network overstay and the issue-079 rogue classes. The vendor blacklist, the
  `unknown_devices` count and the randomised-MAC risk are gone (a randomised MAC is noted as
  information), MAC-similarity anomalies are computed among clients only, and the report
  carries a `limitations` block saying its findings are controller-derived signals, not proof of
  authorisation or of absence of compromise; a check that could not run says "not assessed"
  (issue 080).

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
- `UniFiNetworkClient` tries the documented Integration API base
  `/proxy/network/integration` first and falls back to the plural on a 404, as the port
  diagnostics do; this costs one `GET /v1/info` per connection, and
  `NetworkConfig.api_base_url` is the documented base (issue 003).
- `DeviceInfo.is_switch` / `is_router` / `is_access_point` test the reference's `switching`,
  `gateway` and `accessPoint` feature names instead of `SWITCH`/`ROUTER`/`ACCESS_POINT`; code that
  compared `features` to the upper-case names should use `feature_names` (issue 036).
- `get_acl_rules` output carries `metadata.origin` and `portFilter`; the always-empty top-level
  `origin` and `portsFilter` are gone (`ACLRule.origin` is a read-only property,
  `ACLTrafficFilter.ports_filter` is `port_filter`). `DNSRecordType` members are `A_RECORD` to
  `SRV_RECORD` plus `FORWARD_DOMAIN`, the values the API sends (issue 036).
- Without Graphviz's `dot`, `discover` and `diagram` write a placeholder PNG/SVG with a warning
  naming the install command and still write the report, exiting 0; the leftover DOT source is
  removed. A script that relied on exit 1 to detect a missing Graphviz should check the warning or
  install Graphviz (issue 075).
- The MQTT bridge's `ImportError` hint reads `uv sync --extra mqtt` (was `uv add aiomqtt`)
  (issue 074).
- `inspect_switch_port` uses the same guarded `_readonly_sync_client()` path as the other sync
  port-diagnostics tools; a login that raises is `CONTROLLER_UNREACHABLE` rather than
  `TOOL_FAILED` (issue 021, first step).
- `search_tools` summary results carry `mutates: true` for the three mutating tools, and the
  redacted-failure helper and the 2,000-character error cap live once in `mcp/failure_text.py`
  (issues 022, 067).
- The `analyze`, `stp`, `radio`, `ports` and `diagnose` read commands that moved onto the shared
  read-only runner print a controller failure as `❌ Error: ...` on stderr (was stdout, same
  text) and exit 1; a script that grepped stdout for it should read stderr (issue 064).
- The MCP `snapshot_radio_config` tool returns the absolute path it wrote (`file`) and the exact
  `unifi-mapper radio restore --snapshot <path>` command (`restore_command`, shell-quoted);
  restore still previews by default. The radio, roaming, config-drift and neighbour path options
  default to `None` and name the XDG default in `--help` (issue 010).
- `unifi-mcp --check` and the readiness report carry a `derived` list per family
  (`host: derived from UNIFI_URL`, `site id: resolved at first call`,
  `key: console token (same origin)`) and stay offline; the Network API client refuses
  redirects (issue 037).

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
- `INTEGRATION_BASES` in `network/config.py` and `UniFiNetworkClient.base_path_used` (issue 003);
  `DeviceInterfaces`, `DevicePortInterface`, `DeviceInfo.feature_names`, `ACLRuleMetadata` and
  `ACLRuleOrigin`, exported from `unifi_mapper.network` (issue 036).
- `discover --format dot` writes the Graphviz source and `--format mermaid` writes a Mermaid
  `graph TB` of the topology; both were one-line placeholders (issue 044).
- Optional extra `mqtt` (`aiomqtt>=2,<3`) for the Home Assistant MQTT bridge:
  `uv sync --extra mqtt` (issue 074).
- `vlan_traffic_store.dirty_buckets` (created on the next writable open of an existing store)
  and `max_measured_interval`; `monitor_lags_from_data`, `diagnose_vlans_from_data`,
  `is_trunk_profile` and `gateway_probe.ping_over` as pure, shared seams
  (issues 061, 071, 072, 030, 073).
- `tests/mcp/test_docstring_tool_names.py`: a new phantom tool name in any docstring or string
  constant fails the suite (issue 028).
- Docs guards: backticked CamelCase names and Mermaid classDiagram classes must exist under
  `src/` or in `KNOWN_EXTERNAL_TYPES` (issue 052); a free-text tool count must be the registry
  total unless its sentence names a category, surface or kind (issue 053); an environment
  variable counts as read only at a real read, never in a message (issue 055); the MCP-name
  check knows only bindings a doc may describe, not locals or keyword arguments (issue 056).
  Privacy guard: public IPv4 addresses from address fields and link-local IPv6 addresses in the
  local captures are identifiers tests and scripts must not hold (issue 054).

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
- `UniFiNetworkClient.get_device_statistics` reads `/statistics/latest` and `execute_port_action`
  posts under `/interfaces/ports/{portIdx}/actions`, the reference's paths; the old statistics
  path answered 404 on Network 10.6 (issue 035).
- `DeviceInfo` validates what Network 10.6 sends: `state` accepts `ONLINE`, `OFFLINE`,
  `PENDING_ADOPTION` and `UPDATING` and keeps an unknown state as sent; `features` and
  `interfaces` take the list and the object shape, so `list_devices` and `get_device` no longer
  fail. `ACLTrafficFilter` reads `portFilter` and `ACLRule` reads `metadata.origin`, so ACL port
  filters and the user/system split are no longer silently empty; `DNSPolicyManager` counts the
  `*_RECORD` types instead of filing every policy under `other_records` (issue 036).
- `unifi-mapper install-completions` installs what its help offers: `all` installs bash and zsh,
  `fish` is refused with a pointer to `--install-completion`, and a failed installation exits 1
  instead of 0 (issue 047).
- `monitor_lags` / `analyze lags` find LAGs on current switch firmware (`link_aggregation_groups`,
  the master port's `op_mode: 'aggregate'` override and `lacp_state`), still read legacy
  `port_aggregates`, surface `partner_system_id`, and never read a masked subordinate's cosmetic
  `up: false` as a failed member; `find_lag_candidates` no longer proposes a LAG over one that
  exists (issue 061).
- `vlan-traffic sample`: a second network without a VLAN ID is listed under unresolved instead
  of overwriting the first one's row (issue 070).
- `vlan-traffic rollup` recomputes every hour a sample was written into since the last run, so a
  sample written late still reaches the monthly and yearly reports; raw samples and hourly rows
  are pruned on hour and day boundaries only (issue 071).
- `search_tools` matches every word of a multi-word query against name, description and tags,
  matches `category` case-insensitively, and ranks results by where the words hit (issue 022).
- `python -m unifi_mapper.mcp.server` no longer prints runpy's "found in sys.modules"
  RuntimeWarning (issue 020, first item).
- Tool docstrings and `path_analysis` recommendations name registered tools
  (`analyze_link_quality`, `performance_analysis`, `get_switch_ports`, `discover_stp_topology`,
  `inspect_switch_port`, `security_audit`, `audit_uplink_transparency`, `audit_vlan_coverage`);
  three `CONTROLLER_UNREACHABLE` hints naming controller tools were dropped (issue 028).
- Every CLI read command runs behind the read-only transport: the 39 direct `asyncio.run` reads
  go through `_run_analysis`, and only the seven write paths keep their own client; a
  write-refusal test pins 32 command invocations on the shared mock transport (issue 064).
- `stp optimize` exits 0 when the apply confirmation is declined instead of printing "Error:"
  and exiting 1 (issue 064).
- Docs: Diagnostics has 12 MCP tools, not 11; the direct catalog is 82 tools, not 73; the
  registry holds 96 tools, not 87 (issue 053).
- `stp audit-priorities` / `audit_stp_priorities` warn on a lowest-priority tie that includes a
  core-class switch, naming the switches that are not core-class; a core switch tied with an
  access switch went unwarned (issue 076).
- `vlan-traffic report --help`, `get_vlan_traffic_report`'s description and the daily caveat no
  longer say peaks are smoothed: each tier's peak is the largest sample rate in its window
  (issue 076).
- Keys and free text spelt `pre-shared`, `pre_shared` or `pre shared` are stripped and masked
  like `preshared` (issue 076).
- `vlan-traffic sample` on a gateway without `br*` interfaces ends as "Nothing was stored"
  instead of a message about a bridge line without two integer counters (issue 076).
- Two concurrent call-log write failures warn once, not twice, and a failure on a file other than
  the log names that file; `get_wan_speedtest_history`'s description names
  `unifi-mapper diagnose wan-history` (issue 076).
- A relative `XDG_CONFIG_HOME` is ignored by the CLI, the MCP server, `scripts/site_targets.py`
  and `scripts/unifi-mcp-launch.sh`, as the XDG specification requires, so no search reads a
  file under the working directory (issue 068).
- The six `network_api` tools work with only the controller's config: the host is derived from
  `UNIFI_URL`, the site id from `UNIFI_SITE` at the first call (one `GET /v1/sites`, cached,
  exactly one match required), and `UNIFI_CONSOLE_API_TOKEN` stands in for the key when the
  network host is the same origin as `UNIFI_URL`; explicit `UNIFI_NETWORK_*` keys always win,
  and a derived host inherits `UNIFI_VERIFY_SSL` so the borrowed token never travels over a
  session the controller family would verify (issue 037).
- `scripts/onvif_stream.py test-rtsp` probes each stream with one RTSP `DESCRIBE` from this
  process (Digest, or Basic when that is all the camera offers) instead of running ffprobe with
  the authenticated URI on its command line, so the ONVIF password no longer appears in the
  process list; an `OK` line means the camera accepted the account and returned the stream's SDP
  metadata, not that the stream plays (issue 057).

### Removed

- Internal process documents (`.github/agents/`, `.github/prompts/`, `docs/solutions/`) from the
  public tree. The README's reference material moved to `docs/reference/cli.md`,
  `docs/guides/protect-and-axis.md` and `docs/architecture/README.md`.

## [0.2.0] - 2026-10-07

This release carries the diagnostics prototype of June and July 2026 onto the main line:
read-only MCP tools and CLI diagnostics (gateway probes, client connectivity,
AP health, the per-VLAN traffic collector, WAN history), the default-on MCP call log, and the
docs hygiene pass. See `docs/issues/059` and `060` for what was and was not ported.
