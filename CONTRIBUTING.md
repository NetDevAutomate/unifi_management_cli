# Contributing

Thank you for looking under the hood. This is a small project with a strict safety posture:
every change must keep the controller read-only unless the user asks for a write.

## Set up (clone to green in four commands)

```bash
git clone https://github.com/NetDevAutomate/unifi_management_cli.git
cd unifi_management_cli
uv sync                      # Python 3.12+; creates .venv with the dev group
uv run pre-commit install    # installs the commit AND pre-push hooks
uv run pytest -m "not live"  # ~80 s; needs no controller and no network
```

Optional tools: Graphviz `dot` for PNG/SVG diagrams (`brew install graphviz`), and
`trufflehog` for the secret-scanning hooks (`mise use -g trufflehog@3.97.6`; the hook fails
closed with an install hint when it is missing).

## The gates

`ruff check`, `ruff format --check`, `pyright src/` and `pytest -m "not live" --cov` must all
pass. The pre-push hook runs them; so does CI (`.github/workflows/ci.yml`). The coverage floor
in `pyproject.toml` is a ratchet: raise it only to a value the whole suite meets.

## Rules that are not negotiable

- **Reads become CLI commands and read-only MCP tools. Writes are CLI-only, preview by default,
  and need `--apply` (or `--no-dry-run`).** The MCP server never writes to the controller and
  never opens SSH.
- **Secrets are stripped, never masked**, from every payload that can be printed, logged or
  saved (`core/utils/redact.py`), and only the paths of what was removed are reported.
- **Fixtures use documentation values**: RFC 5737 addresses (`192.0.2.x`, `198.51.100.x`,
  `203.0.113.x`), `2001:db8::/32`, `02:00:00:…` MAC addresses and generic device names. Never
  commit output from a real controller; `reports/` and `diagrams/` are gitignored for that
  reason.
- **Tests first** for behaviour changes, and a test that pins a documented claim when you
  change documentation (`tests/test_docs_consistency.py` and `tests/test_cli_documentation.py`
  check the README and `docs/` against the code).

## Changes that touch the docs

The README's command reference and exit-code table, the MCP guide's tool index and every
documented environment variable are checked by tests. Run `uv run pytest tests/test_docs_consistency.py
tests/test_cli_documentation.py` after a docs edit; the failure message says what drifted.

## Commits and pull requests

Conventional subjects (`fix(mcp): …`, `docs: …`, `test(ports): …`), one concern per commit,
with a body that says why. Open the pull request against `main`; CI must be green. A known
problem you find but do not fix goes in `docs/issues/` (see its README) rather than a TODO.
