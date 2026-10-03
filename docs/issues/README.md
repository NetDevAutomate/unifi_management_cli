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
| [005](005-pyright-errors-in-protect-monitor.md) | pyright reports 3 errors in monitors/protect_monitor.py | resolved (`b4cd19e`) |
| [006](006-mcp-guide-and-server-docstrings-stale.md) | The MCP guide and server docstrings miss the observability category and new counts | resolved (`c518915`) |
| [007](007-bare-discover-writes-by-default.md) | `unifi-mapper --connected-devices` writes port names by default | resolved (`27bca7c`) |
| [008](008-mcp-sdk-v2-migration.md) | Migrate the MCP server to the SDK v2 MCPServer API | open |
| [009](009-mcp-default-tool-surface.md) | Should the MCP server list every tool (the direct surface) by default? | open, decision needed |
| [010](010-cwd-relative-state-files.md) | Radio snapshots and several baselines are written relative to the working directory | open, decision needed |
| [011](011-network-protect-errors-as-success.md) | Network and Protect MCP tools return failures as successful results | open, decision needed |
| [012](012-mcp-default-tool-deadline.md) | MCP tool calls have no deadline by default | open, decision needed |
| [013](013-mcp-audit-log-and-result-cap.md) | No default audit log of MCP calls, and no cap on result size | open, decision needed |
| [014](014-optional-dependency-extras.md) | Every uvx launch installs the Protect, backup and ONVIF dependencies | open |
| [015](015-other-discover-entry-points-write-by-default.md) | `unifi-network-toolkit discover` and `python -m unifi_mapper.cli` still write port names by default | open, decision needed |
| [016](016-audit-lldp-consistency-tool.md) | Add an LLDP consistency audit (`audit_lldp_consistency` / `analyze lldp`) | open |
| [017](017-firmware-drift-tool.md) | Add a firmware drift tool (`get_firmware_drift`) and `inventory firmware-skew --json` | open |
| [018](018-read-only-tool-proposals.md) | Read-only tool proposals for the CLI and MCP | open |
| [019](019-write-capable-cli-ideas.md) | Write-capable CLI ideas (plan, review, apply; never over MCP) | open, decision needed |
| [020](020-mcp-protocol-follow-ups.md) | MCP protocol and runtime follow-ups | open |
| [021](021-sync-diagnostic-path-logs-in-per-call.md) | The sync port-diagnostics MCP tools log in to the controller on every call | open |
| [022](022-search-tools-quality.md) | `search_tools` misses multi-word queries, tags and differently-cased categories | open |
| [023](023-related-tools-hints-name-missing-tools.md) | Error hints send the model to `get_network_topology` and `vlan_info`, which don't exist | resolved |
| [024](024-network-protect-tools-unguarded.md) | Network Integration API and Protect MCP tools run without a read-only guard or request audit | resolved |
| [025](025-launchd-plists-are-invalid-xml.md) | `unifi-cron.sh` writes launchd plists that are invalid XML, so macOS schedules never load | open, decision needed |
| [026](026-profile-precedence-outside-port-diagnostics.md) | `validate_port_profiles` and three other analyses resolve a port's profile without the override precedence | open, decision needed |
| [027](027-root-flags-dropped-before-a-subcommand.md) | Root `--connected-devices`, `--verify-updates` and `--dry-run` are silently dropped before a subcommand | open, decision needed |
| [028](028-tool-docstrings-name-missing-tools.md) | Tool docstrings and `path_analysis` recommendations name tools that don't exist | open |
| [029](029-async-guard-judges-a-different-path.md) | The async read-only guard judges and audits a different path when the raw path starts with `//` | open |
