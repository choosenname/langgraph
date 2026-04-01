"""Tests for the Codex app server prebuilt node."""

import asyncio
import threading
import time
from inspect import signature

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import langgraph.prebuilt.codex_app_server as codex_app_server_module
from langgraph import prebuilt


class _FakeJsonRpcTransport:
    def __init__(
        self,
        responses: dict[str, list[object]] | None = None,
        notifications: list[object] | None = None,
    ) -> None:
        self.start_count = 0
        self.close_count = 0
        self.request_calls: list[tuple[str, dict[str, object]]] = []
        self.notify_calls: list[tuple[str, dict[str, object] | None]] = []
        self._responses = {key: list(value) for key, value in (responses or {}).items()}
        self._notifications = list(notifications or [])

    def start(self) -> None:
        self.start_count += 1

    def request(self, method: str, params: dict[str, object]) -> object:
        self.request_calls.append((method, params))
        queue = self._responses.get(method)
        if not queue:
            raise AssertionError(f"no scripted response for {method}")
        return queue.pop(0)

    def notify(self, method: str, params: dict[str, object] | None = None) -> None:
        self.notify_calls.append((method, params))

    def recv_notification(self) -> object:
        if not self._notifications:
            raise EOFError("no scripted notifications remaining")
        return self._notifications.pop(0)

    def close(self) -> None:
        self.close_count += 1


class _BlockingJsonRpcTransport(_FakeJsonRpcTransport):
    def __init__(
        self,
        responses: dict[str, list[object]] | None = None,
        notifications: list[object] | None = None,
    ) -> None:
        super().__init__(responses=responses, notifications=notifications)
        self.release = threading.Event()
        self.waiting = threading.Event()
        self._waited = False

    def recv_notification(self) -> object:
        if not self._waited:
            self._waited = True
            self.waiting.set()
            if not self.release.wait(timeout=1):
                raise AssertionError("transport was not released")
        return super().recv_notification()


def _initialize_result() -> dict[str, object]:
    return {"userAgent": "tests/1.0"}


def _thread_start_result(thread_id: str = "thread-123") -> dict[str, object]:
    return {
        "thread": {"id": thread_id},
        "approvalPolicy": "on-request",
        "approvalsReviewer": "user",
        "cwd": "/tmp/worktree",
        "model": "gpt-5",
        "modelProvider": "openai",
        "sandbox": {"type": "workspaceWrite"},
    }


def _turn_start_result(turn_id: str = "turn-123") -> dict[str, object]:
    return {"turn": {"id": turn_id, "status": "inProgress", "items": []}}


def _turn_completed_notification(
    *,
    thread_id: str = "thread-123",
    turn_id: str = "turn-123",
    status: str = "completed",
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    turn: dict[str, object] = {"id": turn_id, "status": status, "items": []}
    if error is not None:
        turn["error"] = error
    return {"method": "turn/completed", "params": {"threadId": thread_id, "turn": turn}}


def _agent_message_delta_notification(
    delta: str,
    *,
    thread_id: str = "thread-123",
    turn_id: str = "turn-123",
    item_id: str = "item-123",
) -> dict[str, object]:
    return {
        "method": "item/agentMessage/delta",
        "params": {
            "delta": delta,
            "itemId": item_id,
            "threadId": thread_id,
            "turnId": turn_id,
        },
    }


def _agent_message_completed_notification(
    text: str,
    *,
    thread_id: str = "thread-123",
    turn_id: str = "turn-123",
    item_id: str = "item-123",
) -> dict[str, object]:
    return {
        "method": "item/completed",
        "params": {
            "threadId": thread_id,
            "turnId": turn_id,
            "item": {"id": item_id, "type": "agentMessage", "text": text},
        },
    }


def _new_transport(
    *,
    thread_id: str = "thread-123",
    turn_id: str = "turn-123",
    notifications: list[object] | None = None,
) -> _FakeJsonRpcTransport:
    return _FakeJsonRpcTransport(
        responses={
            "initialize": [_initialize_result()],
            "thread/start": [_thread_start_result(thread_id=thread_id)],
            "turn/start": [_turn_start_result(turn_id=turn_id)],
        },
        notifications=notifications or [_turn_completed_notification()],
    )


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

    transport = _new_transport()
    factory_calls: list[object] = []

    def _factory(node: object) -> _FakeJsonRpcTransport:
        factory_calls.append(node)
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class(
        command=["codex", "app-server"],
        cwd="/tmp/worktree",
        model="gpt-5",
        approval_policy="on-request",
        sandbox_policy="workspace-write",
        client_info={"name": "tests", "version": "1.0"},
    )

    assert factory_calls == []
    assert transport.start_count == 0
    assert transport.request_calls == []
    assert transport.notify_calls == []

    node.invoke({"messages": [HumanMessage(content="hello")]})

    assert factory_calls == [node]
    assert transport.start_count == 1
    assert transport.request_calls[0] == (
        "initialize",
        {"clientInfo": {"name": "tests", "version": "1.0"}},
    )
    assert transport.notify_calls == [("initialized", None)]
    assert transport.request_calls[1] == (
        "thread/start",
        {
            "cwd": "/tmp/worktree",
            "model": "gpt-5",
            "approvalPolicy": "on-request",
            "sandbox": "workspace-write",
        },
    )
    assert transport.request_calls[2] == (
        "turn/start",
        {
            "threadId": "thread-123",
            "input": [{"type": "text", "text": "user: hello"}],
        },
    )


def test_codex_app_server_node_initializes_once_and_reuses_thread(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _FakeJsonRpcTransport(
        responses={
            "initialize": [_initialize_result()],
            "thread/start": [_thread_start_result(thread_id="thread-123")],
            "turn/start": [
                _turn_start_result(turn_id="turn-1"),
                _turn_start_result(turn_id="turn-2"),
            ],
        },
        notifications=[
            _turn_completed_notification(turn_id="turn-1"),
            _turn_completed_notification(turn_id="turn-2"),
        ],
    )

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class(
        command=["codex", "app-server"],
        cwd="/tmp/worktree",
        model="gpt-5",
        approval_policy="on-request",
        sandbox_policy="workspace-write",
        client_info={"name": "tests", "version": "1.0"},
    )

    node.invoke({"messages": [HumanMessage(content="hello")]})
    node.invoke({"messages": [HumanMessage(content="hello again")]})

    request_methods = [method for method, _ in transport.request_calls]

    assert request_methods.count("initialize") == 1
    assert request_methods.count("thread/start") == 1
    assert request_methods.count("turn/start") == 2
    assert transport.notify_calls == [("initialized", None)]
    assert transport.request_calls[2][1]["threadId"] == "thread-123"
    assert transport.request_calls[3][1]["threadId"] == "thread-123"


@pytest.mark.asyncio
async def test_codex_app_server_node_ainvoke_returns_ai_message(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _BlockingJsonRpcTransport(
        responses={
            "initialize": [_initialize_result()],
            "thread/start": [_thread_start_result()],
            "turn/start": [_turn_start_result()],
        },
        notifications=[
            _agent_message_delta_notification("Hel"),
            _agent_message_delta_notification("lo"),
            _turn_completed_notification(),
        ],
    )

    def _factory(node: object) -> _BlockingJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    invoke_task = asyncio.create_task(
        node.ainvoke({"messages": [HumanMessage(content="hello")]})
    )
    await asyncio.wait_for(asyncio.to_thread(transport.waiting.wait, 1), timeout=1)

    marker_ran = asyncio.Event()

    async def _mark_loop() -> None:
        marker_ran.set()

    marker = asyncio.create_task(_mark_loop())
    await asyncio.wait_for(marker_ran.wait(), timeout=1)
    transport.release.set()

    result = await invoke_task
    await marker
    assert result == {"messages": [AIMessage(content="Hello")]}


def test_codex_app_server_node_retries_transport_startup_after_failure(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    class _FailingTransport(_FakeJsonRpcTransport):
        def start(self) -> None:
            super().start()
            raise RuntimeError("boom")

    first_transport = _FailingTransport()
    second_transport = _new_transport()
    factory_calls: list[int] = []

    def _factory(node: object) -> _FakeJsonRpcTransport:
        factory_calls.append(len(factory_calls))
        return first_transport if len(factory_calls) == 1 else second_transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(RuntimeError, match="boom"):
        node.invoke({"messages": [HumanMessage(content="hello")]})

    node.invoke({"messages": [HumanMessage(content="hello again")]})

    assert factory_calls == [0, 1]
    assert first_transport.start_count == 1
    assert second_transport.start_count == 1
    assert [method for method, _ in second_transport.request_calls] == [
        "initialize",
        "thread/start",
        "turn/start",
    ]


def test_codex_app_server_node_restarts_transport_after_dead_transport(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    first_transport = _new_transport(
        notifications=[_agent_message_delta_notification("Hel")]
    )
    second_transport = _new_transport(
        notifications=[
            _agent_message_delta_notification("Hel"),
            _agent_message_delta_notification("lo"),
            _turn_completed_notification(),
        ]
    )
    factory_calls: list[int] = []

    def _factory(node: object) -> _FakeJsonRpcTransport:
        factory_calls.append(len(factory_calls))
        return first_transport if len(factory_calls) == 1 else second_transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(prebuilt.CodexAppServerError, match="EOF"):
        node.invoke({"messages": [HumanMessage(content="hello")]})

    result = node.invoke({"messages": [HumanMessage(content="hello again")]})

    assert factory_calls == [0, 1]
    assert first_transport.start_count == 1
    assert second_transport.start_count == 1
    assert result == {"messages": [AIMessage(content="Hello")]}


def test_codex_app_server_node_resets_transport_after_raw_transport_exception(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    class _BrokenTransport(_FakeJsonRpcTransport):
        def recv_notification(self) -> object:
            if not self._notifications:
                raise RuntimeError("transport exploded")
            return super().recv_notification()

    first_transport = _BrokenTransport(
        responses={
            "initialize": [_initialize_result()],
            "thread/start": [_thread_start_result()],
            "turn/start": [_turn_start_result()],
        },
        notifications=[_agent_message_delta_notification("Hel")],
    )
    second_transport = _new_transport(
        notifications=[
            _agent_message_delta_notification("Hel"),
            _agent_message_delta_notification("lo"),
            _turn_completed_notification(),
        ]
    )
    factory_calls: list[int] = []

    def _factory(node: object) -> _FakeJsonRpcTransport:
        factory_calls.append(len(factory_calls))
        return first_transport if len(factory_calls) == 1 else second_transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(RuntimeError, match="transport exploded"):
        node.invoke({"messages": [HumanMessage(content="hello")]})

    result = node.invoke({"messages": [HumanMessage(content="hello again")]})

    assert factory_calls == [0, 1]
    assert first_transport.start_count == 1
    assert second_transport.start_count == 1
    assert result == {"messages": [AIMessage(content="Hello")]}


def test_codex_app_server_node_serializes_overlapping_invocations(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    class _OverlapTransport(_FakeJsonRpcTransport):
        def __init__(self) -> None:
            super().__init__(
                responses={
                    "initialize": [_initialize_result()],
                    "thread/start": [_thread_start_result()],
                    "turn/start": [
                        _turn_start_result(turn_id="turn-1"),
                        _turn_start_result(turn_id="turn-2"),
                    ],
                },
                notifications=[
                    _turn_completed_notification(turn_id="turn-1"),
                    _turn_completed_notification(turn_id="turn-2"),
                ],
            )
            self.in_recv = threading.Event()
            self.release = threading.Event()

        def recv_notification(self) -> object:
            if not self.in_recv.is_set():
                self.in_recv.set()
                if not self.release.wait(timeout=1):
                    raise AssertionError("transport was not released")
            return super().recv_notification()

    transport = _OverlapTransport()

    def _factory(node: object) -> _OverlapTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()
    results: list[dict[str, list[AIMessage]]] = []
    errors: list[BaseException] = []

    def _invoke() -> None:
        try:
            results.append(node.invoke({"messages": [HumanMessage(content="hello")]}))
        except BaseException as exc:  # pragma: no cover - defensive
            errors.append(exc)

    first = threading.Thread(target=_invoke)
    second = threading.Thread(target=_invoke)

    first.start()
    assert transport.in_recv.wait(timeout=1)

    second.start()
    time.sleep(0.05)

    assert len(transport.request_calls) == 3
    assert second.is_alive()

    transport.release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert errors == []
    assert results == [
        {"messages": [AIMessage(content="")]},
        {"messages": [AIMessage(content="")]},
    ]
    assert [method for method, _ in transport.request_calls] == [
        "initialize",
        "thread/start",
        "turn/start",
        "turn/start",
    ]


def test_codex_app_server_node_serializes_message_history_into_turn_start(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport(
        notifications=[
            _agent_message_delta_notification("ok"),
            _turn_completed_notification(),
        ]
    )

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()
    node.invoke(
        {
            "messages": [
                SystemMessage(content="system context"),
                HumanMessage(content="hello"),
                AIMessage(content="hi there"),
            ]
        }
    )

    assert transport.request_calls[2] == (
        "turn/start",
        {
            "threadId": "thread-123",
            "input": [
                {
                    "type": "text",
                    "text": "system: system context\n\nuser: hello\n\nassistant: hi there",
                }
            ],
        },
    )


def test_codex_app_server_node_returns_ai_message_from_assistant_deltas(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport(
        notifications=[
            _agent_message_delta_notification("Hel"),
            _agent_message_delta_notification("lo"),
            _turn_completed_notification(),
        ]
    )

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()
    result = node.invoke({"messages": [HumanMessage(content="hello")]})

    assert result == {"messages": [AIMessage(content="Hello")]}


def test_codex_app_server_node_uses_completed_agent_message_without_deltas(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport(
        notifications=[
            _agent_message_completed_notification("Hello"),
            _turn_completed_notification(),
        ]
    )

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()
    result = node.invoke({"messages": [HumanMessage(content="hello")]})

    assert result == {"messages": [AIMessage(content="Hello")]}


def test_codex_app_server_node_validates_input_before_starting_transport(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport()
    factory_calls: list[object] = []

    def _factory(node: object) -> _FakeJsonRpcTransport:
        factory_calls.append(node)
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(ValueError, match="Codex app server input must be a dict"):
        node.invoke([])

    assert factory_calls == []
    assert transport.start_count == 0
    assert transport.request_calls == []


def test_codex_app_server_node_raises_on_eof_before_completion(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport(
        notifications=[
            _agent_message_delta_notification("Hel"),
        ]
    )

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(prebuilt.CodexAppServerError, match="EOF"):
        node.invoke({"messages": [HumanMessage(content="hello")]})

    assert transport.request_calls[0] == (
        "initialize",
        {"clientInfo": {"name": "langgraph-prebuilt", "version": "0"}},
    )
    assert transport.request_calls[1] == ("thread/start", {})
    assert transport.request_calls[2] == (
        "turn/start",
        {
            "threadId": "thread-123",
            "input": [{"type": "text", "text": "user: hello"}],
        },
    )


def test_codex_app_server_node_raises_on_server_error_notification(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport(
        notifications=[
            {
                "method": "error",
                "params": {
                    "threadId": "thread-123",
                    "turnId": "turn-123",
                    "willRetry": False,
                    "error": {"message": "server rejected the turn"},
                },
            }
        ]
    )

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(prebuilt.CodexAppServerError, match="server rejected the turn"):
        node.invoke({"messages": [HumanMessage(content="hello")]})


def test_codex_app_server_node_raises_on_failed_turn_status(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport(
        notifications=[
            _turn_completed_notification(
                status="failed",
                error={"message": "server rejected the turn"},
            )
        ]
    )

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(prebuilt.CodexAppServerError, match="server rejected the turn"):
        node.invoke({"messages": [HumanMessage(content="hello")]})


def test_codex_app_server_node_raises_on_invalid_notification(
    monkeypatch: object,
) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport(notifications=[["not", "a", "notification"]])

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()

    with pytest.raises(prebuilt.CodexAppServerError, match="Invalid notification"):
        node.invoke({"messages": [HumanMessage(content="hello")]})


def test_codex_app_server_node_close_closes_transport(monkeypatch: object) -> None:
    node_class = getattr(prebuilt, "CodexAppServerNode", None)
    assert node_class is not None

    transport = _new_transport()

    def _factory(node: object) -> _FakeJsonRpcTransport:
        return transport

    monkeypatch.setattr(node_class, "_transport_factory", _factory, raising=False)

    node = node_class()
    node.invoke({"messages": [HumanMessage(content="hello")]})

    node.close()

    assert transport.close_count == 1


def test_default_transport_factory_builds_stdio_transport() -> None:
    node = prebuilt.CodexAppServerNode(
        command=["codex", "app-server"], cwd="/tmp/worktree"
    )

    transport = node._default_transport_factory(node)

    assert isinstance(transport, codex_app_server_module._StdioJsonRpcTransport)
    assert transport.command == ("codex", "app-server")
    assert transport.cwd == "/tmp/worktree"
