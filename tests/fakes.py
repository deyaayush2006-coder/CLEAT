"""A scripted stand-in for the Gemini chat model, so tests never call the network."""

from typing import Any


class ScriptedLLM:
    """Answers structured-output calls and chat turns from queues prepared by the test."""

    def __init__(self, structured: list[Any] | None = None, turns: list[Any] | None = None) -> None:
        self.structured = list(structured or [])
        self.turns = list(turns or [])
        self.prompts: list[list[Any]] = []
        self.bound_tools: list[Any] = []

    def with_structured_output(self, schema: type, **kwargs: Any) -> "_StructuredRunner":
        return _StructuredRunner(self, schema)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "ScriptedLLM":
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages: list[Any]) -> Any:
        self.prompts.append(list(messages))
        return self.turns.pop(0)


class _StructuredRunner:
    def __init__(self, llm: ScriptedLLM, schema: type) -> None:
        self.llm, self.schema = llm, schema

    def invoke(self, messages: list[Any]) -> Any:
        self.llm.prompts.append(list(messages))
        item = self.llm.structured.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, self.schema) else self.schema.model_validate(item)
