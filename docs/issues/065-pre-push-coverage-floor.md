---
title: "The pre-push pytest hook fails the 90% coverage floor"
date: 2026-10-05
status: open, decision needed
severity: medium
components: [.pre-commit-config.yaml, pyproject.toml]
found_by: July port planning (baseline measured at 3d49fbd)
---

# The pre-push pytest hook fails the 90% coverage floor

## Problem

`.pre-commit-config.yaml`'s pre-push `pytest` hook runs
`uv run pytest -m "not live" --cov --cov-branch --cov-report=term-missing`. With `--cov`,
pytest-cov reads `[tool.coverage.report] fail_under = 90` from `pyproject.toml`. The measured
total at `3d49fbd` is 57.63% branch coverage (3073 tests passed), so the hook fails on every
push from a host that has the pre-commit hooks installed.

## Impact

Breaks fresh clones, CI or prod: **yes, where the pre-push hook is installed**: `git push`
fails on coverage although every test passes. Hosts without the installed hook are not
affected.

## Decision needed

It changes a gate, so it is a decision. Recommendation: set `fail_under` to the measured
floor (57) and ratchet it up as coverage grows, so the hook guards against regressions
without blocking every push. The alternative is to drop `--cov` from the hook and keep
coverage as a report only.
