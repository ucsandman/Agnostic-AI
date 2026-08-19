# System Instructions and Persona

This example demonstrates how to configure system instructions or persona for an
agent using the Google Antigravity SDK. You can either append to the default
instructions or completely overwrite them.

## Appending to Instructions (Recommended)

To add custom instructions or change the agent's identity while retaining the
default safety and operational guidelines, use `TemplatedSystemInstructions`.

Alternatively, you can pass a simple string, which will be treated as an
additional instruction section.

### Using TemplatedSystemInstructions

```python
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import TemplatedSystemInstructions

# Define the persona (identity)
identity = "You are a helpful assistant that speaks like a pirate."

# Configure the templated system instructions
templated_si = TemplatedSystemInstructions(
    identity=identity
)

config = LocalAgentConfig(
    system_instructions=templated_si
)

async with Agent(config) as agent:
    response = await agent.chat("Hello! Who are you?")
    print(await response.text())
```

### Using a Simple String (Shorthand for Append)

Passing a string will append it as a new section to the default instructions.

```python
from google.antigravity import Agent, LocalAgentConfig

config = LocalAgentConfig(
    system_instructions="Always respond in pirate slang."
)

async with Agent(config) as agent:
    response = await agent.chat("Hello!")
    print(await response.text())
```

## Overwriting Instructions (Advanced)

To completely replace all default system instructions (including safety and core
mandates), use `CustomSystemInstructions`.

> [!WARNING] Use this with caution. You will be responsible for providing all
> necessary safety and operational instructions.

```python
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import CustomSystemInstructions

custom_si = CustomSystemInstructions(
    text="You are a minimal assistant. You only answer with 'Yes' or 'No'."
)

config = LocalAgentConfig(
    system_instructions=custom_si
)

async with Agent(config) as agent:
    response = await agent.chat("Is the sky blue?")
    print(await response.text())
```
