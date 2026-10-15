"""The worker budget's permit always comes back (council pass C, lens 1).

``run_blocking`` takes a permit before starting the thread and the thread returns it when the
handler ends. If the thread cannot be started at all (the interpreter refuses a new thread
under resource exhaustion), nothing would run ``finally``; the permit must come back from the
start path instead, or every such failure would shrink the budget for the life of the server.
"""

from __future__ import annotations

import asyncio
import pytest
import threading
from unifi_mapper.core.utils import workers


def test_a_thread_start_failure_returns_the_permit_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = workers.configure_worker_budget(1)

    class Unstartable(threading.Thread):
        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(workers.threading, 'Thread', Unstartable)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="can't start new thread"):
            await workers.run_blocking(lambda: None)

    asyncio.run(scenario())
    assert budget.borrowed == 0, 'the permit taken for the failed start was not returned'
    assert budget.try_acquire(), 'the budget must be whole again'
    budget.release()
