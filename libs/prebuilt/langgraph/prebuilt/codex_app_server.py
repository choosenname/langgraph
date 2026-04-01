"""Codex app server node scaffolding."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    convert_to_messages,
)
from langchain_core.runnables.config import RunnableConfig
from langgraph._internal._runnable import RunnableCallable


class CodexAppServerError(Exception):
    """Raised for Codex app server node failures."""


class CodexAppServerNode(RunnableCallable):
    """RunnableCallable shell for future Codex app server integration."""

    _transport_factory: Callable[[CodexAppServerNode], Any] | None = None

    def __init__(
        self,
        command: Sequence[str] | None = None,
        cwd: str | None = None,
        model: str | None = None,
        approval_policy: str | None = None,
        sandbox_policy: str | None = None,
        client_info: dict[str, str] | None = None,
        messages_key: str = "messages",
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.model = model
        self.approval_policy = approval_policy
        self.sandbox_policy = sandbox_policy
        self.client_info = client_info
        self.messages_key = messages_key
        self._transport: Any | None = None
        self._initialized = False
        self._thread_started = False
        self._lock = threading.RLock()
        super().__init__(self._func, self._afunc, name="codex_app_server", trace=False)

    @staticmethod
    def _default_transport_factory(_: CodexAppServerNode) -> Any:
        raise CodexAppServerError("Codex app server transport is not implemented yet.")

    def _ensure_transport(self) -> Any:
        if self._transport is None:
            factory = type(self)._transport_factory or self._default_transport_factory
            transport = factory(self)
            start = getattr(transport, "start", None)
            if start is None:
                raise CodexAppServerError(
                    "Codex app server transport is missing start()."
                )
            start()
            self._transport = transport
        return self._transport

    def _reset_transport(self) -> None:
        self._transport = None
        self._initialized = False
        self._thread_started = False

    def _send_request(self, request: dict[str, Any]) -> None:
        transport = self._ensure_transport()
        send = getattr(transport, "send", None)
        if send is None:
            raise CodexAppServerError("Codex app server transport is missing send().")
        send(request)

    def _get_messages(self, input: Any) -> list[BaseMessage]:  # noqa: A002
        if not isinstance(input, dict):
            raise ValueError("Codex app server input must be a dict.")
        if self.messages_key not in input:
            raise ValueError(f"Missing messages key '{self.messages_key}'.")

        messages = convert_to_messages(input[self.messages_key])
        return list(messages)

    @staticmethod
    def _serialize_message(message: BaseMessage) -> dict[str, Any]:
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            raise ValueError(f"Unsupported message type: {type(message).__name__}")

        return {"role": role, "content": message.content}

    def _serialize_messages(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        return [self._serialize_message(message) for message in messages]

    def _receive_event(self) -> Any:
        transport = self._ensure_transport()
        receive = getattr(transport, "recv", None)
        if receive is None:
            raise CodexAppServerError("Codex app server transport is missing recv().")
        try:
            return receive()
        except EOFError:
            raise CodexAppServerError("Unexpected EOF from Codex app server transport.")

    def _assemble_assistant_message(self) -> AIMessage:
        fragments: list[str] = []

        while True:
            event = self._receive_event()
            if not isinstance(event, dict):
                raise CodexAppServerError(
                    "Invalid event from Codex app server transport."
                )

            event_type = event.get("type")
            if event_type == "assistant/text_delta":
                fragment = event.get("content")
                if fragment is not None:
                    fragments.append(str(fragment))
                continue

            if event_type == "turn/completed":
                return AIMessage(content="".join(fragments))

            if event_type in {"turn/failed", "turn/error", "protocol/error"}:
                message = event.get("message") or event.get("error")
                if message is None:
                    message = "Codex app server turn failed."
                raise CodexAppServerError(f"Codex app server turn failed: {message}")

            raise CodexAppServerError(
                f"Unexpected Codex app server event: {event_type!r}"
            )

    async def _afunc(self, input: Any, config: RunnableConfig) -> Any:  # noqa: A002
        return await asyncio.to_thread(self._func, input, config)

    def _func(self, input: Any, config: RunnableConfig) -> Any:  # noqa: A002
        with self._lock:
            messages = self._get_messages(input)
            turn_start_request = {
                "type": "turn/start",
                "messages": self._serialize_messages(messages),
            }

            try:
                if not self._initialized:
                    self._send_request(
                        {
                            "type": "initialize",
                            "command": self.command,
                            "cwd": self.cwd,
                            "model": self.model,
                            "approval_policy": self.approval_policy,
                            "sandbox_policy": self.sandbox_policy,
                            "client_info": self.client_info,
                            "messages_key": self.messages_key,
                        }
                    )
                    self._initialized = True

                if not self._thread_started:
                    self._send_request({"type": "thread/start"})
                    self._thread_started = True

                self._send_request(turn_start_request)
                return {"messages": [self._assemble_assistant_message()]}
            except Exception:
                self._reset_transport()
                raise


__all__ = ["CodexAppServerError", "CodexAppServerNode"]
