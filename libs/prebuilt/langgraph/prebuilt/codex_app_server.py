"""Codex App Server node implementation."""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Sequence
from typing import IO, Any

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
    """Raised for Codex App Server node failures."""


class _StdioJsonRpcTransport:
    """Minimal line-delimited JSON-RPC transport for `codex app-server`."""

    def __init__(self, command: Sequence[str], cwd: str | None = None) -> None:
        self.command = tuple(command)
        self.cwd = cwd
        self._process: subprocess.Popen[str] | None = None
        self._stdout: IO[str] | None = None
        self._stdin: IO[str] | None = None
        self._next_id = 1
        self._pending_notifications: deque[dict[str, Any]] = deque()

    def start(self) -> None:
        if self._process is not None:
            return

        process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        if process.stdin is None or process.stdout is None:
            process.terminate()
            raise CodexAppServerError(
                "Codex app server process did not expose stdio pipes."
            )

        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write_message({"id": request_id, "method": method, "params": params})

        while True:
            message = self._read_message()
            if "method" in message:
                self._pending_notifications.append(message)
                continue

            if message.get("id") != request_id:
                raise CodexAppServerError(
                    f"Unexpected response id from Codex app server: {message.get('id')!r}"
                )

            error = message.get("error")
            if error is not None:
                raise CodexAppServerError(self._format_error(error))

            result = message.get("result")
            if not isinstance(result, dict):
                raise CodexAppServerError(
                    "Codex app server response is missing an object result."
                )
            return result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        self._write_message(message)

    def recv_notification(self) -> dict[str, Any]:
        if self._pending_notifications:
            return self._pending_notifications.popleft()

        message = self._read_message()
        if "method" not in message:
            raise CodexAppServerError(
                "Unexpected response received while waiting for a notification."
            )
        return message

    def close(self) -> None:
        process = self._process
        stdin = self._stdin
        stdout = self._stdout
        self._process = None
        self._stdin = None
        self._stdout = None
        self._pending_notifications.clear()

        if stdin is not None:
            stdin.close()
        if stdout is not None:
            stdout.close()

        if process is None:
            return
        if process.poll() is not None:
            return

        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

    def _write_message(self, message: dict[str, Any]) -> None:
        if self._stdin is None:
            raise CodexAppServerError("Codex app server transport is not started.")

        payload = json.dumps(message, separators=(",", ":"))
        try:
            self._stdin.write(payload)
            self._stdin.write("\n")
            self._stdin.flush()
        except BrokenPipeError as exc:
            raise CodexAppServerError(
                "Codex app server transport closed while sending a message."
            ) from exc

    def _read_message(self) -> dict[str, Any]:
        if self._stdout is None:
            raise CodexAppServerError("Codex app server transport is not started.")

        line = self._stdout.readline()
        if line == "":
            raise EOFError("Codex app server transport reached EOF.")

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexAppServerError(
                "Codex app server transport emitted invalid JSON."
            ) from exc

        if not isinstance(message, dict):
            raise CodexAppServerError(
                "Codex app server transport emitted a non-object message."
            )
        return message

    @staticmethod
    def _format_error(error: Any) -> str:
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        return str(error)


class CodexAppServerNode(RunnableCallable):
    """Runnable node that reuses one Codex App Server thread across invocations."""

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
        self._thread_id: str | None = None
        self._lock = threading.RLock()
        super().__init__(self._func, self._afunc, name="codex_app_server", trace=False)

    @staticmethod
    def _default_transport_factory(node: CodexAppServerNode) -> _StdioJsonRpcTransport:
        command = tuple(node.command or ("codex", "app-server"))
        return _StdioJsonRpcTransport(command=command, cwd=node.cwd)

    def close(self) -> None:
        with self._lock:
            self._reset_transport()

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

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
        transport = self._transport
        self._transport = None
        self._initialized = False
        self._thread_id = None

        close = getattr(transport, "close", None)
        if close is not None:
            close()

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        transport = self._ensure_transport()
        request = getattr(transport, "request", None)
        if request is None:
            raise CodexAppServerError(
                "Codex app server transport is missing request()."
            )
        result = request(method, params)
        if not isinstance(result, dict):
            raise CodexAppServerError(
                "Codex app server transport returned a non-object result."
            )
        return result

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        transport = self._ensure_transport()
        notify = getattr(transport, "notify", None)
        if notify is None:
            raise CodexAppServerError("Codex app server transport is missing notify().")
        notify(method, params)

    def _receive_notification(self) -> dict[str, Any]:
        transport = self._ensure_transport()
        receive = getattr(transport, "recv_notification", None)
        if receive is None:
            raise CodexAppServerError(
                "Codex app server transport is missing recv_notification()."
            )
        try:
            message = receive()
        except EOFError as exc:
            raise CodexAppServerError(
                "Unexpected EOF from Codex app server transport."
            ) from exc

        if not isinstance(message, dict):
            raise CodexAppServerError(
                "Invalid notification from Codex app server transport."
            )
        return message

    def _get_messages(self, input: Any) -> list[BaseMessage]:  # noqa: A002
        if not isinstance(input, dict):
            raise ValueError("Codex app server input must be a dict.")
        if self.messages_key not in input:
            raise ValueError(f"Missing messages key '{self.messages_key}'.")

        messages = convert_to_messages(input[self.messages_key])
        return list(messages)

    @staticmethod
    def _render_message_text(message: BaseMessage) -> str:
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            raise ValueError(f"Unsupported message type: {type(message).__name__}")

        content = message.content
        if not isinstance(content, str):
            content = str(content)
        return f"{role}: {content}"

    def _build_turn_input(self, messages: list[BaseMessage]) -> list[dict[str, str]]:
        transcript = "\n\n".join(
            self._render_message_text(message) for message in messages
        )
        return [{"type": "text", "text": transcript}]

    def _build_client_info(self) -> dict[str, str]:
        client_info = {"name": "langgraph-prebuilt", "version": "0"}
        if self.client_info is not None:
            client_info.update(self.client_info)
        return client_info

    def _initialize_session(self) -> None:
        if self._initialized:
            return

        self._request("initialize", {"clientInfo": self._build_client_info()})
        self._notify("initialized")
        self._initialized = True

    def _ensure_thread(self) -> str:
        if self._thread_id is not None:
            return self._thread_id

        params: dict[str, Any] = {}
        if self.cwd is not None:
            params["cwd"] = self.cwd
        if self.model is not None:
            params["model"] = self.model
        if self.approval_policy is not None:
            params["approvalPolicy"] = self.approval_policy
        if self.sandbox_policy is not None:
            params["sandbox"] = self.sandbox_policy

        result = self._request("thread/start", params)
        thread = result.get("thread")
        if not isinstance(thread, dict):
            raise CodexAppServerError(
                "Codex app server thread/start response is missing thread metadata."
            )
        thread_id = thread.get("id")
        if not isinstance(thread_id, str):
            raise CodexAppServerError(
                "Codex app server thread/start response is missing a thread id."
            )
        self._thread_id = thread_id
        return thread_id

    def _start_turn(self, messages: list[BaseMessage]) -> dict[str, Any]:
        turn_params = {
            "threadId": self._ensure_thread(),
            "input": self._build_turn_input(messages),
        }
        return self._request("turn/start", turn_params)

    def _assemble_assistant_message(self) -> AIMessage:
        fragments: list[str] = []
        completed_text: str | None = None

        while True:
            notification = self._receive_notification()
            method = notification.get("method")
            params = notification.get("params")

            if not isinstance(method, str) or not isinstance(params, dict):
                raise CodexAppServerError(
                    "Invalid notification from Codex app server transport."
                )

            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if delta is not None:
                    fragments.append(str(delta))
                continue

            if method == "item/completed":
                item = params.get("item")
                if isinstance(item, dict) and item.get("type") == "agentMessage":
                    text = item.get("text")
                    if text is not None:
                        completed_text = str(text)
                continue

            if method == "turn/completed":
                turn = params.get("turn")
                if not isinstance(turn, dict):
                    raise CodexAppServerError(
                        "Codex app server turn/completed notification is missing turn metadata."
                    )

                status = turn.get("status")
                if status != "completed":
                    error = turn.get("error")
                    if isinstance(error, dict) and isinstance(
                        error.get("message"), str
                    ):
                        message = error["message"]
                    else:
                        message = (
                            f"Codex app server turn finished with status {status!r}."
                        )
                    raise CodexAppServerError(message)

                content = "".join(fragments) or completed_text or ""
                return AIMessage(content=content)

            if method == "error":
                error = params.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
                else:
                    message = "Codex app server reported an error."
                raise CodexAppServerError(message)

    async def _afunc(self, input: Any, config: RunnableConfig) -> Any:  # noqa: A002
        return await asyncio.to_thread(self._func, input, config)

    def _func(self, input: Any, config: RunnableConfig) -> Any:  # noqa: A002
        with self._lock:
            messages = self._get_messages(input)

            try:
                self._initialize_session()
                self._start_turn(messages)
                return {"messages": [self._assemble_assistant_message()]}
            except Exception:
                self._reset_transport()
                raise


__all__ = ["CodexAppServerError", "CodexAppServerNode"]
