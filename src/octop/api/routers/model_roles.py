"""Model roles — which model is primary, backup, and last resort.

Three dropdowns in the dashboard; no model name is hard-coded. The
automatic route tries primary first, then backup, then last resort.
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
    primary: str = ""
    backup: str = ""
    last_resort: str = ""
    available_models: list[str] = []


class ModelRolesSaveBody(BaseModel):
    primary: str = ""
    backup: str = ""
    last_resort: str = ""


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
        primary=roles.primary,
        backup=roles.backup,
        last_resort=roles.last_resort,
        available_models=_available_models(server),
    )


def _validate_ref(field: str, ref: str, available: list[str]) -> str:
    ref = ref.strip()
    if not ref:
        return ""
    if "/" not in ref:
        raise HTTPException(
            status_code=400,
            detail=f"{field} 的格式应为 提供商/模型，例如 sensenova/deepseek-v4-flash",
        )
    if ref not in available:
        raise HTTPException(
            status_code=400, detail=f"{field} 的模型 {ref} 当前不可用，请先确认该渠道已配置并启用"
        )
    return ref


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
    """Save the three roles. A non-empty ref must be a usable model."""
    available = _available_models(server)
    roles = ModelRoles(
        primary=_validate_ref("主力模型", body.primary, available),
        backup=_validate_ref("备用模型", body.backup, available),
        last_resort=_validate_ref("托底模型", body.last_resort, available),
    )
    _store(server).save(roles)
    return _view(server)
