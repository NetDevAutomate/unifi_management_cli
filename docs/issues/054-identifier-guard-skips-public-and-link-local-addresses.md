---
title: "The identifier guard skips public IPv4 and link-local IPv6 addresses from the captures"
date: 2026-10-04
status: resolved
resolved_by: bc73af8
severity: low
components: [tests/test_docs_consistency.py]
found_by: docs and repo hygiene review
---

# The identifier guard skips public IPv4 and link-local IPv6 addresses from the captures

## Problem

`tests/test_docs_consistency.py` fails when a tracked test or script holds an identifier
that the local captures (`reports/*.json`) hold. `captured_identifiers` collects addresses
by network, not by value:

- an IPv4 address counts only when it is private, link-local or CGNAT
  (`PRIVATE_NETWORKS`), and the guard keeps its /24;
- an IPv6 address counts only when it is global unicast or unique local (`SITE_V6`), and
  the guard keeps its /48.

Two kinds of captured address therefore never become identifiers:

- a public IPv4 address, such as the site's WAN address, which identifies the site more
  than any other value;
- a link-local IPv6 address, which can embed the device's MAC address.

`captured_identifier_problems` can't report what the guard never collected, so a test or
script line holding one of these values passes.

## Impact

Nothing leaks at HEAD: the local privacy scan, which matches both kinds by exact value,
finds none in `tests/` or `scripts/`. The committed guard is the one that outlives this
review, though, and it is weaker than the local scan in the case a public repository
cares about most.

## Recommendation

1. In `captured_identifiers`, also collect, by exact value:
   - public IPv4 addresses from structured address fields (the WAN and gateway fields,
     say), leaving out a short allowlist of public resolvers (`1.1.1.1`, `8.8.8.8`,
     `9.9.9.9` and the like), the documentation ranges, multicast, loopback and reserved
     space;
   - link-local IPv6 addresses (`fe80::/10`).
2. Report them from `captured_identifier_problems` as their own kinds, with the file and
   line only, never the value.
3. Extend `test_captured_identifier_detector_reports_what_the_captures_hold` with one of
   each, built at run time so the file holds no literal, plus an allowlisted resolver that
   must not be reported.

Which capture fields carry the WAN address is the design step: matching every public
address in the captures would also catch the vendors' cloud and update hosts.

## Resolution

Resolved on 2026-10-13 (`bc73af8`). `captured_identifiers` now also collects, by exact value:

- every public IPv4 address in an **address field** of a capture: a key that is or ends in
  `ip`, `ip6`, `ipv6`, `gateway` or `gw`, or is `wan`, `wan1`, `wan2` (`ADDRESS_KEY`), and
  does not name a DNS, NTP, server, host, resolver or speedtest field
  (`NOT_A_SITE_ADDRESS_KEY`). That is the design step's answer to "which fields carry the
  WAN address": the field's name, not an enumeration of controller payloads, so a vendor's
  cloud or update host (a `*_host` or `*server*` field) is never collected. The public
  resolvers of Cloudflare, Google, Quad9 and OpenDNS (`PUBLIC_RESOLVERS`), the documentation
  ranges, loopback, multicast, reserved space, "this network" and the broadcast address
  (`NOT_PUBLIC_V4`) are left out as well;
- every link-local IPv6 address (`fe80::/10`), from any field.

`captured_identifier_problems` reports them as `public IPv4 address` and `link-local IPv6
address` "from the local captures", with the file and line only. A public address counts by
value, not by network: its /24 neighbour is not reported, since a public /24 is the ISP's,
not the site's. The self-test builds a WAN address, its neighbour, an allowlisted resolver,
a public address in a non-address field and a link-local address at run time, and expects
exactly the WAN and link-local lines.

Run against the fourteen local captures, the extended guard collects no public and no
link-local address (the captures' only public values are three resolver addresses in `dns1`
and `dns2` fields) and reports nothing under `tests/` or `scripts/`, so no fixture needed a
documentation value. The committed guard now matches the local privacy scan in the two
cases this issue named.
