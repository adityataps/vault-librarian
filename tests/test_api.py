from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import src.config as _cfg_module


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.mark.asyncio
async def test_status_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("LIBRARIAN_LLM_API_KEY", "test")
    monkeypatch.setenv("LIBRARIAN_SECRET", "secret")
    _cfg_module._instance = None

    db_mock = AsyncMock()
    db_mock.initialize = AsyncMock()
    db_mock.close = AsyncMock()

    with (
        patch("src.api.app.build_db", return_value=db_mock),
        patch("src.api.app.build_llm", return_value=MagicMock()),
        patch("src.api.app.build_embedder", return_value=MagicMock()),
        patch("src.api.app.VectorStore", return_value=MagicMock()),
        patch("src.api.app.VaultTools", return_value=MagicMock()),
        patch("src.api.app.PipelineRunner", return_value=MagicMock()),
        patch("src.api.app.Dispatcher", return_value=MagicMock(reconcile=AsyncMock())),
        patch(
            "src.api.app.VaultWatcher", return_value=MagicMock(start=MagicMock(), stop=MagicMock())
        ),
        patch("src.api.app.VaultConfigLoader", return_value=MagicMock(apply=MagicMock())),
    ):
        from src.api.app import create_app

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "vault" in data
    assert "enrolled_agents" in data


@pytest.mark.asyncio
async def test_webhook_requires_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("LIBRARIAN_LLM_API_KEY", "test")
    monkeypatch.setenv("LIBRARIAN_SECRET", "my-secret")
    _cfg_module._instance = None

    db_mock = AsyncMock()
    db_mock.initialize = AsyncMock()
    db_mock.close = AsyncMock()

    with (
        patch("src.api.app.build_db", return_value=db_mock),
        patch("src.api.app.build_llm", return_value=MagicMock()),
        patch("src.api.app.build_embedder", return_value=MagicMock()),
        patch("src.api.app.VectorStore", return_value=MagicMock()),
        patch("src.api.app.VaultTools", return_value=MagicMock()),
        patch("src.api.app.PipelineRunner", return_value=MagicMock()),
        patch("src.api.app.Dispatcher", return_value=MagicMock(reconcile=AsyncMock())),
        patch(
            "src.api.app.VaultWatcher", return_value=MagicMock(start=MagicMock(), stop=MagicMock())
        ),
        patch("src.api.app.VaultConfigLoader", return_value=MagicMock(apply=MagicMock())),
    ):
        from src.api.app import create_app

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp_no_secret = await client.post("/webhook/git")
            resp_wrong_secret = await client.post(
                "/webhook/git", headers={"X-Librarian-Secret": "wrong"}
            )
            resp_correct = await client.post(
                "/webhook/git", headers={"X-Librarian-Secret": "my-secret"}
            )

    assert resp_no_secret.status_code == 401
    assert resp_wrong_secret.status_code == 401
    assert resp_correct.status_code == 200
