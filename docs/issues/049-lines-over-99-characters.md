---
title: "225 tracked lines are longer than the 99-character limit, and nothing enforces it"
date: 2026-10-04
status: open, decision needed
severity: low
components: [pyproject, src, tests, scripts]
found_by: docs and repo hygiene review (line-length guard)
---

# 225 tracked lines are longer than the 99-character limit, and nothing enforces it

## Problem

`pyproject.toml` sets ruff's `line-length = 99`, and the house style keeps `.py` and `.toml`
lines at 99 characters or fewer. ruff can't hold that line, though: `E501` is in the
`ignore` list, and `ruff format` doesn't split long strings or comments. At `8d51214`,
counting characters per line (not bytes), 225 tracked lines are longer:

| Area | Files | Lines over 99 characters |
| --- | ---: | ---: |
| `src/` | 44 | 172 |
| `tests/` | 7 | 36 |
| `scripts/` | 4 | 16 |
| `pyproject.toml` | 1 | 1 |

The longest is 174 characters. About 100 are f-strings (mostly log and console messages),
about 80 other string literals (help text and test fixtures), 6 comments and the rest code.
All of them predate the docs and hygiene review, which added none.

## Impact

Style only: no behaviour, test or build depends on line length. New long lines can land
unnoticed, because nothing checks them. It doesn't break fresh clones, contributors or CI.

## Decision needed

Recommendation: sweep the 225 lines (wrap strings and comments, mechanical and reviewable
file by file), then drop `E501` from the ignore list so ruff enforces the limit from then
on.

The alternative is to document the exemption: keep `E501` ignored, say in the README's
development notes that the limit applies to new code only, and check added lines in review.

Why this needs a decision: the sweep touches 56 files across `src/`, `tests/` and the site
scripts, and enforcing `E501` changes what every future change must pass.
