"""The fenced-code-block parser the docs tests share, so a fix to it lands in one place."""

from __future__ import annotations

import re
from collections.abc import Iterator


FENCE_OPEN = re.compile(r'(`{3,}|~{3,})([^`]*)$')


def code_blocks(text: str) -> Iterator[tuple[int, str, list[str]]]:
    """Yield ``(first body line, info string, body lines)`` for each fenced code block.

    Every opening fence pairs with its own closing fence, whatever the info string (``bash``,
    ``text``, ``json`` ...). A regex that only knows ``bash`` blocks pairs a ``text`` block's
    closing fence with the next block's opening fence, which silently turns every later block
    inside out.

    Args:
        text: Markdown text.

    Yields:
        One tuple per block, line numbers 1-based. A fence that is never closed runs to the
        end of the text, as in CommonMark, so its lines are still checked.
    """
    fence: str | None = None
    info, start, body = '', 0, []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if fence is None:
            opening = FENCE_OPEN.match(stripped)
            if opening:
                fence, info, start, body = opening.group(1), opening.group(2).strip(), n + 1, []
        elif stripped.startswith(fence) and not stripped.strip(fence[0]):
            yield start, info, body
            fence = None
        else:
            body.append(line)
    if fence is not None:
        yield start, info, body
