"""Unit tests for model roles: primary / backup / last resort.

The three roles are generic — no model name is hard-coded. The automatic
route tries primary first, then backup, then last resort; each role is
resolved through its own pool (round-robin across every usable channel
for that model, with no cap on the pool size).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.providers.health import FailureScope
from octop.infra.agents.settings.model_roles import ModelRoles
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
        api_key="<redacted>",
        models_json=json.dumps([{"id": model_id, "name": model_id, "enabled": True}]),
    )


def _fail(manager: AgentManager, *refs: str) -> None:
    for ref in refs:
        manager._model_health.record_failure(ref, kind="timeout", scope=FailureScope.MODEL)


def _save_roles(manager: AgentManager, **kwargs: str) -> None:
    manager._model_roles.save(ModelRoles(**kwargs))


# --- store ---


def test_store_defaults_to_unset(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    assert manager._model_roles.load() == ModelRoles(primary="", backup="", last_resort="")


def test_store_save_load_roundtrip(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _save_roles(
        manager,
        primary="s1/deepseek-v4-flash",
        backup="agens/agnes-3.0-flash",
        last_resort="intern-ai/qwen",
    )

    assert manager._model_roles.load() == ModelRoles(
        primary="s1/deepseek-v4-flash",
        backup="agens/agnes-3.0-flash",
        last_resort="intern-ai/qwen",
    )


def test_store_ignores_corrupt_json(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._repos.settings_repo.set("model_roles", "{not json")

    assert manager._model_roles.load() == ModelRoles()


def test_store_cleans_bad_refs(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager._model_roles.save(
        ModelRoles(primary="plain-no-slash", backup="  agens/agnes-3.0-flash  ")
    )

    assert manager._model_roles.load() == ModelRoles(primary="", backup="agens/agnes-3.0-flash")


# --- role resolution ---


def test_unset_roles_resolve_to_none(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")

    assert manager.resolve_role_model_ref() is None


def test_primary_healthy_rotates_inside_its_pool(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _add_model(manager, "agens", "agnes-3.0-flash")
    _save_roles(manager, primary="s1/deepseek-v4-flash", backup="agens/agnes-3.0-flash")

    seen = {manager.resolve_role_model_ref() for _ in range(4)}

    assert seen == {"s1/deepseek-v4-flash", "s2/deepseek-v4-flash"}


def test_primary_pool_all_unhealthy_falls_to_backup(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _add_model(manager, "agens", "agnes-3.0-flash")
    _add_model(manager, "intern-ai", "qwen")
    _save_roles(
        manager,
        primary="s1/deepseek-v4-flash",
        backup="agens/agnes-3.0-flash",
        last_resort="intern-ai/qwen",
    )
    _fail(manager, "s1/deepseek-v4-flash", "s2/deepseek-v4-flash")

    assert manager.resolve_role_model_ref() == "agens/agnes-3.0-flash"


def test_primary_and_backup_unhealthy_falls_to_last_resort(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "agens", "agnes-3.0-flash")
    _add_model(manager, "intern-ai", "qwen")
    _save_roles(
        manager,
        primary="s1/deepseek-v4-flash",
        backup="agens/agnes-3.0-flash",
        last_resort="intern-ai/qwen",
    )
    _fail(manager, "s1/deepseek-v4-flash", "agens/agnes-3.0-flash")

    assert manager.resolve_role_model_ref() == "intern-ai/qwen"


def test_all_roles_unhealthy_resolves_to_none(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "agens", "agnes-3.0-flash")
    _add_model(manager, "intern-ai", "qwen")
    _save_roles(
        manager,
        primary="s1/deepseek-v4-flash",
        backup="agens/agnes-3.0-flash",
        last_resort="intern-ai/qwen",
    )
    _fail(manager, "s1/deepseek-v4-flash", "agens/agnes-3.0-flash", "intern-ai/qwen")

    assert manager.resolve_role_model_ref() is None


def test_backup_pool_rotates_when_primary_down(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "b1", "agnes-3.0-flash")
    _add_model(manager, "b2", "agnes-3.0-flash")
    _save_roles(manager, primary="s1/deepseek-v4-flash", backup="b1/agnes-3.0-flash")
    _fail(manager, "s1/deepseek-v4-flash")

    seen = {manager.resolve_role_model_ref() for _ in range(4)}

    assert seen == {"b1/agnes-3.0-flash", "b2/agnes-3.0-flash"}


def test_roles_feed_automatic_route(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "agens", "agnes-3.0-flash")
    _save_roles(manager, primary="s1/deepseek-v4-flash", backup="agens/agnes-3.0-flash")
    _fail(manager, "s1/deepseek-v4-flash")

    assert manager.resolve_fallback_model_ref() == "agens/agnes-3.0-flash"


# --- no cap on pool size ---


def test_large_pool_rotates_across_every_member(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    expected = {f"s{i}/deepseek-v4-flash" for i in range(1, 9)}
    for i in range(1, 9):
        _add_model(manager, f"s{i}", "deepseek-v4-flash")
    _save_roles(manager, primary="s1/deepseek-v4-flash")

    assert manager._providers.pool_refs_for("deepseek-v4-flash") == sorted(expected)
    seen = [manager.resolve_role_model_ref() for _ in range(8)]

    assert seen == sorted(expected)
    assert len(set(seen)) == 8


def test_large_pool_lists_every_member_in_view(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    for i in range(1, 9):
        _add_model(manager, f"s{i}", "deepseek-v4-flash")

    assert len(manager._providers.pool_refs_for("deepseek-v4-flash")) == 8


# --- failover candidates follow roles ---


def test_failover_candidates_order_pool_then_roles(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _add_model(manager, "s1", "deepseek-v4-flash")
    _add_model(manager, "s2", "deepseek-v4-flash")
    _add_model(manager, "agens", "agnes-3.0-flash")
    _add_model(manager, "intern-ai", "qwen")
    _add_model(manager, "other", "glm")
    _save_roles(
        manager,
        primary="s1/deepseek-v4-flash",
        backup="agens/agnes-3.0-flash",
        last_resort="intern-ai/qwen",
    )

    refs = [
        candidate.ref
        for candidate in manager._failover_candidates(
            "s1/deepseek-v4-flash", needs_multimodal=False
        )
    ]

    assert refs[:4] == [
        "s1/deepseek-v4-flash",
        "s2/deepseek-v4-flash",
        "agens/agnes-3.0-flash",
        "intern-ai/qwen",
    ]
    assert refs[-1] == "other/glm"
