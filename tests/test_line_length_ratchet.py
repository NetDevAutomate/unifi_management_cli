"""The long-line count can only fall (issue 049).

``E501`` stays in ruff's ignore list for 0.3.0: the 240 lines over 99 characters are almost all
f-strings and string literals that ``ruff format`` cannot split, and the release council deferred
the hand sweep to after the release rather than mix a 240-line reformat into the behaviour
changes. This ratchet keeps the debt from growing in the meantime: a change that adds a long
line fails here, and when the sweep lands the ceiling drops with it (and ``E501`` leaves the
ignore list, which makes this test redundant).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
# The measured count at the 0.3.0 release branch. Lower it when you remove long lines; never
# raise it.
E501_CEILING = 240


def _e501_count() -> int:
    result = subprocess.run(
        [
            'uv',
            'run',
            'ruff',
            'check',
            '--select',
            'E501',
            '--no-fix',
            '--output-format',
            'concise',
            '.',
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return sum(1 for line in result.stdout.splitlines() if ': E501 ' in line)


def test_the_number_of_lines_over_99_characters_does_not_grow() -> None:
    count = _e501_count()
    assert count <= E501_CEILING, (
        f'{count} lines exceed 99 characters, above the ceiling of {E501_CEILING}: wrap the new '
        'ones (issue 049), or lower the ceiling if you removed some'
    )
