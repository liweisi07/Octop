"""Model roles: which models are primary, backup, and last resort.

Stored as one JSON blob under the ``model_roles`` settings key::

    {"primary": ["provider/model", ...], "backup": [...], "last_resort": [...]}

Each role holds a list of model refs (no cap): the automatic route
rotates across the models of the primary role, then the backup role,
then the last resort. An empty list means "not set". A single string
value is read as a one-element list for backward compatibility with
the earlier single-select format. No model name is hard-coded here:
the user picks any available model refs for each role in the dashboard.
No new database tables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from octop.infra.db.repos.settings import SettingsRepo

_SETTINGS_KEY = "model_roles"

_ROLES = ("primary", "backup", "last_resort")


@dataclass(frozen=True)
class ModelRoles:
    """Which model refs fill each role (empty tuple means unset)."""

    primary: tuple[str, ...] = ()
    backup: tuple[str, ...] = ()
    last_resort: tuple[str, ...] = ()


def _clean_refs(value: object) -> tuple[str, ...]:
    """Normalize one role value to a deduped tuple of ``provider/model`` refs.

    Accepts a list (current format) or a single string (legacy format).
    """
    items = value if isinstance(value, list) else [value]
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        ref = item.strip() if isinstance(item, str) else ""
        if not ref or "/" not in ref or ref in seen:
            continue
        seen.add(ref)
        cleaned.append(ref)
    return tuple(cleaned)


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
            primary=_clean_refs(parsed.get("primary")),
            backup=_clean_refs(parsed.get("backup")),
            last_resort=_clean_refs(parsed.get("last_resort")),
        )

    def save(self, roles: ModelRoles) -> ModelRoles:
        payload = {
            "primary": list(_clean_refs(list(roles.primary))),
            "backup": list(_clean_refs(list(roles.backup))),
            "last_resort": list(_clean_refs(list(roles.last_resort))),
        }
        self._settings.set(_SETTINGS_KEY, json.dumps(payload, ensure_ascii=False))
        return self.load()


__all__ = ["ModelRoles", "ModelRolesStore"]
