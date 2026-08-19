from __future__ import annotations

import inspect

import offerpilot.ai.agent as agent_module
import offerpilot.api as api_module


def test_chat_hitl_has_no_persistent_checkpoint_dependency() -> None:
    source = inspect.getsource(agent_module)
    assert "SqliteSaver" not in source
    assert "checkpoint_path" not in source
    assert "langgraph.types import Command" not in source


def test_api_does_not_construct_agent_checkpoint_paths() -> None:
    source = inspect.getsource(api_module)
    assert "_agent_checkpoint_path" not in source
    assert "agent-checkpoints.sqlite" not in source


def test_runner_uses_only_request_scoped_memory_saver() -> None:
    source = inspect.getsource(agent_module.LangGraphAgentRunner)
    assert "InMemorySaver()" in source
    assert "SqliteSaver" not in source
