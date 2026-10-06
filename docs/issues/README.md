# Issues

Known problems that were found but not fixed in the change that found them. One file per
issue, named `NNN-short-slug.md`, numbered in the order filed.

Each file has `status: open` (or `open, decision needed`) in its front matter. When an
issue is fixed, set `status: resolved`, add `resolved_by: <commit>` and keep the file, so
the reasoning stays next to the code it explains.

## Index

| # | Title | Status |
| --- | --- | --- |
| [001](001-stub-commands-do-nothing.md) | `find device`, `analyze link-quality` and `diagnose health` are stubs | resolved (`ce93018`) |
| [002](002-port-counter-baseline-has-no-producer.md) | The port counter baseline store has no producer | resolved (`55b67b0`) |
| [003](003-integration-api-undocumented-base-path.md) | The Network Integration API client uses an undocumented base path | open |
| [004](004-no-counter-history.md) | There is no on-disk history of port error counters | resolved (`55b67b0`) |
| [005](005-pyright-errors-in-protect-monitor.md) | pyright reports 3 errors in `monitors/protect_monitor.py` | resolved (`b4cd19e`) |
| [006](006-mcp-guide-and-server-docstrings-stale.md) | The MCP guide and server docstrings miss the observability category and new counts | resolved (`c518915`) |
| [007](007-bare-discover-writes-by-default.md) | `unifi-mapper --connected-devices` writes port names by default | resolved (`27bca7c`) |
| [008](008-mcp-sdk-v2-migration.md) | Migrate the MCP server to the SDK v2 `MCPServer` API | open |
| [009](009-mcp-default-tool-surface.md) | Should the MCP server list every tool (the direct surface) by default? | open, decision needed |
| [010](010-cwd-relative-state-files.md) | Radio snapshots and several baselines are written relative to the working directory | open, decision needed |
| [011](011-network-protect-errors-as-success.md) | Network and Protect MCP tools return failures as successful results | open, decision needed |
| [012](012-mcp-default-tool-deadline.md) | MCP tool calls have no deadline by default | open, decision needed |
| [013](013-mcp-audit-log-and-result-cap.md) | No default audit log of MCP calls, and no cap on result size | resolved (`ec6aec9`) |
| [014](014-optional-dependency-extras.md) | Every uvx launch installs the Protect, backup and ONVIF dependencies | open |
| [015](015-other-discover-entry-points-write-by-default.md) | `unifi-network-toolkit discover` and `python -m unifi_mapper.cli` still write port names by default | open, decision needed |
| [016](016-audit-lldp-consistency-tool.md) | Add an LLDP consistency audit (`audit_lldp_consistency` / `analyze lldp`) | open |
| [017](017-firmware-drift-tool.md) | Add a firmware drift tool (`get_firmware_drift`) and `inventory firmware-skew --json` | open |
| [018](018-read-only-tool-proposals.md) | Read-only tool proposals for the CLI and MCP | open |
| [019](019-write-capable-cli-ideas.md) | Write-capable CLI ideas (plan, review, apply; never over MCP) | open, decision needed |
| [020](020-mcp-protocol-follow-ups.md) | MCP protocol and runtime follow-ups | open |
| [021](021-sync-diagnostic-path-logs-in-per-call.md) | The sync port-diagnostics MCP tools log in to the controller on every call | open, decision needed |
| [022](022-search-tools-quality.md) | `search_tools` misses multi-word queries, tags and differently-cased categories | open |
| [023](023-related-tools-hints-name-missing-tools.md) | Error hints send the model to `get_network_topology` and `vlan_info`, which don't exist | resolved (`d487314`) |
| [024](024-network-protect-tools-unguarded.md) | Network Integration API and Protect MCP tools run without a read-only guard or request audit | resolved (`5d21cdc`) |
| [025](025-launchd-plists-are-invalid-xml.md) | `unifi-cron.sh` writes launchd plists that are invalid XML, so macOS schedules never load | open, decision needed |
| [026](026-profile-precedence-outside-port-diagnostics.md) | `validate_port_profiles` and three other analyses resolve a port's profile without the override precedence | resolved (`865d417`) |
| [027](027-root-flags-dropped-before-a-subcommand.md) | Root `--connected-devices`, `--verify-updates` and `--dry-run` are silently dropped before a subcommand | resolved (`7412365`) |
| [028](028-tool-docstrings-name-missing-tools.md) | Tool docstrings and `path_analysis` recommendations name tools that don't exist | open |
| [029](029-async-guard-judges-a-different-path.md) | The async read-only guard judges and audits a different path when the raw path starts with `//` | open |
| [030](030-raw-portconf-id-read-as-a-profile-name.md) | `vlan_diagnostics` and `mac_analyzer` read a raw `portconf_id` as if it were a profile name | open, decision needed |
| [031](031-acl-rules-path-not-served.md) | `get_acl_rules` gets a 404: the client's `/acls` path isn't served by Network 10.6 | resolved (`fb4ff9e`) |
| [032](032-dns-policies-path-not-served.md) | `get_dns_policies` gets a 404: the client's `/dns-policies` path isn't served | resolved (`fb4ff9e`) |
| [033](033-client-access-type-default-rejected.md) | `get_clients` returns no clients: `access.type: DEFAULT` fails validation | resolved (`1f79d47`) |
| [034](034-protect-has-no-live-account.md) | The Protect MCP tools are unverified live: no Protect account is configured | open |
| [035](035-device-statistics-and-port-action-paths.md) | The Integration API client's device-statistics and port-action paths aren't served | open |
| [036](036-integration-api-models-drift-from-the-reference.md) | Integration API models disagree with the v10.6 reference, so some fields are lost | open |
| [037](037-launch-config-network-family-incomplete.md) | With the legacy config file, the six network_api tools return CONFIG_MISSING | open, decision needed |
| [038](038-ssh-host-key-verification-disabled.md) | The gateway SSH commands don't verify the gateway's host key (`known_hosts=None`) | open, decision needed |
| [039](039-promote-the-live-check-harness.md) | Promote the read-only live-check harness into the repo as a config-driven tool | open, decision needed |
| [040](040-real-identifiers-in-tests.md) | Test fixtures carried MAC addresses and addresses from the live network | open, decision needed |
| [041](041-onvif-scripts-hard-code-cameras.md) | The ONVIF scripts hard-coded the site's cameras, and `onvif_stream.py` a camera password that is in pushed history | open, decision needed |
| [042](042-settings-with-no-effect.md) | Five documented settings have no effect on `unifi-mapper` | open, decision needed |
| [043](043-inventory-ignores-the-root-config.md) | `unifi-mapper inventory` ignores the root `--config` and `UNIFI_CONFIG` | open |
| [044](044-discover-mermaid-and-dot-write-a-placeholder.md) | `discover --format mermaid` and `--format dot` write a placeholder, not a diagram | open, decision needed |
| [045](045-configure-logging-is-never-called.md) | `configure_logging` is never called, so `UNIFI_MAPPER_DEBUG` does nothing | open, decision needed |
| [046](046-real-device-names-in-code-and-history.md) | Tests, scripts and docstrings carried the site's device and room names; the history and some runtime strings still do | open, decision needed |
| [047](047-install-completions-fish-and-all-fail.md) | `unifi-mapper install-completions` accepts `fish` and `all` but installs only bash and zsh | open |
| [048](048-cli-and-mcp-config-searches-differ.md) | With `XDG_CONFIG_HOME` set, the CLI and the MCP server search different config files | open, decision needed |
| [049](049-lines-over-99-characters.md) | At `8d51214`, 225 tracked lines were longer than the 99-character limit, and nothing enforces it | open, decision needed |
| [050](050-latency-matrix-errors-bypass-the-ssh-error-path.md) | `diagnose latency-matrix` reports errors on stdout and unredacted, unlike `diagnose bandwidth` | resolved (`8308183`) |
| [051](051-verify-cli-help-example-held-a-password.md) | `verify_cli`'s help example held a real-looking password, and it is in pushed history | open, decision needed |
| [052](052-class-names-outside-the-docs-guard.md) | Class names in the docs are outside the docs-drift guard | open |
| [053](053-mcp-counts-in-prose-match-any-registry-count.md) | A tool count in prose only has to match one of the registry's counts | open |
| [054](054-identifier-guard-skips-public-and-link-local-addresses.md) | The identifier guard skips public IPv4 and link-local IPv6 addresses from the captures | open |
| [055](055-env-guard-counts-a-mention-as-a-read.md) | The env-var guard counts a variable as read when any string in the code names it | open |
| [056](056-mcp-name-guard-knows-every-assigned-name.md) | The MCP-name guard counts any name assigned in `src/` as known, local variables included | open |
| [057](057-onvif-test-rtsp-puts-the-password-on-argv.md) | `onvif_stream.py test-rtsp` passes the ONVIF password to ffprobe on its command line | open, decision needed |
| [058](058-tracebacks-print-frame-values.md) | Tracebacks can print secrets: loguru's `diagnose` and Typer's frame locals are on | resolved (`14488b1`) |
| [059](059-july-work-not-ported.md) | July work that was not ported, and why | open |
| [060](060-decisions-from-the-july-port.md) | Decisions from the July port | open, decision needed |
| [061](061-monitor-lags-misses-current-firmware-lags.md) | `monitor_lags` misses LAGs on current switch firmware | open |
| [062](062-open-items-from-the-archived-plans.md) | Open items from the archived improvement and STP plans | open |
| [063](063-execute-tool-result-cap.md) | No cap on `execute_tool` result size | open, decision needed |
| [064](064-cli-reads-outside-the-read-only-transport.md) | CLI read commands that reach the controller outside the read-only transport | open |
| [065](065-pre-push-coverage-floor.md) | The pre-push pytest hook fails the 90% coverage floor | open, decision needed |
| [066](066-backup-collections-unverified-on-a-real-backup.md) | `backup verify` names collections by `_type`, unverified on a real backup | open |
| [067](067-mcp-tool-failure-helper-duplicated.md) | The network and Protect tools each carry a copy of the redacted-failure helper | open |
| [068](068-relative-xdg-config-home-is-honoured.md) | The config searches honour a relative `XDG_CONFIG_HOME`, so they can read a file under the working directory | open, decision needed |
| [069](069-vlan-reports-read-tiers-without-recent-data.md) | VLAN traffic reports read rollup tiers that held no recent data, so `1w` was always empty | resolved (`56567fd`) |
| [070](070-untagged-networks-share-vlan-1-in-the-traffic-store.md) | Two networks without a VLAN ID both sample as VLAN 1, so one overwrites the other in the traffic store | open |
| [071](071-late-vlan-samples-never-reach-the-rollups.md) | A VLAN traffic sample written two hours or more late, into an hour already rolled, never reaches the hourly or daily rollups | open |
| [072](072-vlan-intervals-span-a-sampler-outage.md) | A VLAN traffic interval can span a sampler outage, so one fresh sample reports days of traffic as current | open, decision needed |
| [073](073-gateway-ping-step-duplicated.md) | The gateway ping step is written twice, in gateway ping and in AP-health's client pings | open |
| [074](074-mqtt-needs-an-undeclared-dependency.md) | MQTT support needs aiomqtt, which the project does not declare (its hint and the README now name `uv add aiomqtt`) | open, decision needed |
| [075](075-discover-needs-graphviz-dot-undocumented.md) | `discover` needs Graphviz's `dot` program for its PNG and SVG diagrams and exits 1 without it, writing no report (the docs now name it) | open |
| [076](076-july-port-final-review-follow-ups.md) | Follow-ups from the July port's final review that were not fixed on the branch | open, decision needed |
