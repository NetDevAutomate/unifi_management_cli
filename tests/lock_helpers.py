"""Hold a capped file's lock the way another local account can, and run a writer against it.

Shared by the writer's tests (``tests/utility/test_jsonl.py``) and the MCP call log's
(``tests/mcp/test_call_audit.py``), final-fix VS-1: a lock held on a read-only descriptor
must never stall a write for longer than its limit. The writer runs in a daemon thread with
a join timeout, so a regression fails the test instead of hanging the suite.
"""

import fcntl
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@contextmanager
def umask(mask: int) -> Iterator[None]:
    """Run the block under ``mask``, then restore the process's umask.

    Args:
        mask: The umask to set.

    Yields:
        Nothing.
    """
    old = os.umask(mask)
    try:
        yield
    finally:
        os.umask(old)


@contextmanager
def held_read_only(lock: Path) -> Iterator[None]:
    """Hold ``LOCK_EX`` on an ``O_RDONLY`` descriptor of ``lock``, as the VS-1 probe did.

    Read access is all ``flock`` needs, so any account that can open the lock file can hold
    it. The lock file is created first when it is missing. The lock is released, and the
    descriptor closed, when the block ends, also when it fails.

    Args:
        lock: The ``<file>.lock`` to hold.

    Yields:
        Nothing.
    """
    if not lock.exists():
        lock.touch()
    fd = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@dataclass
class Outcome:
    """How a call run by :func:`run_bounded` ended.

    Attributes:
        done: Whether it returned or raised before the join timeout.
        elapsed: Seconds it took (the join timeout when it was not done).
        result: What it returned.
        error: What it raised, or None.
    """

    done: bool
    elapsed: float
    result: object = None
    error: BaseException | None = None


def run_bounded(call: Callable[[], object], join_s: float) -> Outcome:
    """Run ``call`` in a daemon thread and wait for it for at most ``join_s`` seconds.

    Args:
        call: What to run.
        join_s: How long to wait for it; a call still running then is reported not done.

    Returns:
        How it ended.
    """
    ended: list[Outcome] = []

    def _run() -> None:
        started = time.monotonic()
        try:
            result = call()
        except BaseException as e:  # noqa: BLE001 - reported to the test, which asserts on it
            ended.append(Outcome(True, time.monotonic() - started, error=e))
        else:
            ended.append(Outcome(True, time.monotonic() - started, result=result))

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(join_s)
    return ended[0] if ended else Outcome(done=False, elapsed=join_s)
