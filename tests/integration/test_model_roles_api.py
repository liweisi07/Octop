"""Integration tests for the model-roles API (GET/PUT /api/model-roles)."""

from __future__ import annotations

from tests.support.auth import create_provider


def _model(model_id: str) -> dict[str, object]:
    return {"id": model_id, "name": model_id, "enabled": True, "input": ["text"]}


async def _seed(env) -> tuple[object, dict[str, str]]:
    client, _srv, auth = env
    for i in range(1, 9):
        await create_provider(
            client,
            auth,
            name=f"sensenova-{i}",
            base_url="https://api.example.com/v1",
            models=[_model("deepseek-v4-flash")],
        )
    await create_provider(
        client,
        auth,
        name="agens",
        base_url="https://api.example.com/v1",
        models=[_model("agnes-3.0-flash")],
    )
    await create_provider(
        client,
        auth,
        name="intern-ai",
        base_url="https://api.example.com/v1",
        models=[_model("qwen")],
    )
    return client, auth


async def test_list_roles_returns_all_available_models(env) -> None:
    client, auth = await _seed(env)

    r = await client.get("/api/model-roles", headers=auth)

    assert r.status_code == 200
    body = r.json()
    assert body["primary"] == ""
    assert body["backup"] == ""
    assert body["last_resort"] == ""
    # No cap: all 8 channels for the same model are listed.
    assert [ref for ref in body["available_models"] if ref.endswith("deepseek-v4-flash")] == [
        f"sensenova-{i}/deepseek-v4-flash" for i in range(1, 9)
    ]
    assert "agens/agnes-3.0-flash" in body["available_models"]
    assert "intern-ai/qwen" in body["available_models"]


async def test_save_roles_persists(env) -> None:
    client, auth = await _seed(env)

    r = await client.put(
        "/api/model-roles",
        headers=auth,
        json={
            "primary": "sensenova-1/deepseek-v4-flash",
            "backup": "agens/agnes-3.0-flash",
            "last_resort": "intern-ai/qwen",
        },
    )

    assert r.status_code == 200
    assert r.json()["primary"] == "sensenova-1/deepseek-v4-flash"
    assert r.json()["backup"] == "agens/agnes-3.0-flash"
    assert r.json()["last_resort"] == "intern-ai/qwen"

    r = await client.get("/api/model-roles", headers=auth)
    assert r.status_code == 200
    assert r.json()["primary"] == "sensenova-1/deepseek-v4-flash"


async def test_save_roles_rejects_unavailable_model(env) -> None:
    client, auth = await _seed(env)

    r = await client.put(
        "/api/model-roles",
        headers=auth,
        json={"primary": "gone/no-such-model", "backup": "", "last_resort": ""},
    )

    assert r.status_code == 400
    assert "gone/no-such-model" in r.text


async def test_save_roles_rejects_bad_format(env) -> None:
    client, auth = await _seed(env)

    r = await client.put(
        "/api/model-roles",
        headers=auth,
        json={"primary": "no-slash-here", "backup": "", "last_resort": ""},
    )

    assert r.status_code == 400


async def test_list_roles_requires_auth(env) -> None:
    client, _srv, _auth = env

    r = await client.get("/api/model-roles")

    assert r.status_code == 401
