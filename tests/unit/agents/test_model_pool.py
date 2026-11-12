"""Unit tests for round-robin model pools (one model id, many keys/channels)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.providers import ProviderStore
from octop.infra.agents.providers.health import FailureScope, ModelHealthRegistry
from octop.infra.agents.providers.pool import ModelPoolRouter, pool_key_for_ref
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.utils.paths import PathLayout


def test_pool_key_for_ref() -> None:
    assert pool_key_for_ref("deepseek/deepseek-chat") == "deepseek-chat"
    assert pool_key_for_ref("deepseek-chat") == ""
    assert pool_key_for_ref("") == ""
    # Same model spelled with different casing behind different channels
    # must land in one pool.
    assert pool_key_for_ref("AMD/DeepSeek-V4-Flash") == "deepseek-v4-flash"
    assert pool_key_for_ref("sensenova/deepseek-v4-flash") == "deepseek-v4-flash"


def test_next_ref_rotates_across_healthy_members() -> None:
    health = ModelHealthRegistry(clock=lambda: 100.0)
    router = ModelPoolRouter(health=health)
    refs = ["p1/m", "p2/m", "p3/m"]

    assert [router.next_ref("m", refs) for _ in range(5)] == [
        "p1/m",
        "p2/m",
        "p3/m",
        "p1/m",
        "p2/m",
    ]


def test_next_ref_skips_unhealthy_members() -> None:
    health = ModelHealthRegistry(clock=lambda: 100.0)
    router = ModelPoolRouter(health=health)
    health.record_failure("p2/m", kind="timeout", scope=FailureScope.MODEL)
    refs = ["p1/m", "p2/m", "p3/m"]

    assert [router.next_ref("m", refs) for _ in range(4)] == [
        "p1/m",
        "p3/m",
        "p1/m",
        "p3/m",
    ]


def test_next_ref_returns_none_when_all_unhealthy() -> None:
    health = ModelHealthRegistry(clock=lambda: 100.0)
    router = ModelPoolRouter(health=health)
    health.record_failure("p1/m", kind="timeout", scope=FailureScope.MODEL)
    health.record_failure("p2/m", kind="timeout", scope=FailureScope.MODEL)

    assert router.next_ref("m", ["p1/m", "p2/m"]) is None


def test_next_ref_returns_none_for_empty() -> None:
    health = ModelHealthRegistry(clock=lambda: 100.0)
    router = ModelPoolRouter(health=health)

    assert router.next_ref("m", []) is None
    assert router.next_ref("", ["p1/m"]) is None


@pytest.fixture
def store(tmp_path: Path) -> ProviderStore:
    paths = PathLayout(tmp_path / ".octop")
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=OctopConfig())
    return ProviderStore(provider_repo=services.repos.provider_repo)


def _add_provider(
    store: ProviderStore,
    name: str,
    model_id: str,
    *,
    enabled: bool = True,
    api_key: str | None = "sk-test",
) -> None:
    pid = store._provider_repo.create(
        name=name,
        kind="openai",
        base_url="https://api.example.com/v1",
        api_key=api_key,
        models_json=json.dumps([{"id": model_id, "name": model_id, "enabled": True}]),
    )
    if not enabled:
        store._provider_repo.update(pid, enabled=False)


def test_pool_refs_for_groups_same_model_across_providers(store: ProviderStore) -> None:
    _add_provider(store, "deepseek-1", "deepseek-chat")
    _add_provider(store, "deepseek-2", "deepseek-chat")
    _add_provider(store, "other", "qwen-max")

    assert store.pool_refs_for("deepseek-chat") == [
        "deepseek-1/deepseek-chat",
        "deepseek-2/deepseek-chat",
    ]
    assert store.pool_refs_for("qwen-max") == ["other/qwen-max"]
    assert store.pool_refs_for("nope") == []
    assert store.pool_refs_for("") == []


def test_pool_refs_for_groups_case_insensitively(store: ProviderStore) -> None:
    # Real-world case: AMD spells it "DeepSeek-V4-Flash", sensenova
    # "deepseek-v4-flash". One pool, refs keep their stored casing.
    _add_provider(store, "AMD", "DeepSeek-V4-Flash")
    _add_provider(store, "sensenova", "deepseek-v4-flash")

    assert store.pool_refs_for("deepseek-v4-flash") == [
        "AMD/DeepSeek-V4-Flash",
        "sensenova/deepseek-v4-flash",
    ]
    assert store.pool_refs_for("DeepSeek-V4-Flash") == [
        "AMD/DeepSeek-V4-Flash",
        "sensenova/deepseek-v4-flash",
    ]


def test_pool_refs_for_ignores_unusable_rows(store: ProviderStore) -> None:
    _add_provider(store, "good", "m")
    _add_provider(store, "disabled", "m", enabled=False)
    _add_provider(store, "no-key", "m", api_key=None)

    assert store.pool_refs_for("m") == ["good/m"]


def _manager(tmp_path: Path) -> AgentManager:
    db = SqlitePool(tmp_path / "x.db")
    run_migrations(db)
    services = build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())
    manager = AgentManager(repos=services.repos, paths=services.paths)
    manager._harness_manager = MagicMock()
    return manager


def _add_model(manager: AgentManager, provider_name: str, model_id: str) -> None:
    manager._providers._provider_repo.create(
        name=provider_name,
        kind="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        models_json=json.dumps([{"id": model_id, "name": model_id, "enabled": True}]),
    )


def test_resolve_fallback_model_ref_rotates_pool(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "deepseek-1", "deepseek-chat")
    _add_model(manager, "deepseek-2", "deepseek-chat")

    assert [manager.resolve_fallback_model_ref() for _ in range(4)] == [
        "deepseek-1/deepseek-chat",
        "deepseek-2/deepseek-chat",
        "deepseek-1/deepseek-chat",
        "deepseek-2/deepseek-chat",
    ]


def test_rotate_pool_ref_keeps_single_member(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "only", "solo")

    assert manager.rotate_pool_ref("only/solo") == "only/solo"
    assert manager.rotate_pool_ref("only/solo") == "only/solo"


def test_resolve_fallback_model_ref_skips_unhealthy_pool_member(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "deepseek-1", "deepseek-chat")
    _add_model(manager, "deepseek-2", "deepseek-chat")
    manager._model_health.record_failure(
        "deepseek-1/deepseek-chat", kind="timeout", scope=FailureScope.MODEL
    )

    assert [manager.resolve_fallback_model_ref() for _ in range(2)] == [
        "deepseek-2/deepseek-chat",
        "deepseek-2/deepseek-chat",
    ]
