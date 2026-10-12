# Security

This tool authenticates to your UniFi controller with your credentials and can, on request,
write to it. Read this before running it against a production network.

## What it does with your credentials

- They are read from one config file (`~/.config/unifi_management_cli/prod.env` by default;
  `--config` or `UNIFI_CONFIG` to choose another). Keep that file `chmod 600`. Nothing is
  written back to it, and it is never committed (`.env` is gitignored).
- An API token (`UNIFI_CONSOLE_API_TOKEN`) is preferred over a username and password. A
  dedicated read-only or view-only account is recommended for anything that does not write.
- Controller payloads are stripped of secrets before they are printed, logged or saved:
  keys starting with `x_` and keys containing `password`, `secret`, `token`, `authkey`, `psk`,
  `preshared`, `passphrase`, `api_key` or `private_key`, plus the SNMP
  `community` string, `syslog_key` and `lcm_tracker_seed`, are removed, and only the paths of
  what was removed are reported. The match is by key name: a credential someone typed into a
  free-text field under another key (a device note, say) is not recognised, and a key spelt
  `pre-shared` or `pre_shared` is not matched yet
  ([issue 076, item 6](docs/issues/076-july-port-final-review-follow-ups.md)). Tracebacks never
  print local variables.
- **Stripping is not anonymisation.** Reports, evidence bundles and MCP results still carry
  device and client names, MAC and IP addresses, SSIDs and your topology. Treat every output
  as sensitive and review it before posting it to a forum or a ticket.
- **The MCP server's results go to whatever AI host you connect it to** (Claude, Codex, a
  desktop client), under that host's data terms. It serves read-only tools; what it returns
  is your network's data, redacted of secrets but not of identifiers.

## Defaults you should know about

- **TLS verification is off by default** (`UNIFI_VERIFY_SSL=false`), because most consoles
  present a self-signed certificate. Set it to `true` if your console has a trusted
  certificate.
- **The gateway SSH commands do not verify the gateway's host key yet**
  ([issue 038](docs/issues/038-ssh-host-key-verification-disabled.md)). They are CLI-only and
  only run when `UNIFI_SSH_PASSWORD` is set.
- **Nothing writes to the controller unless you ask.** Commands that can write preview by
  default and need `--apply` or `--no-dry-run`; the MCP server exposes read-only tools only and
  never opens SSH.
- The MCP call log (`~/.local/state/unifi_mapper/mcp-audit.jsonl`, `0600`) records tool names
  and argument keys, never values.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability
reporting on this repository ("Report a vulnerability" under the Security tab), or email the
maintainer at the address in `pyproject.toml`. Include the command or tool, the controller
version, and what you observed. You will get an acknowledgement within a week.

## Scope

In scope: anything that leaks a credential or controller secret, writes to a controller without
`--apply`, or reaches a device outside the configured controller and gateway. Out of scope:
vulnerabilities in UniFi OS itself (report those to Ubiquiti).
