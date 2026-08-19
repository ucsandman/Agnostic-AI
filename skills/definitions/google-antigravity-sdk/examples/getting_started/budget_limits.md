# Session Budget Limits & Stop Reasons

This guide demonstrates how to configure operational limits and proactive token budget controls using `BudgetConfig`, and how to inspect turn termination causes via `StopReason`.

---

## Code Example

```python
import asyncio
from google.antigravity import Agent, LocalAgentConfig, types

# 1. Configure session budget controls
config = LocalAgentConfig(
    budget_config=types.BudgetConfig(
        # Invocation dials
        max_model_calls=10,  # Halts session after 10 model generation calls
        max_tool_calls=25,   # Halts session after 25 tool executions

        # Proactive token budget dials
        max_input_tokens=100_000,   # Caps net uncached input prompt tokens
        max_output_tokens=20_000,   # Caps cumulative generated candidate tokens
        max_total_tokens=120_000,   # Caps total net token consumption (net input + output)
    )
)

async def main():
    async with Agent(config) as agent:
        response = await agent.chat("Analyze our quarterly financial metrics.")
        print(await response.text())

        # Inspect why the turn ended
        if response.stop_reason == types.StopReason.MAX_MODEL_CALLS_EXCEEDED:
            print("Session reached model call limit.")
        elif response.stop_reason == types.StopReason.MAX_TOOL_CALLS_EXCEEDED:
            print("Session reached tool invocation limit.")
        elif response.stop_reason == types.StopReason.MAX_INPUT_TOKENS_EXCEEDED:
            print("Prompt exceeded input token budget before dispatch.")
        elif response.stop_reason == types.StopReason.MAX_OUTPUT_TOKENS_EXCEEDED:
            print("Cumulative output exceeded output token budget.")
        elif response.stop_reason == types.StopReason.MAX_TOTAL_TOKENS_EXCEEDED:
            print("Cumulative total token budget exhausted.")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Key Concepts

* **`BudgetConfig`**: Attached to `LocalAgentConfig(budget_config=...)` or `AgentConfig.budget_config` to govern entire agent sessions.
* **Invocation Dials**:
  * `max_model_calls`: Guards against runaway reasoning cascades by capping generator invocations across the session.
  * `max_tool_calls`: Proactively intercepts and aborts repeated or looping tool calls once the ceiling is reached.
* **Token Budget Dials**:
  * `max_input_tokens`: Evaluated proactively before dispatch. Calculates net uncached prompt tokens (`prompt_tokens - cached_tokens`) to ensure predictable limits.
  * `max_output_tokens`: Tracks cumulative generated tokens across candidate and thinking tokens.
  * `max_total_tokens`: Tracks cumulative net token consumption (`net_input + output`).
* **`StopReason`**: Surfaced on `ChatResponse.stop_reason`, `Conversation.last_turn_stop_reason`, and `Step.stop_reason` to reliably distinguish normal termination (`UNSPECIFIED`) from budget halts and quota limits (`RESOURCE_EXHAUSTED`).
