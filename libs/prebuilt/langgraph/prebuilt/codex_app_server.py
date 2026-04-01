"""Codex app server node scaffolding."""

from __future__ import annotations

from langchain_core.runnables.config import RunnableConfig
from collections.abc import Sequence
from typing import Any

from langgraph._internal._runnable import RunnableCallable


class CodexAppServerError(Exception):
    """Raised for Codex app server node failures."""


class CodexAppServerNode(RunnableCallable):
    """RunnableCallable shell for future Codex app server integration."""

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
        super().__init__(self._func, None, name="codex_app_server", trace=False)

    def _func(self, input: Any, config: RunnableConfig) -> Any:  # noqa: A002
        raise CodexAppServerError("Codex app server node is not implemented yet.")


__all__ = ["CodexAppServerError", "CodexAppServerNode"]
