---
title: "`onvif_stream.py test-rtsp` passes the ONVIF password to ffprobe on its command line"
date: 2026-10-05
status: open, decision needed
severity: medium
components: [scripts/onvif_stream.py]
found_by: docs and repo hygiene review (M4 council)
---

# `onvif_stream.py test-rtsp` passes the ONVIF password to ffprobe on its command line

## Problem

`check_rtsp()` in `scripts/onvif_stream.py` builds the authenticated stream URI with
`_with_credentials()` and passes it to `subprocess.run` as ffprobe's `-i` argument. A
process's arguments are readable by other local users (`ps -o args`) for as long as ffprobe
runs, which is up to its 10-second timeout per camera.

The masking added in `1fcf726` (`_redact`) covers what the script prints: the URI line and
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
