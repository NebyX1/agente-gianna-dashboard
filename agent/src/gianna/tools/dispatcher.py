import asyncio


class Dispatcher:
    def __init__(self, registry, max_calls=12):
        self.registry, self.max_calls = registry, max_calls
        self.calls = 0

    async def call(self, name, arguments, context):
        tool = self.registry.validate(name, arguments)
        self.calls += 1
        if self.calls > self.max_calls:
            raise RuntimeError("tool_budget_exhausted")
        if tool not in self.registry.available(context.capabilities, context.state, context.role):
            raise RuntimeError("tool_unavailable")
        if tool.effect == "remote_write":
            raise RuntimeError("Remote writes require durable OperationManager dispatch")
        async with asyncio.timeout(tool.deadline):
            result = await tool.handler(arguments)
            if tool.output_schema:
                from jsonschema import Draft202012Validator

                Draft202012Validator(tool.output_schema).validate(result)
            return result
