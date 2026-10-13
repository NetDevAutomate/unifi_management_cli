---
title: "`create_block_rule` / `create_allow_rule` default `rule_type='USER'`, a value the ACL API rejects"
date: 2026-10-13
status: open
severity: low
components: [network/acl]
found_by: the 0.3.0 Integration API lane (issue 036)
---

# `create_block_rule` / `create_allow_rule` default `rule_type='USER'`, a value the ACL API rejects

## Problem

`network/acl.py` lines 243 and 308 default `rule_type` to `'USER'`. The ACL `type` values
present in the in-repo fixtures are `IPV4`; `USER` is the value of `metadata.origin`, a
different field.

## Impact

A caller that accepts the default builds a rule the controller refuses, with a 400 that names a
field the caller did not set. These helpers are CLI-only (ACL writes are not exposed over MCP),
so no automated path is affected today.

## Recommended fix

Default `rule_type` to `IPV4` or make it a required argument; add a MockTransport test that the
request body carries the type the fixtures show.
