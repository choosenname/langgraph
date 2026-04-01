# Codex App Server Node Design

**Date:** 2026-04-01

**Status:** Approved in chat, pending written spec review

## Goal

Add first-class support for OpenAI Codex App Server as a reusable LangGraph node.
The node must manage one long-lived `codex app-server` subprocess, reuse a single
server thread across invocations, and expose a message-based LangGraph interface.

## Scope

This design covers a new Python prebuilt node in `libs/prebuilt`.
It does not cover:

- raw protocol event passthrough as public API
- interactive approval UI integration
- multiple concurrent turns on one node instance
- a dedicated new package outside `libs/prebuilt`

## Why `libs/prebuilt`

`libs/prebuilt` is already the home for reusable high-level nodes such as
`ToolNode` and `ValidationNode`. The new Codex integration has the same shape:
it is a user-facing building block that encapsulates runtime behavior behind a
normal LangGraph node interface.

Keeping the implementation in `libs/prebuilt` also avoids coupling `libs/langgraph`
core to subprocess management and external service protocol details.

## Public API

Add a new export:

- `langgraph.prebuilt.CodexAppServerNode`

Proposed constructor:

```python
CodexAppServerNode(
    command: Sequence[str] | None = None,
    cwd: str | None = None,
    model: str | None = None,
    approval_policy: str | None = None,
    sandbox_policy: str | None = None,
    client_info: dict[str, str] | None = None,
    messages_key: str = "messages",
)
```

Behavior:

- The node is usable directly in `StateGraph.add_node(...)`.
- Input state must contain a message list under `messages_key`.
- Output is a state update with one appended `AIMessage`.
- The first version does not expose raw App Server events.

Example:

```python
from langgraph.graph import StateGraph
from langgraph.prebuilt import CodexAppServerNode

codex_node = CodexAppServerNode(model="gpt-5-codex")

builder = StateGraph(MessagesState)
builder.add_node("codex", codex_node)
```

## Internal Architecture

Implementation is split into two layers in the same module:

1. `CodexAppServerNode`
   - public LangGraph-facing node
   - validates input state
   - maps LangGraph messages to App Server turn input
   - maps final App Server output back to `AIMessage`

2. Internal client/transport helper
   - starts the subprocess
   - writes JSON-RPC requests over stdio
   - reads and routes JSON-RPC responses and server events
   - tracks lifecycle state such as initialized process and `thread_id`

The helper remains private in the first version to keep the public surface small.

## Lifecycle

The node owns one long-lived subprocess per node instance.

### Startup

- `__init__` stores configuration only
- subprocess startup is lazy
- first `invoke` or `ainvoke` starts `codex app-server`
- after process start, the client sends `initialize`
- after successful initialization, the client sends `thread/start`
- returned `thread_id` is cached on the node instance

### Per invocation

- each node call sends a new `turn/start` for the cached `thread_id`
- the node waits until the turn reaches completion
- assistant output events are accumulated into one final text response
- the node returns `{"messages": [AIMessage(...)]}`

### Shutdown

- provide `close()` and `aclose()` for explicit cleanup
- these methods terminate the child process and clear cached lifecycle state
- if the process dies unexpectedly, the next invocation restarts it, runs a new
  `initialize`, creates a new thread, and proceeds without trying to restore the
  old thread

## Concurrency Model

The first version supports exactly one in-flight turn per node instance.

Enforcement:

- sync path guarded by `threading.Lock`
- async path guarded by `asyncio.Lock`

If the node is invoked concurrently on the same instance, the second caller waits
for the first instead of trying to open parallel turns on the same subprocess.

## Message Mapping

The first version is intentionally conservative.

### Input mapping

- Read the full conversation from `state[messages_key]`
- Accept standard LangChain/LangGraph message objects already used across tests
- Convert the message history into a single conversation payload for
  `turn/start`
- Preserve role order for `system`, `user`, and `assistant` messages

### Output mapping

- Collect assistant-facing output from App Server item events
- Concatenate assistant text fragments in arrival order
- Emit a single final `AIMessage` with the assembled content

Non-goals for v1:

- structured tool/event passthrough
- partial streaming into graph state
- multiple output messages from one turn

## Error Handling

Add a dedicated exception:

- `CodexAppServerError`

Raise it for:

- subprocess startup failure
- protocol errors
- invalid or malformed server responses
- unexpected EOF from the child process
- timeout waiting for turn completion
- turn completion with an error status

Raise `ValueError` for invalid LangGraph-side input such as missing
`messages_key` or unsupported message shapes.

## Dependency Strategy

Do not add a required OpenAI SDK dependency to `libs/prebuilt`.

The implementation should talk to `codex app-server` directly over stdio using
standard-library process and JSON handling. This keeps the dependency surface
consistent with the current `prebuilt` package.

## File Plan

Expected changes:

- Create: `libs/prebuilt/langgraph/prebuilt/codex_app_server.py`
- Modify: `libs/prebuilt/langgraph/prebuilt/__init__.py`
- Modify: `libs/prebuilt/pyproject.toml` only if test support needs an extra
  lightweight dependency, otherwise leave unchanged
- Create: `libs/prebuilt/tests/test_codex_app_server_node.py`

## Testing Strategy

Tests should be unit tests with a fake process transport rather than relying on
the real `codex` binary.

Required coverage:

1. lazy process start
2. `initialize` is sent exactly once
3. one `thread/start` is reused across multiple invocations
4. one `turn/start` is sent per invocation
5. assistant output events are assembled into one `AIMessage`
6. sync API works
7. async API works
8. process death triggers restart and new initialization
9. protocol or turn errors raise `CodexAppServerError`
10. invalid input state raises `ValueError`

## Implementation Constraints

- Follow repository TDD expectations: failing test first, then minimal code
- Keep the first version message-based and non-streaming
- Avoid broad new dependencies
- Match the style of existing `prebuilt` nodes and tests
- Do not implement approval-loop UX or raw event APIs in this slice

## Open Questions

None at this stage. The user selected:

- `libs/prebuilt` as the integration home
- node-managed subprocess startup
- one long-lived process per node instance
- one reused thread across invocations
- message-based public API instead of raw event output
