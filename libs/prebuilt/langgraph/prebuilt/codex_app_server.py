"""Codex app server node scaffolding."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Callable

from langchain_core.runnables.config import RunnableConfig

from langgraph._internal._runnable import RunnableCallable


class CodexAppServerError(Exception):
    """Raised for Codex app server node failures."""


class CodexAppServerNode(RunnableCallable):
    """RunnableCallable shell for future Codex app server integration."""

    _transport_factory: Callable[["CodexAppServerNode"], Any] | None = None

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
        super().__init__(self._func, None, name="codex_app_server", trace=False)

    @staticmethod
    def _default_transport_factory(_: "CodexAppServerNode") -> Any:
        raise CodexAppServerError("Codex app server transport is not implemented yet.")

    def _ensure_transport(self) -> Any:
        if self._transport is None:
            factory = type(self)._transport_factory or self._default_transport_factory
            transport = factory(self)
            start = getattr(transport, "start", None)
            if start is None:
                raise CodexAppServerError("Codex app server transport is missing start().")
            start()
            self._transport = transport
        return self._transport

    def _send_request(self, request: dict[str, Any]) -> None:
        transport = self._ensure_transport()
        send = getattr(transport, "send", None)
        if send is None:
            raise CodexAppServerError("Codex app server transport is missing send().")
        send(request)

    def _func(self, input: Any, config: RunnableConfig) -> Any:  # noqa: A002
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

        self._send_request({"type": "turn/start"})
        return input


__all__ = ["CodexAppServerError", "CodexAppServerNode"]
