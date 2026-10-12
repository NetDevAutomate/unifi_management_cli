---
title: "The gateway SSH commands don't verify the gateway's host key (`known_hosts=None`)"
date: 2026-10-03
status: open, decision needed
severity: medium
components: [analysis/gateway_ssh, analysis/latency_matrix, analysis/bandwidth_test, connectivity/gateway_probe, diagnostics/client_connectivity, analysis/ap_health, analysis/vlan_traffic]
found_by: review of the CLI-only SSH commands (`diagnose latency-matrix`, `diagnose bandwidth`)
---

# The gateway SSH commands don't verify the gateway's host key (`known_hosts=None`)

## Problem

`diagnose latency-matrix` and `diagnose bandwidth` open their SSH session with
`asyncssh.connect(..., known_hosts=None)` (`src/unifi_mapper/analysis/latency_matrix.py:183`,
`src/unifi_mapper/analysis/bandwidth_test.py:104`). asyncssh documents an explicit `None` as
disabling server host key validation, so both commands accept any host key from whatever
answers on the gateway's address. They then log in as root (`UNIFI_SSH_USERNAME`, default
`root`) with password authentication, so a host that intercepts the connection receives the
gateway's root SSH password, and can answer the `ping` and `iperf3` commands itself.

The architecture overview gave "self-signed UDM certs" as the reason. That is the TLS
question (`UNIFI_VERIFY_SSL`). SSH host keys aren't CA-signed: they're pinned on first use
in `~/.ssh/known_hosts`, which is how `ssh root@<gateway>` already works.

Left to its default (no `known_hosts` argument), asyncssh reads `UserKnownHostsFile` from
`~/.ssh/config`, else `~/.ssh/known_hosts`, and fails closed when the file or the gateway's
entry is missing.

## Evidence

- asyncssh 2.22 `connect()` docstring, on `known_hosts`: if not specified, the keys are
  looked up in `.ssh/known_hosts`; if explicitly set to `None`, server host key validation
  is disabled.
- asyncssh 2.22 `SSHClientConnectionOptions.prepare` and `SSHClientConnection._connection_made`
  (in `asyncssh/connection.py`): with the argument omitted, `UserKnownHostsFile`, then
  `~/.ssh/known_hosts`, then an empty set of trusted keys, which fails the handshake.

## Impact

- Who can use it: anything that can answer for the gateway's address on the path from the
  machine running the command, for example ARP spoofing on the same VLAN, a compromised
  device in between, or a spoofed name when `UNIFI_URL` is a hostname. These commands
  normally run from a laptop on the LAN, so that is the exposure.
- What it gets: the root SSH password, which is full control of the gateway (firewall,
  routing, VPN keys), and the ability to forge the latency and bandwidth results.
- Since `6fd791a` the password sent is always `UNIFI_SSH_PASSWORD`, never the UniFi OS
  login, which limits what leaks but doesn't close the gap.
- It doesn't break fresh clones, CI or the MCP server (neither command is an MCP tool).

## Decision needed

Recommendation: verify the host key by default against `~/.ssh/known_hosts`, with an
explicit opt-out.

1. Drop `known_hosts=None` from both calls (one connect helper in `analysis/gateway_ssh.py`),
   so asyncssh's default applies: `UserKnownHostsFile` from `~/.ssh/config`, else
   `~/.ssh/known_hosts`. The entry must match the host the commands connect to, the host
   in `UNIFI_URL` (or `UNIFI_HOST`), exactly.
2. Turn `asyncssh.HostKeyNotVerifiable` into a one-line error that names the host and the
   fix: run `ssh root@<gateway>` once and accept its key, ideally after comparing the
   fingerprint out of band. A changed key (factory reset, a replaced console) fails the same
   way until the stale entry is removed with `ssh-keygen -R <gateway>`; say that too.
3. Opt-out: `UNIFI_SSH_VERIFY_HOST_KEY=false` restores `known_hosts=None` and prints a
   warning on every run. Add it to `CONTROLLER_KEYS` in `mcp/config.py`, so it is loaded
   with the controller family like `UNIFI_VERIFY_SSL`.

Why this needs a decision: after the change, the first run on every machine fails until
the gateway's key is accepted once (`ssh root@<gateway>`), and so does any run after the
key changes. That is the point of the check, but it changes how both commands behave for
every user, so it is the user's call.

## Since the July port

- Every gateway SSH session now opens in one helper, `gateway_session()` in
  `analysis/gateway_ssh.py` (`db18bfa`), which passes `known_hosts=GATEWAY_KNOWN_HOSTS`. That
  constant (`None` today) is the one line step 1 changes; the `file:line` references above
  predate the helper.
- The port added CLI-only SSH entry points, all through that helper: `gateway ping`,
  `traceroute`, `dns`, `http` and `flows` (`8ed301f`); `diagnose client-connectivity` and
  `diagnose ap-health --ping-clients` (`707ea13`); and `vlan-traffic sample` (`ad846b6`). Each
  prints the warning that the host key is not verified once per run, before it connects. None
  is an MCP tool (decision D1 in issue [060](060-decisions-from-the-july-port.md)).
- The VLAN traffic sampler is held off every schedule: `scripts/unifi-cron.sh` has no
  `vlan-traffic sample` task. An unattended root SSH login every few minutes should wait for
  this decision.
