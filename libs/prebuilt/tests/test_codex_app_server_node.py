"""Tests for the Codex app server prebuilt node scaffold."""

from inspect import signature

from langgraph import prebuilt


def test_codex_app_server_node_is_exported() -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    error_class = getattr(prebuilt, "CodexAppServerError", None)

    assert node_class is not None
    assert error_class is not None

    params = signature(node_class.__init__).parameters
    assert tuple(params) == (
        "self",
        "command",
        "cwd",
        "model",
        "approval_policy",
        "sandbox_policy",
        "client_info",
        "messages_key",
    )
    assert params["command"].default is None
    assert params["cwd"].default is None
    assert params["model"].default is None
    assert params["approval_policy"].default is None
    assert params["sandbox_policy"].default is None
    assert params["client_info"].default is None
    assert params["messages_key"].default == "messages"

    node = node_class()

    assert node.command is None
    assert node.cwd is None
    assert node.model is None
    assert node.approval_policy is None
    assert node.sandbox_policy is None
    assert node.client_info is None
    assert node.messages_key == "messages"
    assert isinstance(node, node_class)
