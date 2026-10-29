from types import SimpleNamespace

import pytest

import microdex.client as client_module
from microdex.client import ModelClient
from microdex.schemas import Prompt

pytestmark = pytest.mark.scaffold


def test_openai_provider_uses_its_own_key_and_requires_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    client = ModelClient(provider="openai")
    with pytest.raises(RuntimeError, match="OPENAI_MODEL"):
        client.complete(Prompt(messages=[], tools=[]), lambda _event: None)

    client = ModelClient(provider="openai", model="gpt-test")
    assert client._resolve_api_key() == "openai-test-key"


def test_openai_model_can_come_from_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-env-test")
    assert ModelClient(provider="openai").model == "gpt-env-test"


def test_openai_completion_uses_default_endpoint_and_streams(monkeypatch):
    seen = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen["request"] = kwargs
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="hello", tool_calls=[]))
                    ]
                )
            ]

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    client = ModelClient(provider="openai", model="gpt-test")
    deltas = []
    outcome = client.complete(Prompt(messages=[], tools=[]), deltas.append)

    assert outcome.text == "hello"
    assert len(deltas) == 1 and deltas[0]["text"] == "hello"
    assert seen["client"] == {"api_key": "openai-test-key", "timeout": 180.0}
    assert seen["request"]["model"] == "gpt-test"
    assert seen["request"]["stream"] is True


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="provider"):
        ModelClient(provider="other")
