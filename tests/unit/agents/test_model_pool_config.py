"""Unit tests for per-model pool config: switch, members, fallback chain."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.providers.health import FailureScope
from octop.infra.agents.settings.model_pool import (
    ModelPoolConfig,
    filter_pool_members,
)
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.utils.paths import PathLayout


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


def _fail(manager: AgentManager, *refs: str) -> None:
    for ref in refs:
        manager._model_health.record_failure(ref, kind="timeout", scope=FailureScope.MODEL)


def _save_pool(
    manager: AgentManager,
    model_id: str,
    *,
    enabled: bool = True,
    members: tuple[str, ...] = (),
    fallbacks: tuple[str, ...] = (),
) -> None:
    manager._model_pool_config.save(
        {model_id: ModelPoolConfig(enabled=enabled, members=members, fallbacks=fallbacks)}
    )


# --- store ---


def test_store_defaults_to_empty_config(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    store = manager._model_pool_config

    assert store.load() == {}
    assert store.get("deepseek-v4-flash") == ModelPoolConfig(enabled=True, members=(), fallbacks=())


def test_store_save_load_roundtrip(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    store = manager._model_pool_config
    store.save(
        {
            "deepseek-v4-flash": ModelPoolConfig(
                enabled=False,
                members=("s1/deepseek-v4-flash", "s2/deepseek-v4-flash"),
                fallbacks=("sensenova/agnes-3.0-flash", "intern-ai/qwen"),
            )
        }
    )

    assert store.load() == {
        "deepseek-v4-flash": ModelPoolConfig(
            enabled=False,
            members=("s1/deepseek-v4-flash", "s2/deepseek-v4-flash"),
            fallbacks=("sensenova/agnes-3.0-flash", "intern-ai/qwen"),
        )
    }


def test_store_ignores_corrupt_json(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._repos.settings_repo.set("model_pool_config", "{not json")

    assert manager._model_pool_config.load() == {}
    assert manager._model_pool_config.get("m") == ModelPoolConfig()


def test_store_cleans_refs_on_save(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    store = manager._model_pool_config
    store.save(
        {
            "m": ModelPoolConfig(
                members=("a/m", "no-slash", "a/m", "b/m"),
                fallbacks=("x/y", "plain"),
            )
        }
    )

    assert store.get("m") == ModelPoolConfig(members=("a/m", "b/m"), fallbacks=("x/y",))


def test_filter_pool_members() -> None:
    usable = ["s1/m", "s2/m", "s3/m"]
    assert filter_pool_members((), usable) == usable
    assert filter_pool_members(("s2/m", "s3/m"), usable) == ["s2/m", "s3/m"]
    assert filter_pool_members(("s2/m", "gone/m"), usable) == ["s2/m"]


# --- rotation respects the config ---


def test_disabled_member_never_rotates_in(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _add_model(manager, "s3", "deepseek-v4-flash")
    _save_pool(
        manager,
        "deepseek-v4-flash",
        members=("s1/deepseek-v4-flash", "s3/deepseek-v4-flash"),
    )

    seen = {manager.rotate_pool_ref("s1/deepseek-v4-flash") for _ in range(6)}

    assert seen == {"s1/deepseek-v4-flash", "s3/deepseek-v4-flash"}


def test_switch_off_pins_first_healthy_member(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _add_model(manager, "s3", "deepseek-v4-flash")
    _save_pool(manager, "deepseek-v4-flash", enabled=False)

    assert [manager.rotate_pool_ref("s2/deepseek-v4-flash") for _ in range(3)] == [
        "s1/deepseek-v4-flash",
        "s1/deepseek-v4-flash",
        "s1/deepseek-v4-flash",
    ]


def test_switch_off_skips_unhealthy_first_member(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _save_pool(manager, "deepseek-v4-flash", enabled=False)
    _fail(manager, "s1/deepseek-v4-flash")

    assert [manager.rotate_pool_ref("s1/deepseek-v4-flash") for _ in range(2)] == [
        "s2/deepseek-v4-flash",
        "s2/deepseek-v4-flash",
    ]


# --- fallback chain ---


def test_all_unhealthy_falls_back_in_order(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _add_model(manager, "sensenova", "agnes-3.0-flash")
    _add_model(manager, "intern-ai", "qwen")
    _save_pool(
        manager,
        "deepseek-v4-flash",
        fallbacks=("sensenova/agnes-3.0-flash", "intern-ai/qwen"),
    )
    _fail(manager, "s1/deepseek-v4-flash", "s2/deepseek-v4-flash")

    assert manager.rotate_pool_ref("s1/deepseek-v4-flash") == "sensenova/agnes-3.0-flash"


def test_fallback_chain_skips_unhealthy_fallback(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "sensenova", "agnes-3.0-flash")
    _add_model(manager, "intern-ai", "qwen")
    _save_pool(
        manager,
        "deepseek-v4-flash",
        fallbacks=("sensenova/agnes-3.0-flash", "intern-ai/qwen"),
    )
    _fail(manager, "s1/deepseek-v4-flash", "sensenova/agnes-3.0-flash")

    assert manager.rotate_pool_ref("s1/deepseek-v4-flash") == "intern-ai/qwen"


def test_empty_fallbacks_keeps_original_ref(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _fail(manager, "s1/deepseek-v4-flash", "s2/deepseek-v4-flash")

    assert manager.rotate_pool_ref("s1/deepseek-v4-flash") == "s1/deepseek-v4-flash"


def test_single_member_pool_uses_fallback_when_unhealthy(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "sensenova", "agnes-3.0-flash")
    _save_pool(manager, "deepseek-v4-flash", fallbacks=("sensenova/agnes-3.0-flash",))
    _fail(manager, "s1/deepseek-v4-flash")

    assert manager.rotate_pool_ref("s1/deepseek-v4-flash") == "sensenova/agnes-3.0-flash"


def test_failover_candidates_order_pool_then_fallbacks(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _add_model(manager, "sensenova", "agnes-3.0-flash")
    _add_model(manager, "other", "qwen")
    _save_pool(
        manager,
        "deepseek-v4-flash",
        fallbacks=("sensenova/agnes-3.0-flash",),
    )

    refs = [
        candidate.ref
        for candidate in manager._failover_candidates(
            "s1/deepseek-v4-flash", needs_multimodal=False
        )
    ]

    assert refs[:3] == [
        "s1/deepseek-v4-flash",
        "s2/deepseek-v4-flash",
        "sensenova/agnes-3.0-flash",
    ]
    assert refs[-1] == "other/qwen"
