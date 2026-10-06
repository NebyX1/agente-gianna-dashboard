from jsonschema import Draft202012Validator
from gianna.tools.contracts import Tool


class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.plugins = {}

    def register(self, tool: Tool):
        if tool.name in self.tools or not tool.name.endswith(".v" + tool.version):
            raise ValueError("Duplicate tool or incompatible stable namespace")
        Draft202012Validator.check_schema(tool.schema)
        if tool.output_schema:
            Draft202012Validator.check_schema(tool.output_schema)
        self.tools[tool.name] = tool

    def install(self, provider, *, allowlist):
        if getattr(provider, "api_version", None) != "1":
            raise ValueError("Incompatible plugin API version")
        identity = (provider.plugin_id, provider.version)
        if identity not in allowlist:
            raise ValueError("Plugin not installed/allowlisted")
        if identity in self.plugins:
            raise ValueError("Duplicate plugin")
        staged = ToolRegistry()
        staged.tools = self.tools.copy()
        for tool in provider.tools():
            staged.register(tool)
        self.tools = staged.tools
        self.plugins[identity] = provider

    def validate(self, name, args):
        tool = self.tools[name]
        Draft202012Validator(tool.schema).validate(args)
        return tool

    def available(self, capabilities, state, role):
        return [
            t
            for t in self.tools.values()
            if t.capability in capabilities and state in t.states and role in t.roles
        ]
