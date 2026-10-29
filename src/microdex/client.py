"""Who produces the next model message.

The graph calls `complete` and does not care whether the answer is scripted
or comes from the network. The `Prompt` is built in `microdex.agent.nodes.model`.

`ModelClient` is the live caller. Codex's struct of the same name lives in
`codex-rs/core/src/client.rs` and its `stream` method yields `ResponseEvent`s.
This client speaks chat completions and returns one finished `ModelOutcome`.
`ScriptedModelClient` is a test double. Codex has no counterpart.
"""

import json
import os
from collections.abc import Mapping

from openai import OpenAI
from pydantic import BaseModel

from microdex.events import Emit, agent_message_content_delta
from microdex.oauth import resolve_api_key
from microdex.schemas import ModelOutcome, Prompt, ToolCall


class ScriptedModelClient:
    """Pop the next scripted outcome. Tests use this. No network."""

    def __init__(self, script: list[ModelOutcome]) -> None:
        self._script = list(script)

    def complete(self, prompt: Prompt, emit: Emit) -> ModelOutcome:
        del prompt
        if not self._script:
            raise RuntimeError("ScriptedModelClient ran out of outcomes")
        outcome = self._script.pop(0)
        if outcome.text:
            emit(agent_message_content_delta(outcome.text))
        return outcome


class _ToolAcc(BaseModel):
    id: str = ""
    name: str = ""
    arguments: str = ""


def fold_chat_delta(
    parts: list[str],
    tools: dict[int, _ToolAcc],
    delta: object,
) -> str:
    """Merge one chat-completions stream delta. Return the new text, if any."""

    content = getattr(delta, "content", None)
    new_text = content if isinstance(content, str) else ""
    if new_text:
        parts.append(new_text)
    for call in getattr(delta, "tool_calls", None) or []:
        acc = tools.setdefault(call.index, _ToolAcc())
        if call.id:
            acc.id += call.id
        function = call.function
        if function is None:
            continue
        if function.name:
            acc.name += function.name
        if function.arguments:
            acc.arguments += function.arguments
    return new_text


def finish_outcome(parts: list[str], tools: Mapping[int, _ToolAcc]) -> ModelOutcome:
    """Parse accumulated tool-call argument strings into one outcome."""

    calls: list[ToolCall] = []
    for index in sorted(tools):
        acc = tools[index]
        raw = acc.arguments or "{}"
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"tool {acc.name or index} arguments are not JSON: {raw}"
            ) from exc
        if not isinstance(arguments, dict):
            raise RuntimeError(
                f"tool {acc.name or index} arguments must be a JSON object"
            )
        calls.append(
            ToolCall(id=acc.id or f"call-{index}", name=acc.name, arguments=arguments)
        )
    return ModelOutcome(text="".join(parts), tool_calls=calls)


class ModelClient:
    """Stream one chat completion. The prompt is sent as built."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        provider: str = "xai",
    ) -> None:
        if provider not in {"xai", "openai"}:
            raise ValueError("provider must be 'xai' or 'openai'")
        self.provider = provider
        if provider == "xai":
            self.model = model or os.environ.get("XAI_MODEL") or "grok-4.7"
            self.base_url = (
                base_url or os.environ.get("XAI_BASE_URL") or "https://api.x.ai/v1"
            )
        else:
            self.model = model or os.environ.get("OPENAI_MODEL") or ""
            self.base_url = base_url or os.environ.get("OPENAI_BASE_URL") or ""
        # None means "resolve at call time" from the provider's environment.
        self.api_key = api_key

    def complete(self, prompt: Prompt, emit: Emit) -> ModelOutcome:
        if not self.model:
            raise RuntimeError(
                "OpenAI requires --model or OPENAI_MODEL to be set."
            )
        try:
            api_key = self._resolve_api_key()
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc} Core tests use ScriptedModelClient and do not need a credential."
            ) from exc
        options = {"api_key": api_key, "timeout": 180.0}
        if self.base_url:
            options["base_url"] = self.base_url
        client = OpenAI(**options)
        stream = client.chat.completions.create(
            model=self.model,
            messages=prompt.messages,
            tools=prompt.tools,
            stream=True,
        )
        parts: list[str] = []
        tools: dict[int, _ToolAcc] = {}
        for chunk in stream:
            delta = chunk.choices[0].delta
            new_text = fold_chat_delta(parts, tools, delta)
            if new_text:
                emit(agent_message_content_delta(new_text))
        return finish_outcome(parts, tools)

    def _resolve_api_key(self) -> str:
        if self.provider == "xai":
            return resolve_api_key(self.api_key)
        if self.api_key:
            return self.api_key
        api_key = os.environ.get("OPENAI_API_KEY") or ""
        if not api_key:
            raise RuntimeError("No OpenAI API key. Set OPENAI_API_KEY.")
        return api_key
