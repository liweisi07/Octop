"""Model roles — which models are primary, backup, and last resort.

Three multi-selects in the dashboard; no model name is hard-coded.
Each role holds a list of models: the automatic route rotates across
the models of the primary role, then the backup role, then last resort.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from octop.api.deps import get_server, require_permission
from octop.infra.agents.providers.resolved import list_resolved_models
from octop.infra.agents.settings.model_roles import ModelRoles, ModelRolesStore

router = APIRouter()


class ModelRolesResponse(BaseModel):
    primary: list[str] = []
    backup: list[str] = []
    last_resort: list[str] = []
    available_models: list[str] = []


class ModelRolesSaveBody(BaseModel):
    primary: list[str] = []
    backup: list[str] = []
    last_resort: list[str] = []


def _store(server: Any) -> ModelRolesStore:
    return ModelRolesStore(settings_repo=server.services.settings_repo)


def _available_models(server: Any) -> list[str]:
    """Every usable chat model ref, with no cap on the count."""
    refs: list[str] = []
    for item in list_resolved_models(server.services.provider_repo.list_all()):
        model_id = str(item.get("model") or "").strip()
        provider_name = str(item.get("provider_name") or "").strip()
        if not model_id or not provider_name:
            continue
        ref = f"{provider_name}/{model_id}"
        if ref not in refs:
            refs.append(ref)
    return sorted(refs)


def _view(server: Any) -> ModelRolesResponse:
    roles = _store(server).load()
    return ModelRolesResponse(
        primary=list(roles.primary),
        backup=list(roles.backup),
        last_resort=list(roles.last_resort),
        available_models=_available_models(server),
    )


def _validate_refs(field: str, refs: list[str], available: list[str]) -> list[str]:
    """Clean one role's list; every non-empty ref must be a usable model."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        ref = ref.strip() if isinstance(ref, str) else ""
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if "/" not in ref:
            raise HTTPException(
                status_code=400,
                detail=f"{field} 的格式应为 提供商/模型，例如 sensenova/deepseek-v4-flash",
            )
        if ref not in available:
            raise HTTPException(
                status_code=400,
                detail=f"{field} 的模型 {ref} 当前不可用，请先确认该渠道已配置并启用",
            )
        cleaned.append(ref)
    return cleaned


@router.get(
    "",
    summary="List model roles and available models",
    response_model=ModelRolesResponse,
)
async def list_model_roles(
    _: Any = Depends(require_permission("providers")),
    server: Any = Depends(get_server),
) -> ModelRolesResponse:
    """Return the current primary/backup/last-resort roles and all usable models."""
    return _view(server)


@router.put(
    "",
    summary="Save model roles",
    response_model=ModelRolesResponse,
)
async def save_model_roles(
    body: ModelRolesSaveBody,
    _: Any = Depends(require_permission("providers")),
    server: Any = Depends(get_server),
) -> ModelRolesResponse:
    """Save the three roles. Every non-empty ref must be a usable model."""
    available = _available_models(server)
    roles = ModelRoles(
        primary=tuple(_validate_refs("主力模型", body.primary, available)),
        backup=tuple(_validate_refs("备用模型", body.backup, available)),
        last_resort=tuple(_validate_refs("托底模型", body.last_resort, available)),
    )
    _store(server).save(roles)
    return _view(server)
