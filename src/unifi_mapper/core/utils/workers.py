"""The MCP server's worker-thread budget: one bound for every blocking hop (issue 090).

Two kinds of handler block a thread: a synchronous catalog handler, which the runner hops
itself, and an async port-diagnostics wrapper, which hops its own collector through
:func:`run_blocking`. Both must draw on ONE budget, sized to ``UNIFI_MCP_MAX_CONCURRENCY``,
and a permit must stay occupied until the worker thread actually exits, not until the caller
stops waiting: when the deadline abandons a worker, the caller returns at once but the thread
is still running against the controller, and the next call must not start another one in its
place beyond the bound. anyio's ``CapacityLimiter`` releases its token when the *awaiting task*
leaves the ``async with``, which on abandonment is before the thread ends, so the permit here is
a plain :class:`threading.BoundedSemaphore` released by the worker itself in ``finally``.

The budget is also never anyio's default thread pool, which the MCP stdio transport reads
stdin through: a wedged controller must not be able to stall request reading.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar


T = TypeVar('T')


@dataclass
class WorkerBudget:
    """``limit`` permits; a permit is held from thread start to thread exit."""

    limit: int
    _permits: threading.BoundedSemaphore = field(init=False, repr=False)
    _borrowed: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        """Create the permits; a budget needs at least one."""
        if self.limit < 1:
            raise ValueError('a worker budget needs at least one permit')
        self._permits = threading.BoundedSemaphore(self.limit)

    @property
    def borrowed(self) -> int:
        """Permits currently held by running (or abandoned, still running) workers."""
        with self._lock:
            return self._borrowed

    def try_acquire(self) -> bool:
        """Take a permit without blocking; False when every permit is held."""
        if not self._permits.acquire(blocking=False):
            return False
        with self._lock:
            self._borrowed += 1
        return True

    def release(self) -> None:
        """Give a permit back; called by the worker thread itself when it exits."""
        with self._lock:
            self._borrowed -= 1
        self._permits.release()


_BUDGET: WorkerBudget | None = None
_BUDGET_LOCK = threading.Lock()
DEFAULT_LIMIT = 4


def configure_worker_budget(limit: int) -> WorkerBudget:
    """Size the process budget (the server calls this from its settings at start)."""
    global _BUDGET
    with _BUDGET_LOCK:
        _BUDGET = WorkerBudget(limit)
        return _BUDGET


def worker_budget() -> WorkerBudget:
    """The process budget, created at :data:`DEFAULT_LIMIT` if the server never sized it."""
    global _BUDGET
    with _BUDGET_LOCK:
        if _BUDGET is None:
            _BUDGET = WorkerBudget(DEFAULT_LIMIT)
        return _BUDGET


async def run_blocking(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run ``fn`` in a worker thread under the process budget, abandoning it on cancellation.

    Waits (cancellably) for a permit, then starts the thread. If the awaiting task is cancelled
    while the thread runs (the deadline), the caller returns at once; the thread keeps its
    permit until ``fn`` returns, then releases it. The calling context (contextvars) is copied
    into the thread, as :func:`asyncio.to_thread` does.
    """
    budget = worker_budget()
    while not budget.try_acquire():
        await asyncio.sleep(0.005)  # cancellable wait for a permit
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()
    context = contextvars.copy_context()

    def _resolve(setter: Callable[[], None]) -> None:
        if not future.done():  # an abandoned caller's future is already cancelled
            setter()

    def _deliver(setter: Callable[[], None]) -> None:
        try:
            loop.call_soon_threadsafe(_resolve, setter)
        except RuntimeError:  # the loop closed while the abandoned worker was still running
            pass

    def _worker() -> None:
        try:
            result = context.run(functools.partial(fn, *args, **kwargs))
        except BaseException as e:  # noqa: BLE001 - every outcome crosses the thread boundary
            _deliver(functools.partial(future.set_exception, e))
        else:
            _deliver(functools.partial(future.set_result, result))
        finally:
            budget.release()

    try:
        threading.Thread(target=_worker, name='unifi-mcp-worker', daemon=True).start()
    except BaseException:
        # The thread never ran, so its finally never will: the permit comes back from here.
        budget.release()
        raise
    return await future
