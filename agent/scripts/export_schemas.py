"""Export real installed contracts without starting transports or granting authority."""

import argparse
from dataclasses import fields
import json
from gianna.config import ROOT
from gianna.tools.registry import ToolRegistry
from gianna.tools.tickets import install_tools
from gianna.models.ollama_cloud import Proposal
from gianna.server.app import Command, Playback, Preferences
from gianna.adapters.tickets_http import TicketsHTTP
from gianna.config import Settings
from gianna.runtime.errors import ErrorCode


def outputs():
    registry = ToolRegistry()
    install_tools(
        registry, TicketsHTTP(Settings(), None), None, None
    )  # Metadata only; never call a handler.
    catalog = [
        {f.name: getattr(tool, f.name) for f in fields(tool) if f.name != "handler"}
        for tool in registry.tools.values()
    ]
    event = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "event_id",
            "kind",
            "session_id",
            "turn_id",
            "generation_id",
            "at",
            "data",
        ],
        "properties": {
            "schema_version": {"const": "1"},
            "event_id": {"type": "string", "format": "uuid"},
            "kind": {"type": "string", "pattern": "^[a-z_]+$"},
            "session_id": {"type": "string"},
            "turn_id": {"type": "string"},
            "generation_id": {"type": "string"},
            "at": {"type": "string", "format": "date-time"},
            "data": {"type": "object"},
        },
    }
    contract = json.loads(
        (ROOT / "contracts/tickets-openapi.snapshot.json").read_text(encoding="utf-8")
    )
    receipt = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/components/schemas/AgentReceipt",
        "components": contract["components"],
    }
    return {
        "contracts/tools.catalog.json": {"schema_version": "1", "tools": catalog},
        "schemas/events.schema.json": event,
        "schemas/errors.schema.json": {"type": "string", "enum": list(ErrorCode)},
        "schemas/operation-receipt.schema.json": receipt,
        "schemas/command.schema.json": Command.model_json_schema(),
        "schemas/playback.schema.json": Playback.model_json_schema(),
        "schemas/preferences-api.schema.json": Preferences.model_json_schema(),
        "schemas/cloud-proposal.schema.json": Proposal.model_json_schema(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, value in outputs().items():
        path = ROOT / name
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                raise SystemExit("Stale generated contract: " + name)
        else:
            path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
