from __future__ import annotations

import httpx
import pytest

from helpmate.container import AdapterNotImplemented, build_container
from helpmate.main import create_app
from helpmate.settings import Settings


def test_openapi_publishes_the_chat_event_union():
    schema = create_app(Settings(_env_file=None)).openapi()
    event = schema["components"]["schemas"]["ChatEvent"]
    assert event["discriminator"]["propertyName"] == "type"
    assert set(event["discriminator"]["mapping"]) == {
        "message.delta",
        "tool.started",
        "tool.result",
        "proposal.created",
        "message.done",
        "error",
    }


@pytest.mark.parametrize(
    ("seam", "choice", "owner"),
    [("repo", "postgres", "B"), ("agent", "loop", "A"), ("notifier", "webpush", "C")],
)
def test_unimplemented_adapters_fail_loudly(seam, choice, owner):
    settings = Settings(_env_file=None, **{seam: choice})
    with pytest.raises(AdapterNotImplemented, match=f"Workstream {owner}"):
        build_container(settings)


async def test_prod_mode_serves_the_spa_with_client_side_routes(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>HelpMate</title>")
    settings = Settings(
        _env_file=None, serve_web=True, web_dist=tmp_path, scheduler_autostart=False
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert "HelpMate" in (await client.get("/")).text
            assert "HelpMate" in (await client.get("/approvals")).text  # client-side route
            assert (await client.get("/api/health")).status_code == 200
            assert (await client.get("/api/does-not-exist")).status_code == 404
