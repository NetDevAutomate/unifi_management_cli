---
title: "`onvif_stream.py test-rtsp` passes the ONVIF password to ffprobe on its command line"
date: 2026-10-05
status: resolved
resolved_by: 2837c45
severity: medium
components: [scripts/onvif_stream.py]
found_by: docs and repo hygiene review
---

# `onvif_stream.py test-rtsp` passes the ONVIF password to ffprobe on its command line

## Problem

`check_rtsp()` in `scripts/onvif_stream.py` builds the authenticated stream URI with
`_with_credentials()` and passes it to `subprocess.run` as ffprobe's `-i` argument. A
process's arguments are readable by other local users (`ps -o args`) for as long as ffprobe
runs, which is up to its 10-second timeout per camera.

The masking added in `432ed08` (`_redact`) covers what the script prints: the URI line and
any error text. It doesn't cover argv. The AXIS guide (section 8) documents the exposure, but
no issue tracked it.

## Impact

Local only, and only while `test-rtsp` runs. On a managed Mac the realistic reader is an
endpoint agent that records process command lines: each run would send the camera account's
password to that telemetry. `info`, `streams` and `snapshot` don't start a subprocess with
credentials.

## Recommendation

1. Add a failing test first. `tests/test_onvif_scripts.py` already stubs `subprocess.run` and
   records every ffprobe call's argument list. Assert that no element holds the password.
2. Decide how to probe without argv credentials:
   - **Recommended:** probe in-process with PyAV (`av.open(uri, options={"rtsp_transport":
     "tcp"}, timeout=10)`). libavformat then runs inside the script, and the password never
     reaches a command line. It adds a script-only dependency, so put it in a dependency group,
     not the package.
   - **Or:** keep ffprobe and accept the documented exposure. Close this issue as won't-fix
     with that reason.
3. Verify against a local RTSP test server (for example mediamtx), never a real camera, and
   keep the masked-output tests green.

## Resolution

Resolved on 2026-10-13 by `2837c45`. `test-rtsp` no longer starts ffprobe: `rtsp_describe`
sends one RTSP `DESCRIBE` from this process over TCP, answering a Digest challenge (or Basic,
only when the camera offers nothing else) and bounded by a single deadline, so the password
never appears on any command line or in the process list. The command's docstring and output
promise exactly what the probe checks: the camera accepted the account and returned the
stream's SDP metadata (printed as codec and dimensions). It does not prove the stream plays,
which is the council's stated acceptance condition for a DESCRIBE-only probe (decision
D-057, recorded with the 0.3.0 release decisions). No dependency was added. The tests run a fake RTSP
camera on a Unix socket requiring Digest auth (success, wrong password, Basic fallback, a silent
camera against the deadline) and assert that `check_rtsp` has no subprocess and that no output
carries the password. The Axis guide's ffprobe prerequisite and the sentence describing the
exposure were replaced.
