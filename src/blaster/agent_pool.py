"""Exclusive destination reservations on the engine's asyncio loop."""

from __future__ import annotations

import asyncio
import random
from typing import Literal

AgentStrategy = Literal["round_robin", "random", "priority"]


class AgentPool:
    def __init__(self, store, on_change=None):
        self.store = store
        self.on_change = on_change
        self.busy: dict[str, str] = {}  # dialed number -> job id (global across trunks)
        self.aliases: dict[str, str] = {}
        self.pending: list[str] = []
        self.changed = asyncio.Event()
        self.guards: set[asyncio.Task] = set()
        self.closing: set[str] = set()

    def _notify(self):
        self.changed.set()
        self.changed = asyncio.Event()
        if self.on_change:
            self.on_change()

    def availability(self, numbers):
        """Return free configured destinations, including dial-format aliases."""
        configured = list(dict.fromkeys(numbers))
        reserved = {self.aliases.get(number, number) for number in self.busy}
        free = [number for number in configured if number not in reserved]
        return {
            "total": len(configured),
            "busy": len(configured) - len(free),
            "free": free,
        }

    async def acquire(self, owner, campaign_id, numbers, strategy, timeout, on_wait, aliases=None):
        deadline = asyncio.get_running_loop().time() + timeout
        self.pending.append(owner)
        waiting = False
        try:
            while True:
                wake = self.changed
                free = [n for n in numbers if n not in self.busy]
                if self.pending[0] == owner and free:
                    if strategy == "random":
                        number = random.choice(free)
                    elif strategy == "priority":
                        number = free[0]
                    else:
                        cursor = self.store.campaign(campaign_id)["agent_cursor"] % len(numbers)
                        ordered = numbers[cursor:] + numbers[:cursor]
                        number = next(n for n in ordered if n in free)
                    # No await between selection and reservation: concurrent transfers
                    # cannot claim the same destination, including while waiting for CPS.
                    self.busy[number] = owner
                    self.aliases[number] = (aliases or {}).get(number, number)
                    self.store.set_agent_cursor(
                        campaign_id, (numbers.index(number) + 1) % len(numbers)
                    )
                    return number
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return None
                if not waiting:
                    on_wait()
                    waiting = True
                try:
                    await asyncio.wait_for(wake.wait(), remaining)
                except TimeoutError:
                    return None
        finally:
            self.pending.remove(owner)
            self._notify()

    def release(self, owner):
        for number in [n for n, job in self.busy.items() if job == owner]:
            del self.busy[number]
            self.aliases.pop(number, None)
        self._notify()

    def release_after_close(self, owner, leg):
        if owner not in self.busy.values() or owner in self.closing:
            return
        if leg is None or leg.closed.is_set():
            self.release(owner)
            return

        async def confirmed():
            try:
                await leg.closed.wait()
                self.release(owner)
            finally:
                self.closing.discard(owner)

        # A failed hangup is not evidence of availability. Keep the number reserved
        # until the SIP disconnection is observed or the whole endpoint is stopped.
        self.closing.add(owner)
        task = asyncio.create_task(confirmed())
        self.guards.add(task)
        task.add_done_callback(self.guards.discard)

    async def close(self):
        for task in self.guards:
            task.cancel()
        await asyncio.gather(*self.guards, return_exceptions=True)
        self.busy.clear()
        self.aliases.clear()
