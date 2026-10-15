---
title: "At `3ea7243`, 225 tracked lines were longer than the 99-character limit, and nothing enforces it"
date: 2026-10-04
status: open, decision needed
severity: low
components: [pyproject, src, tests, scripts]
found_by: docs and repo hygiene review (line-length guard)
---

# At `3ea7243`, 225 tracked lines were longer than the 99-character limit, and nothing enforces it

## Problem

`pyproject.toml` sets ruff's `line-length = 99`, and the house style keeps `.py` and `.toml`
lines at 99 characters or fewer. ruff can't hold that line, though: `E501` is in the
`ignore` list, and `ruff format` doesn't split long strings or comments. At `3ea7243`,
counting characters per line (not bytes), 225 tracked lines were longer:

| Area | Files | Lines over 99 characters |
| --- | ---: | ---: |
| `src/` | 44 | 172 |
| `tests/` | 7 | 36 |
| `scripts/` | 4 | 16 |
| `pyproject.toml` | 1 | 1 |

The longest was 174 characters. About 100 were f-strings (mostly log and console
messages), about 80 other string literals (help text and test fixtures), 6 comments and
the rest code. All of them predate the docs and hygiene review, which added none. Later
commits move the count a little, so count again before a sweep. A count in bytes, such as
macOS `awk 'length > 99'`, reports more lines than this, because box-drawing and emoji
characters take several bytes each.

## Impact

Style only: no behaviour, test or build depends on line length. New long lines can land
unnoticed, because nothing checks them. It doesn't break fresh clones, contributors or CI.

## Decision needed

Recommendation: sweep the long lines (wrap strings and comments, mechanical and reviewable
file by file), then drop `E501` from the ignore list so ruff enforces the limit from then
on.

The alternative is to document the exemption: keep `E501` ignored, say in the README's
development notes that the limit applies to new code only, and check added lines in review.

Why this needs a decision: the sweep touches 56 files across `src/`, `tests/` and the site
scripts, and enforcing `E501` changes what every future change must pass.

## Decision (2026-10-13)

Deferred past 0.3.0, as the release council allowed when the sweep could not be isolated: at the
release branch 240 lines exceed 99 characters (385 raw, 240 that ruff reports), almost all
f-strings and string literals that `ruff format` cannot split, so the sweep is a hand edit of
240 lines across `src/`, `tests/` and `scripts/` and would have mixed a large reformat into the
behaviour changes. `E501` stays in the ignore list for 0.3.0. `tests/test_line_length_ratchet.py`
pins the count at 240 so it can only fall; the sweep lands after the release, lowers the ceiling
to 0 and removes `E501` from the ignore list, which retires the ratchet. Markdown lines are left
as they are (tables and links wrap badly) and `CONTRIBUTING.md` says so.
