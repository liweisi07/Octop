"""Integration tests for the model-pools API (GET/PUT /api/model-pools)."""

from __future__ import annotations

from tests.support.auth import create_provider


def _model(model_id: str) -> dict[str, object]:
    return {"id": model_id, "name": model_id, "enabled": True, "input": ["text"]}


async def _seed_pool(env) -> tuple[object, dict[str, str]]:
    client, _srv, auth = env
    for name in ("sensenova-1", "sensenova-2"):
        await create_provider(
            client,
            auth,
            name=name,
            base_url="https://api.example.com/v1",
            models=[_model("deepseek-v4-flash")],
        )
    await create_provider(
        client,
        auth,
        name="sensenova-3",
        base_url="https://api.example.com/v1",
        models=[_model("agnes-3.0-flash")],
    )
    return client, auth


async def test_list_pools_groups_same_model(env) -> None:
    client, auth = await _seed_pool(env)

    r = await client.get("/api/model-pools", headers=auth)

    assert r.status_code == 200
    pools = r.json()["pools"]
    # Only the multi-member model is a pool; the single-member model is not.
    assert [pool["model_id"] for pool in pools] == ["deepseek-v4-flash"]
    pool = pools[0]
    assert pool["enabled"] is True
    assert [member["ref"] for member in pool["members"]] == [
        "sensenova-1/deepseek-v4-flash",
        "sensenova-2/deepseek-v4-flash",
    ]
    assert all(member["enabled"] and member["usable"] for member in pool["members"])
    assert pool["fallbacks"] == []


async def test_save_pools_persists_config(env) -> None:
    client, auth = await _seed_pool(env)

    r = await client.put(
        "/api/model-pools",
        headers=auth,
        json={
            "pools": [
                {
                    "model_id": "deepseek-v4-flash",
                    "enabled": False,
                    "members": ["sensenova-1/deepseek-v4-flash"],
                    "fallbacks": ["sensenova-3/agnes-3.0-flash"],
                }
            ]
        },
    )

    assert r.status_code == 200
    pool = r.json()["pools"][0]
    assert pool["enabled"] is False
    assert [m["ref"] for m in pool["members"] if m["enabled"]] == ["sensenova-1/deepseek-v4-flash"]
    assert pool["fallbacks"] == ["sensenova-3/agnes-3.0-flash"]

    r = await client.get("/api/model-pools", headers=auth)
    assert r.status_code == 200
    assert r.json()["pools"][0]["enabled"] is False


async def test_list_pools_requires_auth(env) -> None:
    client, _srv, _auth = env

    r = await client.get("/api/model-pools")

    assert r.status_code == 401
