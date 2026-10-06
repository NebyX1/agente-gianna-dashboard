"""A real second HTTP fixture and installed provider; the core dispatcher stays unchanged."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from gianna.tools.contracts import Tool
from gianna.adapters.base import Capability, CapabilityProvider

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def index():
    return '<!doctype html><html lang="es"><head><title>Agenda de prueba</title></head><body><h1>Agenda administrativa</h1><p data-testid="agenda-description">Reunión administrativa</p></body></html>'


@app.get("/agenda")
async def agenda():
    return {"items": [{"id": 1, "description": "Reunión administrativa", "time": "09:00"}]}


class AgendaPlugin(CapabilityProvider):
    plugin_id = "fixture.agenda"
    version = "1.0.0"
    api_version = "1"

    def __init__(self, client):
        self.client = client

    def capabilities(self):
        return [Capability("fixture_http_v1", "1", True)]

    def tools(self):
        async def read(arguments):
            r = await self.client.get("http://fixture/agenda")
            r.raise_for_status()
            return r.json()

        return [
            Tool(
                "agenda.read.v1",
                {"type": "object", "properties": {}, "additionalProperties": False},
                "Consultar la agenda de la segunda aplicación de prueba",
                "fixture_http_v1",
                ("operator",),
                ("DORMANT",),
                "read",
                "none",
                5,
                0,
                "safe",
                "Respuesta del segundo HTTP",
                read,
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["items"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["id", "description", "time"],
                                "properties": {
                                    "id": {"type": "integer"},
                                    "description": {"type": "string"},
                                    "time": {"type": "string"},
                                },
                            },
                        }
                    },
                },
            )
        ]
