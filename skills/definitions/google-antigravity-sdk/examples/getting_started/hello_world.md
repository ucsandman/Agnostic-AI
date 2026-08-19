# Hello World Example

This example demonstrates the most basic chat interaction with an agent using
the Google Antigravity SDK.

## Basic Chat

```python
from google.antigravity import Agent, LocalAgentConfig

async with Agent(LocalAgentConfig()) as agent:
    response = await agent.chat("Hello, World!")
    print(await response.text())
```

## Streaming Response

You can stream the response tokens as they arrive:

```python
from google.antigravity import Agent, LocalAgentConfig

async with Agent(LocalAgentConfig()) as agent:
    response = await agent.chat("Tell me a short joke.")
    async for token in response:
        print(token, end="", flush=True)
```

## Streaming Thoughts

You can also stream the model's reasoning process (thoughts) before the final
answer:

```python
from google.antigravity import Agent, LocalAgentConfig

async with Agent(LocalAgentConfig()) as agent:
    response = await agent.chat("What is the capital of France?")
    async for thought in response.thoughts:
        print(thought, end="", flush=True)
```

## Interactive Chat Loop

> [!NOTE] `run_interactive_loop()` is a helper method intended to make things
> extra simple for users who want a quick way to trial their agent in the
> terminal. For production use cases or custom interaction flows, you should
> implement your own loop using `agent.chat()` or by interacting directly with
> the `Conversation` object.

> [!WARNING] **This method is not intended for automated agents.**
> `run_interactive_loop()` requires interactive input from a human user in the
> terminal. If an automated process attempts to run this, it will block
> indefinitely waiting for input. This method should only be used by a human
> user when testing or interacting with the agent directly.

### Mechanics of the Interactive Loop

When you call `await run_interactive_loop(config)`, the following mechanics
apply:

-   **Prompts**:
    -   It displays a `User:` prompt for standard chat input.
    -   If the agent asks a structured question (e.g., via `AskQuestionHook`),
        it will display `Question: <text>` and prompt with `Response:`.
-   **Screen Output**:
    -   It prints "Starting interactive loop. Type 'exit' or 'quit' to end."
        when starting.
    -   It prints the agent's final response prefixed with `Agent:`.
-   **How to Quit**:
    -   Type `exit` or `quit` at the `User:` prompt.
    -   Use `Ctrl+C` or `Ctrl+D` to interrupt.

```python
from google.antigravity import LocalAgentConfig
from google.antigravity.utils.interactive import run_interactive_loop

# Starts a full interactive loop in the terminal
await run_interactive_loop(LocalAgentConfig())
```
