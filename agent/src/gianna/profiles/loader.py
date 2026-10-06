import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]


def safe_reference(root, reference):
    path = (root / reference).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != ".json":
        raise ValueError("Profile reference outside installed root or executable format")
    return path


def load_profile(profile_id="idl-tickets", registry=None):
    import re

    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", profile_id):
        raise ValueError("Invalid installed profile identifier")
    root = ROOT / "profiles/apps" / profile_id
    schema = json.loads((ROOT / "schemas/app-profile.schema.json").read_text())
    profile = json.loads((root / "profile.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(profile)
    if registry and set(profile["tools"]) - set(registry.tools):
        raise ValueError("Profile requests a tool that is not installed")
    profile["locators_data"] = json.loads(
        safe_reference(root, profile["locators"]).read_text(encoding="utf-8")
    )
    profile["aliases_data"] = json.loads(
        safe_reference(root, profile["aliases"]).read_text(encoding="utf-8")
    )
    locators = profile["locators_data"]
    if not isinstance(locators, dict) or locators.get("contract_version") != "1":
        raise ValueError("Incompatible locator contract")
    for name, spec in locators.items():
        if name == "contract_version":
            continue
        if not isinstance(spec, dict) or set(spec) not in (
            {"test_id"},
            {"label"},
            {"role", "name"},
        ):
            raise ValueError("Locator requires exactly a test_id, label or role/name")
        if not all(isinstance(v, str) and 0 < len(v) <= 160 for v in spec.values()):
            raise ValueError("Invalid locator value")
        if "role" in spec and spec["role"] not in {
            "heading",
            "textbox",
            "button",
            "combobox",
            "region",
            "link",
        }:
            raise ValueError("Unsupported accessible role")
    aliases = profile["aliases_data"]
    if (
        not isinstance(aliases, dict)
        or aliases.get("schema_version") != "1"
        or any(
            not isinstance(group, dict)
            or any(
                not isinstance(k, str)
                or not isinstance(v, list)
                or any(not isinstance(alias, str) or len(alias) > 160 for alias in v)
                for k, v in group.items()
            )
            for name, group in aliases.items()
            if name != "schema_version"
        )
    ):
        raise ValueError("Invalid catalogue aliases")
    for workflow in profile["workflows"]:
        content = json.loads(safe_reference(root, workflow).read_text(encoding="utf-8"))
        if not isinstance(content, list) or len(content) > 12:
            raise ValueError("Workflow budget exceeded")
        for step in content:
            if set(step) != {"primitive", "arguments"} or step["primitive"] not in profile["tools"]:
                raise ValueError("Workflow uses unregistered primitive")
            if registry:
                # Empty templated arguments are resolved against the canonical draft at runtime.
                if step["arguments"]:
                    registry.validate(step["primitive"], step["arguments"])
    return profile


def load_preferences():
    doc = json.loads((ROOT / "profiles/users/default-accessibility.json").read_text())
    schema = json.loads((ROOT / "schemas/user-preferences.schema.json").read_text())
    Draft202012Validator(schema).validate(doc)
    return doc
