
# Error Handling and Debugging in Google Antigravity SDK

This guide is intended for agents assisting users in troubleshooting their
Google Antigravity agents and making them more robust.

## Part 1: Debugging & Troubleshooting

When an agent fails or behaves unexpectedly, follow these steps to help the user debug.

### Finding Why It Failed

1.  **Inspect Agent Thoughts**: If the interface or logs expose the agent's internal monologue or "thoughts", examine them to understand what it was trying to do before the failure. See [hello_world.md](../examples/getting_started/hello_world.md) for how to stream thoughts.
2.  **Stream Logs**: Check the streaming logs (e.g., WebSocket connection logs, agent execution logs). These often contain the raw error messages and tracebacks. To see these logs in your console, you need to configure Python's root logger at the beginning of your script. Since the SDK uses standard Python logging, these settings apply globally to all SDK logs:

```python
import logging

# Configure the root logger to show INFO level messages and above
logging.basicConfig(level=logging.INFO)
```

For custom observability, users can use lifecycle hooks (like `PostToolCallHook` or `OnInteractionHook`) to create their own structured audit logs or execution traces. See [hooks.md](../examples/getting_started/hooks.md) for how to implement these.

---

## Part 2: Error Management

To make agents robust, they should handle errors gracefully and potentially recover from them.

### Catching Exceptions

The SDK provides specific exceptions that you can catch in your application code:

*   **`AntigravityValidationError`**: Raised when input validation fails (e.g., invalid parameters passed to a tool or configuration).
*   **`AntigravityConnectionError`**: Raised when connection issues occur (e.g., WebSocket drops, timeout).

Example:

```python
from google.antigravity import types

try:
    # Agent operations
    pass
except types.AntigravityValidationError as e:
    print(f"Validation failed: {e}")
except types.AntigravityConnectionError as e:
    print(f"Connection failed: {e}")
```

### Using Hooks for Error Recovery

You can use the `OnToolErrorHook` to intercept failures in tool execution. This is powerful because it allows the agent to see a fallback value instead of a raw error, potentially allowing it to self-correct and continue the conversation.

Here is a minimal example of implementing a fallback hook:

```python
from typing import Any, Optional
from google.antigravity.hooks import hooks

class FallbackHook(hooks.OnToolErrorHook):
    """Intercepts tool errors and returns targeted recovery guidance."""

    async def run(self, context: hooks.HookContext, data: Any) -> Optional[str]:
        # 'data' is the raised exception
        if isinstance(data, ValueError):
             # Guide the model toward resolution or provide a safe default
             return "[Could not complete operation. Please try with alternative parameters.]"

        # Let the harness handle other errors with default formatting
        return None
```

To use this hook, add it to the `hooks` list in your `LocalAgentConfig`. See [hooks.md](../examples/getting_started/hooks.md) doc so the agent can discover more info if it wants.

```python
from google.antigravity.connections.local import LocalAgentConfig

config = LocalAgentConfig(
    hooks=[FallbackHook()],
)
```
