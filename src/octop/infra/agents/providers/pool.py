"""Round-robin model pools: one model id, many keys or channels.

A pool is every usable ``provider/model`` ref that shares one model id —
the same model configured behind several API keys or channels (for
example ``deepseek-1/deepseek-chat`` and ``deepseek-2/deepseek-chat``).
Each turn picks the next healthy pool member so requests and rate-limit
pressure spread evenly instead of always hitting the first configured key.
"""

from __future__ import annotations

import threading

from octop.infra.agents.providers.health import ModelHealthRegistry


def pool_key_for_ref(ref: str) -> str:
    """Return the pool key for a model ref (the model id after ``/``)."""
    return ref.partition("/")[2].strip()


class ModelPoolRouter:
    """Process-local round-robin router for model pools.

    Unhealthy members (open health circuits) are skipped. When every
    member is unhealthy, :meth:`next_ref` returns ``None`` so the caller
    can keep its previous choice and let failover handle the turn.
    """

    def __init__(self, *, health: ModelHealthRegistry) -> None:
        self._health = health
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    def next_ref(self, model_id: str, refs: list[str]) -> str | None:
        """Return the next healthy ref for *model_id*, or None if none is healthy."""
        model_id = model_id.strip()
        if not model_id or not refs:
            return None
        with self._lock:
            healthy = [ref for ref in refs if self._health.is_routable(ref)]
            if not healthy:
                return None
            index = self._counters.get(model_id, 0)
            chosen = healthy[index % len(healthy)]
            self._counters[model_id] = index + 1
            return chosen


__all__ = ["ModelPoolRouter", "pool_key_for_ref"]
