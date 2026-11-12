"""Model pool router — per-model round-robin switch, members, fallback chain."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.agents.providers.resolved import list_resolved_models
from octop.infra.agents.settings.model_pool import (
    ModelPoolConfig,
    ModelPoolConfigStore,
    filter_pool_members,
)

router = APIRouter()


class PoolMemberItem(BaseModel):
    ref: str
    enabled: bool
    usable: bool = True


class ModelPoolItem(BaseModel):
    model_id: str
    enabled: bool
    members: list[PoolMemberItem]
    fallbacks: list[str]


class ModelPoolsResponse(BaseModel):
    pools: list[ModelPoolItem]


class ModelPoolSaveItem(BaseModel):
    model_id: str
    enabled: bool = True
    members: list[str] = Field(default_factory=list)
    fallbacks: list[str] = Field(default_factory=list)


class ModelPoolsSaveBody(BaseModel):
    pools: list[ModelPoolSaveItem] = Field(default_factory=list)


def _store(server: Any) -> ModelPoolConfigStore:
    return ModelPoolConfigStore(settings_repo=server.services.settings_repo)


def _pool_view(server: Any) -> list[ModelPoolItem]:
    """Build the pool list: every multi-member model, plus saved configs."""
    store = _store(server)
    saved = store.load()
    by_model: dict[str, list[str]] = {}
    for item in list_resolved_models(server.services.provider_repo.list_all()):
        model_id = str(item.get("model") or "").strip()
        provider_name = str(item.get("provider_name") or "").strip()
        if not model_id or not provider_name:
            continue
        ref = f"{provider_name}/{model_id}"
        by_model.setdefault(model_id, [])
        if ref not in by_model[model_id]:
            by_model[model_id].append(ref)
    model_ids = sorted(set(by_model) | set(saved))
    pools: list[ModelPoolItem] = []
    for model_id in model_ids:
        usable = by_model.get(model_id, [])
        config = saved.get(model_id, ModelPoolConfig())
        effective = filter_pool_members(config.members, usable)
        members = [PoolMemberItem(ref=ref, enabled=ref in effective, usable=True) for ref in usable]
        # Keep explicitly configured members that are not usable right now
        # visible so the user can uncheck them instead of losing the choice.
        known = {item.ref for item in members}
        for ref in config.members:
            if ref not in known:
                members.append(PoolMemberItem(ref=ref, enabled=True, usable=False))
                known.add(ref)
        if len(usable) <= 1 and model_id not in saved:
            continue
        pools.append(
            ModelPoolItem(
                model_id=model_id,
                enabled=config.enabled,
                members=members,
                fallbacks=list(config.fallbacks),
            )
        )
    return pools


@router.get(
    "",
    summary="List model pools and their round-robin config",
    response_model=ModelPoolsResponse,
)
async def list_model_pools(
    _: Any = Depends(require_permission("providers")),
    server: Any = Depends(get_server),
) -> ModelPoolsResponse:
    """Return every multi-member model pool with its switch, members, fallbacks."""
    return ModelPoolsResponse(pools=_pool_view(server))


@router.put(
    "",
    summary="Save model pool round-robin config",
    response_model=ModelPoolsResponse,
)
async def save_model_pools(
    body: ModelPoolsSaveBody,
    _: Any = Depends(require_permission("providers")),
    server: Any = Depends(get_server),
) -> ModelPoolsResponse:
    """Replace the saved pool config with the submitted pools."""
    configs = {
        item.model_id.strip(): ModelPoolConfig(
            enabled=bool(item.enabled),
            members=tuple(dict.fromkeys(ref.strip() for ref in item.members if "/" in ref.strip())),
            fallbacks=tuple(
                dict.fromkeys(ref.strip() for ref in item.fallbacks if "/" in ref.strip())
            ),
        )
        for item in body.pools
        if item.model_id.strip()
    }
    _store(server).save(configs)
    return ModelPoolsResponse(pools=_pool_view(server))
