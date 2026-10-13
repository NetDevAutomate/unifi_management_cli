# `unifi-mapper` command reference

Every command of the main CLI, by group, with the examples that used to live in the README. The
groups and the exact command set are checked against the Typer app by
`tests/test_cli_documentation.py`; `unifi-mapper --help` and `unifi-mapper <group> --help` are
always the authority for options. Writes to the controller preview by default and need
`--apply` or `--no-dry-run`; everything else only reads.


## Port Mapping

```bash
# Discover the network and generate reports; port names are only previewed
unifi-mapper --connected-devices

# Write the proposed port names to the controller (explicit opt-in)
unifi-mapper --connected-devices --apply

# Write port name updates and verify that they persisted
unifi-mapper --verify-updates --connected-devices --apply

# Preview with the smart (device-aware) mapper; --dry-run is the default and still accepted
unifi-mapper --dry-run --verify-updates
```

`discover` and its root shortcuts (`--connected-devices`, `--verify-updates`, `--dry-run`)
preview by default, like `ports refresh`: only `--apply` writes port names. Passing both
`--apply` and `--dry-run` is an error (exit 2).

Before the `discover` subcommand, the root `--dry-run`, `--connected-devices` and
`--verify-updates` are passed on to it, so `unifi-mapper --connected-devices discover`
includes connected devices and `unifi-mapper --dry-run discover --apply` is an error. Before
any other subcommand they exit 2, as a root `--apply` does before any subcommand: give a
subcommand its own flags after it (`unifi-mapper discover --apply`,
`unifi-mapper ports refresh --apply`).

## Network Toolkit

```bash
# Network health diagnostics
unifi-network-toolkit diagnose network-health

# Link quality analysis
unifi-network-toolkit analyze link-quality

# Device discovery
unifi-network-toolkit find device "Office"
unifi-network-toolkit find ip 192.0.2.100
```

## STP Optimization

```bash
# Analyze current STP topology
unifi-mapper stp analyze

# One-shot audit: every switch's current vs recommended priority (read-only)
unifi-mapper stp audit-priorities
unifi-mapper stp audit-priorities --device "Switch A" --json

# Preview optimal priority changes and write a reversible plan
unifi-mapper stp optimize --dry-run
unifi-mapper stp optimize --plan reports/stp-plan.json

# Apply or roll back an approved plan in a maintenance window. Both only preview unless
# --no-dry-run is given, and then ask for confirmation unless --force is given
unifi-mapper stp apply --plan reports/stp-plan.json
unifi-mapper stp apply --plan reports/stp-plan.json --no-dry-run
unifi-mapper stp rollback reports/stp-plan.json --no-dry-run

# Validate 10G readiness, guard placement, drift, and snapshots
unifi-mapper stp validate-10g --planned-switches 2
unifi-mapper stp guard
unifi-mapper stp drift --intent stp_intent.yaml
unifi-mapper stp snapshot --output reports/stp-baseline.json
unifi-mapper stp diff reports/stp-baseline.json

# Generate markdown report
unifi-mapper stp report -o stp-report.md
```

The gateway (`udm`/`udmpro`) stays in the topology so the switches can be tiered by their
distance to it, but its bridge runs with STP disabled: `stp optimize` and `stp report` never
propose a priority for it or name it as the root, and print "Skipped <gateway>: gateway; its STP
priority is not changed" instead. A bridge that takes no part in the election would ignore a
priority written to it, so a plan built around it as the root would leave the real root to be
decided by MAC address. `stp audit-priorities` lists it under "Skipped" for the same reason, and
always tiers the whole fleet: `--device` narrows the rows and the verdict to that switch, and
prints the fleet's verdict after it (`fleet_compliant` and `fleet_summary` in `--json`).

## Device Inventory

```bash
# List devices with upgrade information
unifi-mapper inventory list --filter switch --show-upgrade

# Check for firmware updates
unifi-mapper inventory check-updates

# Preview the upgrades for the switches; add --apply to trigger them (devices reboot)
unifi-mapper inventory update-firmware --filter switch
```

## Diagnostics

```bash
# Run all 15 diagnostic checks with a pass/warn/fail summary
unifi-mapper diagnose all

# Overall health on its own: 100 when every device is online with no issue; offline devices
# cost up to 30 points, and an uplink counts as down only when its state says so
unifi-mapper diagnose health --detailed

# Gateway latency matrix — SSH to UDM, ping all device/client IPs
unifi-mapper diagnose latency-matrix
unifi-mapper diagnose latency-matrix --devices-only --count 5 --timeout 2

# Bandwidth test via iperf3 (requires iperf3 -s on target)
unifi-mapper diagnose bandwidth 192.0.2.50 --bidir --duration 10
unifi-mapper diagnose bandwidth 192.0.2.50 --reverse --parallel 4

# Live probes run on the gateway over SSH (CLI only); a name resolves through the
# read-only controller client, --vlan to the interface whose address is in its subnet.
# gateway http runs its URL as given on the gateway's command line: put no secret in it
unifi-mapper gateway ping "Phone A" --count 5
unifi-mapper gateway traceroute 203.0.113.53 --max-hops 15
unifi-mapper gateway dns www.example.com --server 203.0.113.53
unifi-mapper gateway http http://www.example.com/ --vlan 30
unifi-mapper gateway flows --ip 192.0.2.50 --state unreplied

# One device's CPU, memory, load, uptime, radios and per-VAP TX counters
unifi-mapper diagnose device-stats "AP 1" --json

# WAN and internet health, and the controller's last scheduled speedtest (never starts one)
unifi-mapper diagnose wan --json
unifi-mapper diagnose wan --record          # also append that result to the history
unifi-mapper diagnose wan-history --limit 24

# Every AP's TX retry rate over 30 s (two device reads, reset-aware; at most 240 s)
unifi-mapper diagnose ap-retries --radio na --interval 30 --threshold 10

# One AP's 2.4 GHz counters every 60 s, 6 times, beside a known-good AP, as a ticket report
# (CLI only; Ctrl-C writes the samples so far and exits 130; --ping-clients adds SSH pings)
unifi-mapper diagnose ap-health "AP 1" --reference "AP 2" --essid "SSID A" --output ap-1.md

# "My phone says No Internet": lookup, AP counters, then ping, DNS, HTTP from its VLAN and
# its conntrack flows from the gateway over SSH, capped at 120 s (exit 1 on a fault)
unifi-mapper diagnose client-connectivity "Phone A"

# Per-VLAN traffic: sample the gateway's bridge counters over SSH into a local store (run it
# every minute or so yourself; no schedule is published until issue 038 is decided), then
# roll up (hourly, say) and report offline
unifi-mapper vlan-traffic sample
unifi-mapper vlan-traffic rollup
unifi-mapper vlan-traffic report "1w"
unifi-mapper vlan-traffic coverage --json

# The controller's raw config objects of one kind, secrets removed (paths listed in --json)
unifi-mapper controller config --json wlanconf --name "SSID A"

# Config objects created in the last week, newest first (creation only, not edits)
unifi-mapper controller config-changes --since-hours 168 --kind wlanconf --kind networkconf

# Check a downloaded config backup offline: does it decrypt, and what does it hold?
unifi-mapper backup verify ~/Downloads/network-backup.unf

# Site-wide events, alarms and system-log entries from the last hour (admin edits included)
unifi-mapper controller events --since-hours 1 --category security --max-events 50
```

`diagnose device-stats`, `diagnose ap-retries` and the `controller` commands read the
controller through the same read-only transport as the MCP server, so a write would be refused
before it left the machine. Secret values never reach their output: `controller config --json`
lists what it removed by key path in `sanitised_paths`, never by value. `controller
config-changes` dates each object by the creation time its ID records, so an edit to an older
object does not appear; `controller events` shows the edits, in the admin-activity system log.

`diagnose ap-health` and `diagnose client-connectivity` are CLI only (no MCP tool: a run is
too long for one MCP call, and the probes use SSH). `ap-health` takes 1-60 samples 30-600 s
apart (up to about 10 h; it prints the expected duration first), reports a retry rate only
over a real interval, records a sample whose read times out or fails as missing, and has no
power-cycle step; without `--essid` it tracks the busiest 2.4 GHz SSID. It checks `--output`
before the first sample and writes it after printing the report; Ctrl-C (exit 130), or a
failure that ends the run (exit 1), still prints and writes the samples taken.
`client-connectivity` bounds every layer and stops at 120 s, reporting the layers it had no
time for; a layer that fails is a finding, and the others still run; a layer that can't test
the client's own path (no address, an address as the probe URL's host, an unknown client
network for the HTTP probe) is not run, so the verdict is inconclusive rather than a pass.

`vlan-traffic sample` is the only `vlan-traffic` command that reaches anything: it reads the
controller's network list (read-only) and runs one fixed script on the gateway over SSH, then
stores a row per VLAN in `$XDG_STATE_HOME/unifi_mapper/vlan-traffic.sqlite3` (never the working
directory; `--db` names another store). A script that fails (a bridge counter it could not
read included: nothing is stored, never a partial sample), and a run that stores nothing
because no VLAN matched a gateway interface with byte counters, exit 1, so a schedule of your
own notices. `rollup`, `report` and `coverage` work on the store
alone. `report now`, `1d` and `1w` read the raw samples (kept 8 days); `1m` reads hourly rows
and `1y` daily rows, which `rollup` writes for every complete hour and day (run it hourly, say;
each run also recomputes the newest two hours and the newest day, so a sample written late
still counts if a run comes less than two hours after its hour is complete; a later one stays
in the raw samples only, [issue 071](../issues/071-late-vlan-samples-never-reach-the-rollups.md)).
As ported from the prototype, `1w` was always empty and `1m` and `1y` left out the newest 8 and about
61 days, because the prototype rolled an hour only once it was 8 days old ([issue
069](../issues/069-vlan-reports-read-tiers-without-recent-data.md)). The MCP tools
`get_vlan_traffic_report` and `list_vlan_traffic_periods` read the same
store and need no credentials; nothing over MCP starts a sample. A report of a store a crashed
sample left unfinished asks for `vlan-traffic rollup`, which repairs it.
`backup verify` contacts nothing: it decrypts the backup with the controller's fixed backup key
and reports which collections it holds and how many documents each has, never their contents
(a collection outside the known UniFi set is counted as `other`, and a version that is not a
version number is shown as `<unrecognised>`, so no string from the file is echoed unchecked).
A truncated download, or a database holding a document that does not decode, is reported as
not valid (exit 1), as is a database of more than 64 gzip members (a real backup's is one).

`diagnose all` runs 15 checks: link quality, capacity planning, port profiles, MTU
consistency, SFP diagnostics, radio optimisation, firmware skew, DHCP pools, PoE budget,
client density, uplink redundancy, uplink VLAN transparency, device power budget, foreign
bridges and telemetry freshness.

The latency matrix, the bandwidth test, the `gateway` probes, `diagnose client-connectivity`,
`vlan-traffic sample` and
`diagnose ap-health --ping-clients` SSH to the gateway, so they
need SSH enabled in UniFi OS (Settings > Control Plane > Console) and `UNIFI_SSH_PASSWORD` in
your config, plus `UNIFI_SSH_USERNAME` if the SSH user isn't `root`. Without
`UNIFI_SSH_PASSWORD` each exits 1 before connecting to anything, and prints this on stderr
(the first line, once per command, comes before every SSH command runs; see
[issue 038](../issues/038-ssh-host-key-verification-disabled.md)):

```text
⚠ This command runs on the gateway over SSH as the SSH user, and the gateway's host key is not verified (issue 038).
❌ [CONFIG_MISSING] UNIFI_SSH_PASSWORD is not set. The gateway SSH login has its own password; UNIFI_PASSWORD (the UniFi OS login) is never sent over SSH
💡 Suggestion: Enable SSH in UniFi OS (Settings > Control Plane > Console) and set UNIFI_SSH_PASSWORD to the SSH password set there; set UNIFI_SSH_USERNAME as well if the SSH user is not root
```

Any other failure of these commands is also a line on stderr, with secrets redacted.

`UNIFI_PASSWORD`, the UniFi OS login, is never sent over SSH. Every address and number is
checked before it reaches the gateway's command line, which is shell-quoted as well:
`diagnose bandwidth` refuses a target that isn't an IP address (an IPv6 zone id included),
and the latency matrix skips such a target and says why. The SSH session doesn't verify the
gateway's host key yet (`known_hosts=None`,
[issue 038](../issues/038-ssh-host-key-verification-disabled.md)), so run these only on a
network you trust.

## Radio Management

```bash
# Snapshot current radio configuration (auto-saved before any changes)
unifi-mapper radio snapshot

# Preview optimised radio settings
unifi-mapper radio optimize

# Apply optimised radio settings (auto-snapshots first)
unifi-mapper radio optimize --apply

# Restore previous radio configuration
unifi-mapper radio restore --apply

# Auto-channel optimiser — utilization-weighted channel assignment
unifi-mapper radio auto-channel --band both --apply
unifi-mapper radio auto-channel --band 5ghz --report radio-report.md

# Generate radio optimisation report
unifi-mapper radio report -o radio-report.md
```

The auto-channel optimiser scores 5 GHz channels by measured utilization + DFS penalty + neighbour-AP congestion (RSSI-weighted, CCA-aligned), and distributes 2.4 GHz across channels 1/6/13 accounting for both own-AP utilization and adjacent-channel neighbour interference.

5 GHz assignment works over whole 80 MHz blocks (36-48, 52-64, 100-112, 116-128, 132-144, 149-161) rather than primary channels, since two APs sharing a block occupy identical spectrum. Band is derived from the controller's radio id, so tri-band APs (U7 series) report 5 GHz and 6 GHz separately.

## Port Labels

```bash
# Preview port label changes derived from LLDP + wired clients
unifi-mapper ports refresh

# Apply
unifi-mapper ports refresh --apply

# Inspect a single port in depth (link state, LLDP peer, client identity, counters)
unifi-mapper ports inspect "Access USW Flex 2.5G 5" 2
unifi-mapper ports inspect "Access USW Flex 2.5G 5" 2 --json
```

`ports inspect` resolves the switch by name, model, IP or MAC and reports everything the
controller holds about one port: link state, the effective port profile and which VLANs it
actually forwards, the native network with its subnet and DHCP pool, the connected device,
an addressing verdict, the LLDP neighbour, the switch's remembered `last_connection`, port
config, PoE and error counters. It warns when cached controller state disagrees with ground
truth, which is the usual reason a port looks down while still carrying traffic.

The connected device is resolved whether or not it is UniFi gear. Adopted devices are named
from the device registry; third-party hosts are reported with their OUI vendor and the
controller's fingerprint model guess, shown alongside its confidence score because that
guess is regularly wrong. LLDP peers are resolved via the same registry, so switches and
access points are named even though they send no `system_name`.

The addressing verdict is what makes an L3-only fault legible:

| Verdict | Meaning |
|---------|---------|
| `leased` | A DHCP lease expiry exists — DHCP is working on this port |
| `static` | An address with no lease, configured on the host itself |
| `no_address` | Client present but unaddressed — suspect the VLAN path or DHCP, not the cable |
| `no_client` | Nothing reporting on the port |

A `no_address` verdict points at the uplink path: check that the native VLAN reaches the
gateway on every hop, and that the switch has been provisioned since the VLAN was created.
The tool also flags a DHCP pool that spans the gateway's own address, which can hand a
client a conflicting address.

Resolves each connected managed switch port, including the integrated LAN/SFP ports on UCG/UDM gateways, to either its LLDP peer or its wired client, and rewrites the label to match. LLDP peers are resolved via the adopted-device registry (`chassis_id`), so access points resolve correctly even though they do not send `system_name` — this is what recovers factory labels such as `PoE Out + Data` on PoE passthrough switches.

Down ports are reverted to their default (`Port N`): a label naming hardware that is no longer plugged in is misinformation. A disconnected port already carrying a factory placeholder such as `PoE Out + Data` or `SFP 1` is left alone, since those say what the port physically is. Four guards prevent bad rewrites:

| Guard | Prevents |
|-------|----------|
| Weak-label protection | `Google Streamer 4K` → `02:00:00:00:00:01` when a client stops reporting a hostname |
| Name ranking | A raw MAC representing a multi-client port instead of `Media-Player +2` |
| Cosmetic-change skip | Churn such as `AI-Port` → `AI Port` |
| `+N` flap suppression | A device that comes and goes oscillating the multi-client counter every run |

Labels are written through `port_overrides`, merged per port, so `poe_mode`, `port_profile` and speed overrides are preserved. Re-running after an apply reports no changes needed.

## Port Diagnostics (read-only)

```bash
# Every port on a switch: speed, duplex, autoneg, profile, LLDP peer, clients, errors
unifi-mapper ports list "Office Flex XG"

# Key-by-key diff of two port profiles, plus every port that uses each one
unifi-mapper ports profile-diff "Access 10G" "Access Auto"

# Where does the controller place a client? Current, offline and historical records
unifi-mapper ports client aa:bb:cc:dd:ee:ff --switch "Office Flex XG" --port 5

# Events, alarms, system log and admin audit for a switch, a port, or a client
unifi-mapper ports events "Office Flex XG" 5 --client aa:bb:cc:dd:ee:ff --since-days 365

# Error counter rates for one port, sampled an inform interval apart, compared with the
# baselines and the recorded counter history (see "Link error baselines and history")
unifi-mapper ports counters "Office Flex XG" 5 --samples 3 --interval 100

# One JSON evidence bundle with all of the above, for a vendor ticket
unifi-mapper ports diagnose "Office Flex XG" 5 --compare-profile "Access 10G" --compare-profile "Access Auto"
```

Every diagnostic command accepts `--json`, resolves the switch by exact name or MAC
before trying a partial name (so `"USW Flex XG"` is not confused with
`"Core USW Flex XG 10G"`), and takes any switch and any port index.

They are read-only by construction, not by convention: after login the client's HTTP
session is wrapped by a transport guard that allows `GET` (except `cmd/` and `upd/`
paths) and `POST` only to the `stat/event`, `list/alarm` and v2 `system-log` query
endpoints. Anything else, including every `PUT`/`DELETE`, is refused before it leaves
the machine. If the client has to log in again mid-run, the new session is wrapped too.
Secret fields (`x_*`, passwords, tokens, PSKs and pre-shared keys, passphrases, and keys
named `community` (SNMP), `syslog_key` or `lcm_tracker_seed` or ending in `_` and one of
them, such as `snmp_community`) are removed from every output, as is the `value` of a
`{key: <secret name>, value: …}` pair, and only their key paths
are listed in `sanitised_paths`. These commands read
configuration only from `--config` (or the default config path), never from a stray
`./.env` in the working directory; `ports inspect` follows the same rule.

`ports diagnose` writes `reports/port-diagnostics-<switch>-p<N>-<timestamp>.json` (or
`-o PATH`). The bundle includes `request_audit`, the method and path of every request
made after login (login requests themselves are not listed), as evidence that collection
never wrote to the controller. Undocumented values such as `speed_caps` are reported raw,
alongside the ports that share the same value, rather than decoded by guesswork. Counter
rates are withheld when the device did not inform between samples, since a stale snapshot
would read as zero errors.

## Fleet Audits (read-only)

```bash
# Port errors and drops (healthy ports too with --include-healthy)
unifi-mapper analyze link-quality --include-healthy

# Ports below their capability or forced into a speed trap; exits 2 on a CRITICAL or HIGH finding
unifi-mapper analyze link-speeds --switch "Core USW Flex XG 10G" --json

# Where each port profile is used, and which profiles are traps
unifi-mapper analyze port-profile-usage --hide-unused

# MTU on inter-switch links; uplinks that can't carry tagged VLANs
unifi-mapper analyze mtu
unifi-mapper analyze uplink-transparency

# PoE output per switch, and switch input power headroom
unifi-mapper analyze poe-budget --json
unifi-mapper analyze power-budget --warn-pct 80

# Single-uplink switches, clients per access point, DHCP pool use
unifi-mapper analyze uplink-redundancy
unifi-mapper analyze client-density
unifi-mapper analyze dhcp-pools
```

## Analysis Tools

```bash
# Link error rate tracking — set a baseline, then compare against it (read only)
unifi-mapper analyze link-errors --snapshot
unifi-mapper analyze link-errors --threshold 100

# Append one counter snapshot of every switch port to the history (the 5-minute cron task)
unifi-mapper analyze link-errors --record --retention-days 14


# Client roaming analysis — identify sticky clients and frequent roamers
unifi-mapper analyze roaming --snapshot
unifi-mapper analyze roaming

# Configuration drift detection — snapshot + diff against baseline
unifi-mapper analyze config-drift --snapshot
unifi-mapper analyze config-drift

# Neighbour AP scan — passive detection via stat/rogueap (always-fresh)
unifi-mapper analyze neighbours
unifi-mapper analyze neighbours --ap "Living Room"

# Neighbour trend tracking — baseline snapshot + diff over time
unifi-mapper analyze neighbours --snapshot
unifi-mapper analyze neighbours --diff
unifi-mapper analyze neighbours --diff --signal-delta 15
```

### Link error baselines and history

`analyze link-errors` keeps its files under the XDG state directory,
`${XDG_STATE_HOME:-~/.local/state}/unifi_mapper/`, never in the working directory:

| File | Written by | Purpose |
|---|---|---|
| `link-error-baseline.json` | `--snapshot` | The comparison baseline for a plain `analyze link-errors` |
| `port-counters.json` | `--snapshot` | The per-port counter baseline compared by `ports counters`, `ports diagnose` and the MCP port tools |
| `port-counter-history.jsonl` | `--record` | One JSON line per switch per run: every port's error, drop, CRC, link-down and byte counters |

- A plain run only reads. Nothing writes a file unless `--snapshot` or `--record` is given;
  the two can be combined and share one controller read.
- Recording never moves the baseline. Set the baseline deliberately with `--snapshot`
  after a known-good physical state.
- The history keeps `--retention-days` days (default 14, 1-365) and at most 64 MiB. So that a
  full file is not rewritten on every run, compaction runs only once the oldest line is a day
  past the window (it then drops every line older than the window), or once the file passes
  64 MiB (it then trims the oldest lines to 80% of the cap). The file therefore holds between
  N and N+1 days unless the size cap binds first; each `--record` prints the days it holds.
- `ports counters`, `ports diagnose`, `get_port_counter_rates` and `diagnose_switch_port`
  report `baselines.history` for the port: the recorded window, deltas, resets (reboots or
  cleared counters) and `first_increase`, the first sample in which each counter rose.
  They only read it; `ports counters --history PATH` reads another file.
- A baseline left at the old `./reports/link-error-baseline.json` is still read when the
  XDG one does not exist, and is reported as legacy.
- `scripts/unifi-cron.sh` runs `analyze link-errors --record` every 5 minutes (the task is
  still named `link-error-snapshot`).

## Command Reference

Every command on the `unifi-mapper` entry point. All are read-only unless noted.

| Command | Purpose |
|---------|---------|
| `discover` | Discover topology and propose port names with LLDP intelligence (preview by default; `--apply` writes) |
| `diagram` | Generate a topology diagram only, no port renaming |
| `verify` | Port name verification with ground truth checking |
| `capabilities` | Analyze device capabilities for port naming support |
| `version` | Show version information |
| `install-completions` | Install the manual bash/zsh completion scripts (`bash`, `zsh` or `all`; exits 1 on failure; fish: `--install-completion`) |
| `find device` | Find a device by name, IP or MAC |
| `find ip` | Where an IP address is: device or client, VLAN, lease and connection |
| `find mac` | Where a MAC address is: device, client or last known location |
| `ports refresh` | Rewrite port labels from LLDP and wired clients (writes with `--apply`) |
| `ports inspect` | Deep single-port inspection: VLAN, client, addressing, LLDP (`--json` for raw fields) |
| `ports list` | Every port on a switch: speed, negotiation, profile, LLDP peer, clients, errors |
| `ports profile-diff` | Key-by-key diff of two port profiles and the ports using each |
| `ports client` | Where the controller places a client, across current and offline client tables |
| `ports events` | Events, alarms, system log and admin audit for a device, port or client |
| `ports counters` | Sample a port's error counters: per-minute rates with a trust verdict, baselines and recorded history |
| `ports diagnose` | JSON evidence bundle for one port, with a request audit (for vendor tickets) |
| `analyze ip-conflicts` | Addresses claimed by more than one client, with each client's connection and VLAN |
| `analyze storms` | Broadcast and multicast storms and high-risk ports from per-port packet counters |
| `analyze mac-table` | Flapping MACs, access ports learning too many MACs, and MAC-learning alerts |
| `analyze qos` | QoS validation: DSCP and CoS trust, storm control, rate limits and the voice VLAN |
| `analyze capacity` | Port and PoE utilisation per switch, bottlenecks and whether expansion is due |
| `analyze lags` | Link aggregation health: members, LACP state, bandwidth and issues per LAG |
| `analyze foreign-bridges` | Third-party switches and bridges on the wired network, and their loop risk |
| `analyze link-quality` | Port statistics and error rates |
| `analyze link-errors` | Error-rate baseline (`--snapshot`), counter history (`--record`) and read-only delta comparison |
| `analyze port-profiles` | Validate STP Edge, BPDU Guard and uplink safety |
| `analyze vlan-coverage` | VLAN coverage on trunk and planned uplink ports |
| `analyze uplink-transparency` | Whether each elected uplink can carry tagged VLANs |
| `analyze mtu` | MTU consistency across inter-switch links |
| `analyze sfp` | SFP/SFP+ transceiver diagnostics |
| `analyze radio` | Wi-Fi channel and transmit power optimisation |
| `analyze lag-candidates` | Parallel links that may be LACP candidates |
| `analyze power-budget` | Switch *input* power headroom, distinct from PoE output |
| `analyze poe-budget` | PoE *output* budget per switch: drawn vs budget, high-draw ports |
| `analyze uplink-redundancy` | Uplinks per switch; single-uplink switches (single points of failure) |
| `analyze client-density` | Wireless clients per access point, with average signal |
| `analyze dhcp-pools` | DHCP pool utilisation per network (near-exhaustion warnings) |
| `analyze link-speeds` | Fleet-wide ports below their capability, forced-speed traps and half duplex (exit 2 on HIGH) |
| `analyze port-profile-usage` | Where each port profile is used; forced-speed, shadowing, dangling, duplicate and unused profiles |
| `analyze traffic-matrix` | Top flows and top talkers |
| `analyze roaming` | Sticky clients and frequent roamers |
| `analyze config-drift` | Full device config snapshot and diff |
| `analyze neighbours` | Passive neighbour AP detection and trend |
| `diagnose all` | Run every diagnostic with a pass/warn/fail summary |
| `diagnose health` | Overall network health check |
| `diagnose security` | Security audit: unknown and anomalous devices, rogue APs, guest and VLAN violations |
| `diagnose vlans` | Every VLAN, the trunk ports that carry them, and the VLAN diagnostic checks |
| `diagnose freshness` | How old each device's telemetry is; `--sample` compares two reads a gap apart |
| `diagnose performance` | CPU, memory, load and drops per device, scored and ranked, with bottlenecks |
| `diagnose connectivity` | Segments, critical paths, single points of failure and a connectivity score |
| `diagnose firewall` | The firewall rules that match a source and destination, and the verdict |
| `diagnose path` | The path between two endpoints from controller data (`--analyze` for hop issues and bottlenecks); no packets sent |
| `diagnose client-path` | A client's path to the gateway from controller data |
| `diagnose wan` | WAN health and the controller's last scheduled speedtest (`--record` appends it to the history) |
| `diagnose wan-history` | The recorded WAN speedtest results, newest first |
| `diagnose device-stats` | One device's CPU, memory, load, uptime, radios and per-VAP TX counters |
| `diagnose ap-retries` | Every AP's per-VAP TX retry rate over an interval (two device reads) |
| `diagnose ap-health` | One AP's 2.4 GHz counters sampled over time beside a reference AP (CLI only; `--ping-clients` uses SSH) |
| `diagnose client-connectivity` | One client's lookup, AP counters, gateway ping, DNS, HTTP and flows, capped at 120 s (SSH) |
| `diagnose inter-vlan` | Inter-VLAN routing and firewall verdict between two endpoints |
| `diagnose latency-matrix` | SSH to the gateway and ping every device |
| `diagnose bandwidth` | iperf3 throughput test via the gateway |
| `gateway ping` | Ping one target from the gateway over SSH (loss, round trips) |
| `gateway traceroute` | The gateway's real forwarding path to a target, over SSH (reached only when the last hop is the target and answered without an ICMP unreachable, `!H`, `!N`, `!X` and the like; the table and `--json` mark each such hop `unreachable`) |
| `gateway dns` | Resolve a hostname on the gateway over SSH (nslookup) |
| `gateway http` | Fetch a URL from the gateway over SSH, from a VLAN's interface if asked |
| `gateway flows` | The gateway's conntrack flows over SSH, filtered by address or state |
| `vlan-traffic sample` | Sample every VLAN's bridge byte counters from the gateway over SSH into the local store |
| `vlan-traffic rollup` | Roll every complete hour and day of samples into hourly and daily rows, prune past 8 and 60 days; repairs a store a crashed sample left (offline) |
| `vlan-traffic report` | Per-VLAN average and peak throughput over now, 1d, 1w (raw samples), 1m (hourly) or 1y (daily), from the store (offline) |
| `vlan-traffic coverage` | What each tier of the store holds, and its gaps (offline) |
| `inventory list` | List devices with upgrade information |
| `inventory check-updates` | Check for firmware updates |
| `inventory firmware-skew` | Report firmware version skew by model |
| `inventory update-firmware` | Preview the firmware upgrades available (writes with `--apply`, after a confirmation `--force` skips) |
| `stp analyze` | Current STP topology and root eligibility |
| `stp audit-priorities` | One-shot audit: each switch's current vs recommended priority, tie and gateway warnings (read-only) |
| `stp optimize` | Preview or plan optimal priority changes |
| `stp apply` | Apply an approved change plan (previews; writes with `--no-dry-run`) |
| `stp rollback` | Revert a previously applied plan (previews; writes with `--no-dry-run`) |
| `stp preflight` | Simulate adding planned switches and report expected root state |
| `stp validate-10g` | Validate 10G readiness before adding switches |
| `stp guard` | Guard placement checks |
| `stp path-costs` | Inter-switch ports whose STP path cost does not match their link speed |
| `stp drift` | Compare live STP state against an intent file |
| `stp snapshot` | Capture an STP baseline |
| `stp diff` | Diff live state against a baseline |
| `stp report` | Generate a markdown STP report |
| `radio snapshot` | Snapshot radio configuration |
| `radio optimize` | Preview or apply optimised radio settings (writes with `--apply`) |
| `radio restore` | Restore a previous radio configuration (writes with `--apply`) |
| `radio auto-channel` | Utilization-weighted channel assignment (writes with `--apply`) |
| `radio report` | Generate a radio optimisation report |
| `backup verify` | Check a downloaded config backup (`.unf`) offline: structure and collection counts only |
| `controller config` | The controller's raw config objects of one kind, secrets removed |
| `controller config-changes` | Config objects created in the last N hours, newest first |
| `controller events` | Site-wide events, alarms and system-log entries from the last N hours |

Run any command with `--help` for its options.

Exit codes, across the commands:

| Code | Meaning |
| --- | --- |
| 0 | Done; a diagnosis found no fault |
| 1 | An error, reported as one line on stderr (a traceback only with `--debug`, without local variables): a failed read or connection, missing data, or a value a command checks once it runs, such as a `gateway` probe's URL, hostname or interface, or a `diagnose bandwidth` target. Some diagnoses (`diagnose client-connectivity`, for example) also exit 1 when they find a fault or a check could not run |
| 2 | A usage error, before anything is read: an unknown option, a value outside an option's stated range, a file option naming a directory, an `--output` that can't be written; or an invalid path or value given to a command that contacts nothing (`backup verify`, `diagnose wan-history`, the `vlan-traffic` readers) or to `controller events`' window. Also a check that failed: the validating commands (`analyze port-profiles`, `mtu`, `vlan-coverage`, `uplink-transparency`, `power-budget`, `link-speeds` and `port-profile-usage`, `diagnose all` and `inter-vlan`, `stp drift` and `validate-10g`) exit 2 when their validation fails, `stp apply` and `stp rollback` when a change failed, and `diagnose ap-health` when the printed report could not be written to `--output` |
| 130 | Interrupted with Ctrl-C after a partial report was printed (`diagnose ap-health`) |

> Invoke commands through the installed `unifi-mapper` script. `uv run python -m
> unifi_mapper.typer_cli` also works, and a test asserts both paths expose the same command set.

## Scheduled Audits

```bash
# Install the read-only audit jobs (macOS launchd or Linux crontab)
./scripts/unifi-cron.sh install

# Also schedule port naming, which WRITES port names every 30 minutes (off by default)
./scripts/unifi-cron.sh install --with-port-naming

# Check schedule status
./scripts/unifi-cron.sh status

# Run every task once now (add --with-port-naming to include the write)
./scripts/unifi-cron.sh run-all

# Update or remove schedules
./scripts/unifi-cron.sh update
./scripts/unifi-cron.sh uninstall
```

Schedules: the link-error history (`analyze link-errors --record`) and roaming snapshots every 5 minutes; config drift, `diagnose all`, the radio report and the WAN speedtest record (`diagnose wan --record`, one read of the controller's last scheduled result, never a new speedtest) hourly. Every default task only reads the controller or records locally. Port naming (`--verify-updates --connected-devices --apply`, every 30 minutes) writes port names, so it is scheduled or run only with `--with-port-naming`; `uninstall` removes it with the rest, and `status` says when it is not installed.

> [!IMPORTANT]
> **Upgrading an installed schedule.** `install` copies each task's command line into the
> launchd plist or crontab entry, and nothing re-reads the task list at run time. A schedule
> installed before 0.2.0 keeps its old commands: port naming then only previews (no
> `--apply`), and the 5-minute link-error job keeps overwriting both baselines instead of
> recording history. After upgrading, run `./scripts/unifi-cron.sh update` (uninstall, then
> install; add `--with-port-naming` to keep that job). `status` flags any installed command
> that differs from the current task list.

## Read-Only Scripts

```bash
# One read-only audit: port-name preview, STP snapshot, analysis, plan, guards and report
./scripts/network-audit.sh [--config PATH] [--output-dir DIR] [--planned-switches N]

# The controller's config and state objects as JSON, secrets removed (outside the repo only)
uv run python scripts/controller_dump.py --output ~/tmp/controller-dump [--endpoint NAME]...
```

- `scripts/network-audit.sh` runs `discover --dry-run` (its port-name report and topology
  diagram), `stp snapshot`, `stp analyze`, `stp optimize --dry-run --plan`, `stp guard` and
  `stp report` (and `stp validate-10g` only
  with `--planned-switches`) into `${XDG_STATE_HOME:-~/.local/state}/unifi_mapper/audits/`
  (a relative `XDG_STATE_HOME` is ignored), or into an `--output-dir` that is new, or empty,
  yours, not writable by others and not a link (exit 2 otherwise),
  then prints the commands that apply what you agree with, carrying the audit's own
  `--config` and `--project`. It never applies anything.
- `scripts/controller_dump.py` reads a fixed table of endpoints (`wlanconf`, `networkconf`,
  `setting`, `firewallrule`, `firewallgroup`, `sta`, `device`, `health`, and the v2
  `firewall-policies`, `firewall-zone`, `trafficrules`, `apgroups`) through the read-only
  guard, strips every secret field, and writes one `0o600` JSON file per endpoint plus
  `manifest.json` (counts, the removed paths and the request audit). `--output` inside the
  repository is refused (exit 2), so a dump can't be committed, and so is an existing
  directory that is not empty, not yours, writable by other users or a symbolic link: each
  file is created new in the directory as it was opened, so nothing planted there can
  redirect a write. Events and alarms come from
  `unifi-mapper controller events --json`.

## Advanced Verification

```bash
# Ground truth verification with consistency checking
uv run python -m unifi_mapper.verify_cli --verify-all --consistency-check

# Device capability analysis
uv run python -m unifi_mapper.analyze_network_capabilities
```
