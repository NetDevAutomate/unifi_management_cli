# Issues

Known problems that were found but not fixed in the change that found them. One file per
issue, named `NNN-short-slug.md`, numbered in the order filed.

Each file has `status: open` (or `open, decision needed`) in its front matter. When an
issue is fixed, set `status: resolved`, add `resolved_by: <commit>` and keep the file, so
the reasoning stays next to the code it explains.

Several files refer to *the prototype* and *the 0.2.0 port*. The prototype is the diagnostics
work written in June and July 2026 on a separate checkout; the 0.2.0 port carried it onto this
history in October 2026 as release 0.2.0. Issues [059](059-prototype-work-not-ported.md) and
[060](060-decisions-from-the-0.2.0-port.md) record what was and was not carried over.

## Index

| # | Title | Status |
| --- | --- | --- |
| [001](001-stub-commands-do-nothing.md) | `find device`, `analyze link-quality` and `diagnose health` are stubs | resolved (`4195f49`) |
| [002](002-port-counter-baseline-has-no-producer.md) | The port counter baseline store has no producer | resolved (`9f8c215`) |
| [003](003-integration-api-undocumented-base-path.md) | The Network Integration API client uses an undocumented base path | resolved (`2533cf6`) |
| [004](004-no-counter-history.md) | There is no on-disk history of port error counters | resolved (`9f8c215`) |
| [005](005-pyright-errors-in-protect-monitor.md) | pyright reports 3 errors in `monitors/protect_monitor.py` | resolved (`3368379`) |
| [006](006-mcp-guide-and-server-docstrings-stale.md) | The MCP guide and server docstrings miss the observability category and new counts | resolved (`ab32faa`) |
| [007](007-bare-discover-writes-by-default.md) | `unifi-mapper --connected-devices` writes port names by default | resolved (`95b822a`) |
| [008](008-mcp-sdk-v2-migration.md) | Migrate the MCP server to the SDK v2 `MCPServer` API | open |
| [009](009-mcp-default-tool-surface.md) | Should the MCP server list every tool (the direct surface) by default? | open, decision needed |
| [010](010-cwd-relative-state-files.md) | Radio snapshots and several baselines are written relative to the working directory | open, decision needed |
| [011](011-network-protect-errors-as-success.md) | Network and Protect MCP tools return failures as successful results | resolved (`9c57b2e`) |
| [012](012-mcp-default-tool-deadline.md) | MCP tool calls have no deadline by default | resolved (`8071f7d`) |
| [013](013-mcp-audit-log-and-result-cap.md) | No default audit log of MCP calls, and no cap on result size | resolved (`e2fbac2`) |
| [014](014-optional-dependency-extras.md) | Every uvx launch installs the Protect, backup and ONVIF dependencies | open |
| [015](015-other-discover-entry-points-write-by-default.md) | `unifi-network-toolkit discover` and `python -m unifi_mapper.cli` still write port names by default | resolved (`0ac8d0d`) |
| [016](016-audit-lldp-consistency-tool.md) | Add an LLDP consistency audit (`audit_lldp_consistency` / `analyze lldp`) | open |
| [017](017-firmware-drift-tool.md) | Add a firmware drift tool (`get_firmware_drift`) and `inventory firmware-skew --json` | resolved (`19ff5ce`) |
| [018](018-read-only-tool-proposals.md) | Read-only tool proposals for the CLI and MCP | open |
| [019](019-write-capable-cli-ideas.md) | Write-capable CLI ideas (plan, review, apply; never over MCP) | open, decision needed |
| [020](020-mcp-protocol-follow-ups.md) | MCP protocol and runtime follow-ups | open |
| [021](021-sync-diagnostic-path-logs-in-per-call.md) | The sync port-diagnostics MCP tools log in to the controller on every call | open, decision needed |
| [022](022-search-tools-quality.md) | `search_tools` misses multi-word queries, tags and differently-cased categories | resolved (`0c98496`) |
| [023](023-related-tools-hints-name-missing-tools.md) | Error hints send the model to `get_network_topology` and `vlan_info`, which don't exist | resolved (`a3efa2f`) |
| [024](024-network-protect-tools-unguarded.md) | Network Integration API and Protect MCP tools run without a read-only guard or request audit | resolved (`e8050fe`) |
| [025](025-launchd-plists-are-invalid-xml.md) | `unifi-cron.sh` writes launchd plists that are invalid XML, so macOS schedules never load | resolved (`17417f3`) |
| [026](026-profile-precedence-outside-port-diagnostics.md) | `validate_port_profiles` and three other analyses resolve a port's profile without the override precedence | resolved (`71083e4`) |
| [027](027-root-flags-dropped-before-a-subcommand.md) | Root `--connected-devices`, `--verify-updates` and `--dry-run` are silently dropped before a subcommand | resolved (`25d6998`) |
| [028](028-tool-docstrings-name-missing-tools.md) | Tool docstrings and `path_analysis` recommendations name tools that don't exist | resolved (`d9ce545`) |
| [029](029-async-guard-judges-a-different-path.md) | The async read-only guard judges and audits a different path when the raw path starts with `//` | resolved (`b70b85d`) |
| [030](030-raw-portconf-id-read-as-a-profile-name.md) | `vlan_diagnostics` and `mac_analyzer` read a raw `portconf_id` as if it were a profile name | resolved (`b3732d8`) |
| [031](031-acl-rules-path-not-served.md) | `get_acl_rules` gets a 404: the client's `/acls` path isn't served by Network 10.6 | resolved (`6fd892c`) |
| [032](032-dns-policies-path-not-served.md) | `get_dns_policies` gets a 404: the client's `/dns-policies` path isn't served | resolved (`6fd892c`) |
| [033](033-client-access-type-default-rejected.md) | `get_clients` returns no clients: `access.type: DEFAULT` fails validation | resolved (`8828255`) |
| [034](034-protect-has-no-live-account.md) | The Protect MCP tools are unverified live: no Protect account is configured | open |
| [035](035-device-statistics-and-port-action-paths.md) | The Integration API client's device-statistics and port-action paths aren't served | resolved (`b975340`) |
| [036](036-integration-api-models-drift-from-the-reference.md) | Integration API models disagree with the v10.6 reference, so some fields are lost | resolved (`befe82a`) |
| [037](037-launch-config-network-family-incomplete.md) | With the legacy config file, the six network_api tools return CONFIG_MISSING | open, decision needed |
| [038](038-ssh-host-key-verification-disabled.md) | The gateway SSH commands don't verify the gateway's host key (`known_hosts=None`) | open, decision needed |
| [039](039-promote-the-live-check-harness.md) | Promote the read-only live-check harness into the repo as a config-driven tool | open, decision needed |
| [040](040-real-identifiers-in-tests.md) | Test fixtures carried MAC addresses and addresses from the live network | resolved (`2650809`) |
| [041](041-onvif-scripts-hard-code-cameras.md) | The ONVIF scripts hard-coded the site's cameras, and `onvif_stream.py` a camera password that is in pushed history | resolved (`2650809`) |
| [042](042-settings-with-no-effect.md) | Five documented settings have no effect on `unifi-mapper` | resolved (`38594dd`) |
| [043](043-inventory-ignores-the-root-config.md) | `unifi-mapper inventory` ignores the root `--config` and `UNIFI_CONFIG` | resolved (`9e506f0`) |
| [044](044-discover-mermaid-and-dot-write-a-placeholder.md) | `discover --format mermaid` and `--format dot` write a placeholder, not a diagram | resolved (`9b403ab`) |
| [045](045-configure-logging-is-never-called.md) | `configure_logging` is never called, so `UNIFI_MAPPER_DEBUG` does nothing | resolved (`70bbf8b`) |
| [046](046-real-device-names-in-code-and-history.md) | Tests, scripts and docstrings carried the site's device and room names; the history still does | resolved (`2650809`) |
| [047](047-install-completions-fish-and-all-fail.md) | `unifi-mapper install-completions` accepts `fish` and `all` but installs only bash and zsh | resolved (`3951920`) |
| [048](048-cli-and-mcp-config-searches-differ.md) | With `XDG_CONFIG_HOME` set, the CLI and the MCP server search different config files | open, decision needed |
| [049](049-lines-over-99-characters.md) | At `3ea7243`, 225 tracked lines were longer than the 99-character limit, and nothing enforces it | open, decision needed |
| [050](050-latency-matrix-errors-bypass-the-ssh-error-path.md) | `diagnose latency-matrix` reports errors on stdout and unredacted, unlike `diagnose bandwidth` | resolved (`7b1ef78`) |
| [051](051-verify-cli-help-example-held-a-password.md) | `verify_cli`'s help example held a real-looking password, and it is in pushed history | resolved (`2650809`) |
| [052](052-class-names-outside-the-docs-guard.md) | Class names in the docs are outside the docs-drift guard | resolved (`9b5af8b`) |
| [053](053-mcp-counts-in-prose-match-any-registry-count.md) | A tool count in prose only has to match one of the registry's counts | resolved (`b131da0`) |
| [054](054-identifier-guard-skips-public-and-link-local-addresses.md) | The identifier guard skips public IPv4 and link-local IPv6 addresses from the captures | resolved (`bc73af8`) |
| [055](055-env-guard-counts-a-mention-as-a-read.md) | The env-var guard counts a variable as read when any string in the code names it | resolved (`ff69dc6`) |
| [056](056-mcp-name-guard-knows-every-assigned-name.md) | The MCP-name guard counts any name assigned in `src/` as known, local variables included | resolved (`16dda92`) |
| [057](057-onvif-test-rtsp-puts-the-password-on-argv.md) | `onvif_stream.py test-rtsp` passes the ONVIF password to ffprobe on its command line | open, decision needed |
| [058](058-tracebacks-print-frame-values.md) | Tracebacks can print secrets: loguru's `diagnose` and Typer's frame locals are on | resolved (`779c14e`) |
| [059](059-prototype-work-not-ported.md) | Prototype work that was not ported, and why | open |
| [060](060-decisions-from-the-0.2.0-port.md) | Decisions from the 0.2.0 port | open, decision needed |
| [061](061-monitor-lags-misses-current-firmware-lags.md) | `monitor_lags` misses LAGs on current switch firmware | resolved (`b314c77`) |
| [062](062-open-items-from-the-archived-plans.md) | Open items from the archived improvement and STP plans | open |
| [063](063-execute-tool-result-cap.md) | No cap on `execute_tool` result size | open, decision needed |
| [064](064-cli-reads-outside-the-read-only-transport.md) | CLI read commands that reach the controller outside the read-only transport | resolved (`02bec3a`) |
| [065](065-pre-push-coverage-floor.md) | The pre-push pytest hook fails the 90% coverage floor | resolved (`1a7f2d7`) |
| [066](066-backup-collections-unverified-on-a-real-backup.md) | `backup verify` names collections by `_type`, unverified on a real backup | open |
| [067](067-mcp-tool-failure-helper-duplicated.md) | The network and Protect tools each carry a copy of the redacted-failure helper | resolved (`681497f`) |
| [068](068-relative-xdg-config-home-is-honoured.md) | The config searches honour a relative `XDG_CONFIG_HOME`, so they can read a file under the working directory | open, decision needed |
| [069](069-vlan-reports-read-tiers-without-recent-data.md) | VLAN traffic reports read rollup tiers that held no recent data, so `1w` was always empty | resolved (`0b19f3c`) |
| [070](070-untagged-networks-share-vlan-1-in-the-traffic-store.md) | Two networks without a VLAN ID both sample as VLAN 1, so one overwrites the other in the traffic store | resolved (`b645b1d`) |
| [071](071-late-vlan-samples-never-reach-the-rollups.md) | A VLAN traffic sample written two hours or more late, into an hour already rolled, never reaches the hourly or daily rollups | resolved (`1146b22`) |
| [072](072-vlan-intervals-span-a-sampler-outage.md) | A VLAN traffic interval can span a sampler outage, so one fresh sample reports days of traffic as current | resolved (`5bc743e`) |
| [073](073-gateway-ping-step-duplicated.md) | The gateway ping step is written twice, in gateway ping and in AP-health's client pings | resolved (`417ff83`) |
| [074](074-mqtt-needs-an-undeclared-dependency.md) | MQTT support needs aiomqtt, which the project does not declare (its hint and the README now name `uv add aiomqtt`) | resolved (`df3d905`) |
| [075](075-discover-needs-graphviz-dot-undocumented.md) | `discover` needs Graphviz's `dot` program for its PNG and SVG diagrams and exits 1 without it, writing no report (the docs now name it) | resolved (`21f728b`) |
| [076](076-0.2.0-port-final-review-follow-ups.md) | Follow-ups from the 0.2.0 port's final review that were not fixed on the branch | open, 27 of 29 items done (`0c1468e`) |
| [077](077-update-firmware-confirms-instead-of-previewing.md) | `inventory update-firmware` writes after a confirmation prompt, not a preview | open, decision needed |
| [078](078-cli-and-mcp-feature-parity-is-not-enforced.md) | The CLI and the MCP server do not have feature parity, and nothing checks that they do | resolved (`4d55fa0`) |
| [079](079-security-audit-counts-every-neighbour-ap-as-a-critical-rogue.md) | `security_audit` counts every neighbouring AP as a critical rogue | resolved (`2f8d2a8`) |
| [080](080-security-audit-rates-own-devices-and-iot-vendors-as-medium.md) | `security_audit` rates its own adopted devices and every IoT vendor as medium risk | open, decision needed |
