---
title: "`verify_cli`'s help example held a real-looking password, and it is in pushed history"
date: 2026-10-04
status: open, decision needed
severity: high
components: [verify_cli, history]
found_by: docs and repo hygiene review (C4 provider docs, verify_cli)
---

# `verify_cli`'s help example held a real-looking password, and it is in pushed history

## Problem

The browser-verification example in the `--help` epilog of
`python -m unifi_mapper.verify_cli` (`src/unifi_mapper/verify_cli.py`) showed a username and
a 20-character password that is not a placeholder. It came in with `216c8e1` (2025-12-30)
and stayed in every revision until `8d51214` removed it, the `origin/main` tip included, so
it has been on GitHub since then. No other tracked file holds it.

Nothing caught it. detect-secrets' keyword plugin doesn't read the `--password VALUE`
shape, so the value never reached `.secrets.baseline`, and the local privacy scan only
looks for the values of the configured env files. Compared in-process, without printing
it, the value matches none of them, so it isn't the controller UI login, the console API
token or the SSH password. Given the username, it is most likely the password of a local
UniFi OS account used by UnPoller. The repository is public.

`8d51214` replaced the example's username and password with `<username>` and `<password>`.

## Impact

Anyone who can read the repository or a clone of it can read the value. If it is, or was,
a live account's password, that account is exposed: read access for an UnPoller-style
monitoring account, more if the account was given a wider role. Removing the value from
HEAD doesn't help with that, because it stays in every pushed revision. It doesn't break
fresh clones, contributors or CI.

## Decision needed

What is left, in this order:

1. Done by the user: UnPoller has been deleted and all passwords have been changed (the
   user's report; not checked here).
2. The history rewrite: the user has asked for the history to be rewritten to remove this
   value, and the camera password in
   [issue 041](041-onvif-scripts-hard-code-cameras.md) with it. That runs separately, after
   this review. It rewrites every commit since `216c8e1`, its force-push needs the user's
   explicit confirmation, and every clone has to be re-made afterwards. The user has
   approved removing the network details in the unpushed commits
   ([issue 040](040-real-identifiers-in-tests.md),
   [issue 046](046-real-device-names-in-code-and-history.md)) in the same rewrite. Only the
   identifiers in the pushed history are still to decide. The orchestrator sets the exact
   commit list.

A guard is already in place: `tests/test_example_credentials.py` (`8d51214`) reads every
string literal under `src/` and fails on a password option or argument whose value isn't a
`<placeholder>`, a `$VARIABLE` or a `{template}` field. Running `detect-secrets audit` on the
baseline would also confirm that no other entry is a real credential.

Why this needs a decision: the rewrite's force-push needs the user's confirmation; the
review never pushes.
