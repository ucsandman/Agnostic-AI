# Conversation Persistence

This example demonstrates how to persist conversation state and resume it later
using a `conversation_id`. This is useful for long-running interactions or when
you need to restart an agent without losing context.

## Resuming a Conversation

To resume a conversation, you need to: 1. Save the `conversation_id` from a
previous session. 2. Provide the `conversation_id` and the same `save_dir` in
the `LocalAgentConfig` for the new session.

```python
import tempfile
from google.antigravity import Agent, LocalAgentConfig

# Use a directory to save the conversation state
save_dir = tempfile.mkdtemp()

# --- Session 1: Setup Persistence Directory ---
config1 = LocalAgentConfig(save_dir=save_dir)

async with Agent(config1) as agent:
    await agent.chat("Remember this: my favorite color is blue.")
    # Retrieve the conversation ID
    conversation_id = agent.conversation_id

# --- Session 2: Resume conversation ---
config2 = LocalAgentConfig(
    conversation_id=conversation_id,
    save_dir=save_dir,
)

async with Agent(config2) as agent:
    response = await agent.chat("What is my favorite color?")
    print(await response.text())
```

> [!TIP] While `save_dir` persists the conversation trajectory history, you can
> use `app_data_dir` to control where generated artifacts (like `task.md`),
> scratch files, and media are written. See
> [app_data_dir_override.md](app_data_dir_override.md) for an example.
