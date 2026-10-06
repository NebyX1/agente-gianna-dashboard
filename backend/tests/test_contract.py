import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from test_domain import create


def test_contract_matches_routes_validators_and_actual_ticket(app, headers, payload):
    path = Path(__file__).resolve().parents[1] / "contracts"
    spec = importlib.util.spec_from_file_location("generate_contract", path / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    contract = json.loads((path / "openapi.json").read_text(encoding="utf-8"))
    assert module.generate() == contract
    Draft202012Validator.check_schema(contract["components"]["schemas"]["TicketRead"])
    ticket = create(app, headers, payload).json["data"]
    schema = {"$ref": "#/components/schemas/TicketRead", "components": contract["components"]}
    Draft202012Validator(schema).validate(ticket)
    served = app.test_client().get("/api/v1/openapi.json")
    assert served.json == contract and "ok" not in served.json
