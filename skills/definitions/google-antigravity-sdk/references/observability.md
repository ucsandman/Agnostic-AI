# Observability

This guide covers how to monitor costs and execution behavior of agents built
with the Google Antigravity SDK.

## Token Usage Tracking

You can track token usage across a session using
`agent.conversation.total_usage`. This property returns a `UsageMetadata` object
containing cumulative counts for the session.

```python
from google.antigravity import Agent, LocalAgentConfig

# ... initialize agent ...

async with Agent(config) as agent:
    response = await agent.chat("Hello")
    usage = agent.conversation.total_usage
    print(f"Prompt tokens: {usage.prompt_token_count}")
    print(f"Candidates tokens: {usage.candidates_token_count}")
    print(f"Thoughts tokens: {usage.thoughts_token_count}")
    print(f"Total tokens: {usage.total_token_count}")
```

The `UsageMetadata` object contains: * `prompt_token_count`: Number of tokens in
the prompt. * `cached_content_token_count`: Number of tokens from cached
content. * `candidates_token_count`: Number of tokens in the generated
candidates (excluding thinking). * `thoughts_token_count`: Number of tokens used
for thinking/reasoning. * `total_token_count`: Sum of prompt + candidates +
thinking tokens.

> [!IMPORTANT] **Thinking tokens** can significantly increase the total count
> unexpectedly, especially with models that support extended thinking. Always
> monitor `thoughts_token_count` if you are using thinking models.

> [!CAUTION] If the agent execution fails (e.g., due to an invalid API key or
> backend error), token usage counts may be reported as 0.

## Standard Logging

The SDK uses standard Python logging. To see what the harness is doing, you can
enable `INFO` or `DEBUG` logging for the `google.antigravity` namespace.

```python
import logging

# Enable INFO logging for the SDK
logging.getLogger("google.antigravity").setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO)
```

This will output information about session start/stop, connection establishment,
and tool execution. For more details on using logs for troubleshooting, see the
[Error Handling and Debugging](error_handling.md)
guide.

## Custom Tracing with Hooks

For advanced monitoring, you can use lifecycle hooks to build custom audit logs
or execution traces. For example, you can use `PostToolCallHook` to inspect the
results of every tool call.

```python
from google.antigravity import types
from google.antigravity.hooks import hooks

@hooks.post_tool_call
async def audit_log_tool_call(data):
    # 'data' is the result of the tool execution
    print(f"[AUDIT] Tool execution completed. Result: {data}")

# Register the hook in your AgentConfig
config = LocalAgentConfig(
    hooks=[audit_log_tool_call],
    # ... other config ...
)
```

You can also use `PreToolCallDecideHook` to log tool calls *before* they are
executed, or even block them based on custom logic. For a complete list of
available hooks and practical examples, see the
[Hooks Example](../examples/getting_started/hooks.md).
