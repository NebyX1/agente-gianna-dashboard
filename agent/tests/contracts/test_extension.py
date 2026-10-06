import httpx
import pytest
from types import SimpleNamespace
from gianna.tools.registry import ToolRegistry
from gianna.tools.dispatcher import Dispatcher
from tests.fixtures.second_app import AgendaPlugin, app
from gianna.profiles.loader import load_profile


async def test_second_web_application_through_installed_provider():
    registry = ToolRegistry()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        plugin = AgendaPlugin(client)
        with pytest.raises(ValueError, match="allowlisted"):
            registry.install(plugin, allowlist=set())
        plugin.api_version = "2"
        with pytest.raises(ValueError, match="Incompatible"):
            registry.install(plugin, allowlist={(plugin.plugin_id, plugin.version)})
        plugin.api_version = "1"
        registry.install(plugin, allowlist={(plugin.plugin_id, plugin.version)})
        profile = load_profile("fixture-agenda", registry)
        assert profile["tools"] == ["agenda.read.v1"]
        dispatcher = Dispatcher(registry)
        context = SimpleNamespace(
            capabilities={"fixture_http_v1"}, state="DORMANT", role="operator"
        )
        result = await dispatcher.call(profile["tools"][0], {}, context)
        surface = await client.get("http://fixture/")
        assert "<h1>Agenda administrativa</h1>" in surface.text
        assert result["items"][0]["description"] == "Reunión administrativa"
        context.role = "viewer"
        with pytest.raises(RuntimeError, match="unavailable"):
            await dispatcher.call("agenda.read.v1", {}, context)
