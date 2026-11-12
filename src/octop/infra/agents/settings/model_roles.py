"""Model roles: which model is primary, backup, and last resort.

Stored as one JSON blob under the ``model_roles`` settings key::

    {"primary": "provider/model", "backup": "provider/model",
     "last_resort": "provider/model"}

An empty string means "not set". No model name is hard-coded here: the
user picks any available model ref for each role in the dashboard. The
automatic route tries primary first, then backup, then last resort; each
role is resolved through its own model pool (round-robin across all of
that model's usable channels, skipping unhealthy ones), and only moves to
the next role when the whole pool is unhealthy. No new database tables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from octop.infra.db.repos.settings import SettingsRepo

_SETTINGS_KEY = "model_roles"

_ROLES = ("primary", "backup", "last_resort")


@dataclass(frozen=True)
class ModelRoles:
    """Which model ref fills each role ("" means unset)."""

    primary: str = ""
    backup: str = ""
    last_resort: str = ""


def _clean_ref(value: object) -> str:
    ref = value.strip() if isinstance(value, str) else ""
    return ref if "/" in ref else ""


class ModelRolesStore:
    """Persist the three model roles in the settings KV store."""

    def __init__(self, *, settings_repo: SettingsRepo) -> None:
        self._settings = settings_repo

    def load(self) -> ModelRoles:
        raw = self._settings.get(_SETTINGS_KEY)
        if not raw:
            return ModelRoles()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return ModelRoles()
        if not isinstance(parsed, dict):
            return ModelRoles()
        return ModelRoles(
            primary=_clean_ref(parsed.get("primary")),
            backup=_clean_ref(parsed.get("backup")),
            last_resort=_clean_ref(parsed.get("last_resort")),
        )

    def save(self, roles: ModelRoles) -> ModelRoles:
        payload = {
            "primary": _clean_ref(roles.primary),
            "backup": _clean_ref(roles.backup),
            "last_resort": _clean_ref(roles.last_resort),
        }
        self._settings.set(_SETTINGS_KEY, json.dumps(payload, ensure_ascii=False))
        return self.load()


__all__ = ["ModelRoles", "ModelRolesStore"]
