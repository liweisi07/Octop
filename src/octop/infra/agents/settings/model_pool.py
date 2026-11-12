"""Per-model round-robin pool configuration (switch, members, fallbacks).

Stored as one JSON blob under the ``model_pool_config`` settings key::

    {model_id: {"enabled": bool, "members": [ref, ...], "fallbacks": [ref, ...]}}

``members`` empty means "every usable ref for this model id". ``fallbacks``
is an ordered chain of model refs tried when the whole pool is unhealthy.
No new database tables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from octop.infra.db.repos.settings import SettingsRepo

_SETTINGS_KEY = "model_pool_config"


@dataclass(frozen=True)
class ModelPoolConfig:
    """Round-robin settings for one model id."""

    enabled: bool = True
    members: tuple[str, ...] = ()
    fallbacks: tuple[str, ...] = ()


def _clean_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in value:
        ref = item.strip() if isinstance(item, str) else ""
        if not ref or "/" not in ref or ref in seen:
            continue
        seen.add(ref)
        cleaned.append(ref)
    return tuple(cleaned)


def filter_pool_members(configured: tuple[str, ...], usable_refs: list[str]) -> list[str]:
    """Return the configured members that are still usable (all when unset)."""
    if not configured:
        return list(usable_refs)
    usable = set(usable_refs)
    return [ref for ref in configured if ref in usable]


class ModelPoolConfigStore:
    """Persist per-model pool settings in the settings KV store."""

    def __init__(self, *, settings_repo: SettingsRepo) -> None:
        self._settings = settings_repo

    def load(self) -> dict[str, ModelPoolConfig]:
        raw = self._settings.get(_SETTINGS_KEY)
        configs: dict[str, ModelPoolConfig] = {}
        if not raw:
            return configs
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return configs
        if not isinstance(parsed, dict):
            return configs
        for model_id, item in parsed.items():
            model_id = str(model_id).strip().lower()
            if not model_id or not isinstance(item, dict):
                continue
            configs[model_id] = ModelPoolConfig(
                enabled=bool(item.get("enabled", True)),
                members=_clean_refs(item.get("members")),
                fallbacks=_clean_refs(item.get("fallbacks")),
            )
        return configs

    def get(self, model_id: str) -> ModelPoolConfig:
        return self.load().get(model_id.strip().lower(), ModelPoolConfig())

    def save(self, configs: dict[str, ModelPoolConfig]) -> dict[str, ModelPoolConfig]:
        payload = {
            str(model_id).strip().lower(): {
                "enabled": bool(config.enabled),
                "members": list(config.members),
                "fallbacks": list(config.fallbacks),
            }
            for model_id, config in sorted(configs.items())
            if model_id.strip()
        }
        self._settings.set(_SETTINGS_KEY, json.dumps(payload, ensure_ascii=False))
        return self.load()

    def effective_pool(self, model_id: str, usable_refs: list[str]) -> list[str]:
        """Return the configured members for *model_id* (all usable when unset)."""
        return filter_pool_members(self.get(model_id).members, usable_refs)


__all__ = ["ModelPoolConfig", "ModelPoolConfigStore", "filter_pool_members"]
