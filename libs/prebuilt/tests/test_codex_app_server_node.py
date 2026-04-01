"""Tests for the Codex app server prebuilt node scaffold."""

from inspect import signature

from langgraph import prebuilt


class _FakeTransport:
    def __init__(self) -> None:
        self.start_count = 0
        self.requests: list[object] = []

    def start(self) -> None:
        self.start_count += 1

    def send(self, request: object) -> None:
        self.requests.append(request)


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


def test_codex_app_server_node_lazy_starts_transport_on_first_invoke(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _FakeTransport()
    factory_calls: list[object] = []

    def _factory(node: object) -> _FakeTransport:
        factory_calls.append(node)
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class(
        command=["codex", "run"],
        cwd="/tmp/worktree",
        model="gpt-5",
        approval_policy="on-request",
        sandbox_policy="workspace-write",
        client_info={"name": "tests"},
    )

    assert factory_calls == []
    assert transport.start_count == 0
    assert transport.requests == []

    node.invoke({"messages": []})

    assert factory_calls == [node]
    assert transport.start_count == 1
    assert transport.requests[0] == {
        "type": "initialize",
        "command": ["codex", "run"],
        "cwd": "/tmp/worktree",
        "model": "gpt-5",
        "approval_policy": "on-request",
        "sandbox_policy": "workspace-write",
        "client_info": {"name": "tests"},
        "messages_key": "messages",
    }
    assert [request["type"] for request in transport.requests[1:]] == [
        "thread/start",
        "turn/start",
    ]


def test_codex_app_server_node_initializes_once_and_reuses_thread(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _FakeTransport()

    def _factory(node: object) -> _FakeTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class(
        command=["codex", "run"],
        cwd="/tmp/worktree",
        model="gpt-5",
        approval_policy="on-request",
        sandbox_policy="workspace-write",
        client_info={"name": "tests"},
    )

    node.invoke({"messages": []})
    node.invoke({"messages": []})

    request_types = [request["type"] for request in transport.requests]

    assert request_types.count("initialize") == 1
    assert request_types.count("thread/start") == 1
    assert request_types.count("turn/start") == 2
    assert transport.requests[0] == {
        "type": "initialize",
        "command": ["codex", "run"],
        "cwd": "/tmp/worktree",
        "model": "gpt-5",
        "approval_policy": "on-request",
        "sandbox_policy": "workspace-write",
        "client_info": {"name": "tests"},
        "messages_key": "messages",
    }


def test_codex_app_server_node_retries_transport_startup_after_failure(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    class _FailingTransport(_FakeTransport):
        def start(self) -> None:
            super().start()
            msg = "boom"
            raise RuntimeError(msg)

    first_transport = _FailingTransport()
    second_transport = _FakeTransport()
    factory_calls: list[int] = []

    def _factory(node: object) -> _FakeTransport:
        factory_calls.append(len(factory_calls))
        return first_transport if len(factory_calls) == 1 else second_transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    try:
        node.invoke({"messages": []})
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected startup failure")

    node.invoke({"messages": []})

    assert factory_calls == [0, 1]
    assert first_transport.start_count == 1
    assert second_transport.start_count == 1
    assert [request["type"] for request in second_transport.requests] == [
        "initialize",
        "thread/start",
        "turn/start",
    ]
