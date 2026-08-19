# Hooks

Hooks in the Google Antigravity SDK allow you to intercept and observe various
lifecycle events of the agent, and in some cases, modify data or control
execution flow.

## Hook Types

### Session Hooks

#### Session Start Hook

Invoked when the agent session starts.

```python
from google.antigravity.hooks import hooks

@hooks.on_session_start
async def on_start():
    print("Session started")
```

#### Session End Hook

Invoked when the agent session ends.

```python
from google.antigravity.hooks import hooks

@hooks.on_session_end
async def on_end():
    print("Session ended")
```

### Turn Hooks

#### Pre-Turn Hook

Invoked before a turn starts. You can use this to inspect or reject the turn.

```python
from google.antigravity import types
from google.antigravity.hooks import hooks

@hooks.pre_turn
async def pre_turn(data: str) -> types.HookResult:
    print(f"Intercepted prompt: {data}")
    return types.HookResult(allow=True)
```

#### Post-Turn Hook

Invoked after a turn ends. Receives the final response content.

```python
from google.antigravity.hooks import hooks

@hooks.post_turn
async def post_turn(data: str):
    print(f"Final response: {data}")
```

### Tool Hooks

#### Pre-Tool Call (Decide) Hook

Invoked before a tool call to decide if it should proceed.

```python
from google.antigravity import types
from google.antigravity.hooks import hooks

@hooks.pre_tool_call_decide
async def pre_tool(data: types.ToolCall) -> types.HookResult:
    print(f"Approving tool call: {data.name}")
    return types.HookResult(allow=True)
```

#### Post-Tool Call Hook

Invoked after a tool call completes.

```python
from google.antigravity.hooks import hooks

@hooks.post_tool_call
async def post_tool(data):
    print("Tool execution completed")
```

#### On Tool Error Hook

Invoked when a tool fails, allowing for recovery or modification of the error
message the model sees.

```python
from google.antigravity.hooks import hooks

@hooks.on_tool_error
async def on_error(data: Exception):
    print(f"Tool failed: {data}")
    return None  # Let the error propagate
```

### Interaction Hook

Invoked when the agent needs user interaction (e.g., asking a question).

```python
from google.antigravity import types
from google.antigravity.hooks import hooks

@hooks.on_interaction
async def on_interact(data: types.AskQuestionInteractionSpec) -> types.QuestionHookResult:
    print(f"Interaction requested: {data}")
    return types.QuestionHookResult(responses=[])
```

### Compaction Hook

Invoked when a context compaction event occurs.

```python
from google.antigravity.hooks import hooks

@hooks.on_compaction
async def on_compact(data):
    print("Context compaction occurred")
```

## Registration

Hooks are registered when creating the `LocalAgentConfig`.

```python
from google.antigravity.connections.local import LocalAgentConfig

config = LocalAgentConfig(
    hooks=[
        on_start,
        on_end,
        pre_turn,
        post_turn,
        pre_tool,
        post_tool,
        on_error,
        on_compact,
        on_interact,
    ],
)
```
